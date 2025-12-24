#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMU机械臂控制系统 - 主程序入口

功能:
- 读取三个IMU传感器数据
- 计算机械臂末端位置
- 通过ZeroMQ发送到远程B服务器
- 接收视频/音频反馈
- 发布调试数据到本地UI

使用方式:
    python main.py                    # 使用默认配置
    python main.py --config custom.yaml  # 使用自定义配置

环境:
    conda activate lerobot
"""

import sys
import os
import signal
import time
import threading
import argparse
import select
import numpy as np
from typing import Optional, Dict, Any

# OpenCV for video display
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[main] Warning: OpenCV不可用，视频显示功能将被禁用")

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from config import config
from core.imu_handler import IMUHandler
from core.zmq_manager import ZMQManager
from core.kinematics import Kinematics
from core.gripper import GripperController
from core.audio import AudioReceiver
from core.video import VideoReceiver


class IMUArmController:
    """
    IMU机械臂控制器主类
    
    整合所有模块，实现完整的控制流程:
    1. IMU数据读取 -> 运动学计算 -> 发送到B服务器
    2. 接收视频/音频反馈
    3. 发布数据到调试UI
    """
    
    # 终端显示常量
    BOX_WIDTH = 70
    
    def __init__(self):
        """初始化控制器"""
        self._running = False
        
        # 初始化各模块
        self.imu = IMUHandler()
        self.zmq = ZMQManager()
        self.kinematics = Kinematics()
        self.gripper = GripperController()
        self.audio = AudioReceiver()
        self.video = VideoReceiver()
        
        # 线程
        self._publisher_thread: Optional[threading.Thread] = None
        self._debug_publisher_thread: Optional[threading.Thread] = None
        self._ui_command_thread: Optional[threading.Thread] = None
        self._video_thread: Optional[threading.Thread] = None
        self._audio_thread: Optional[threading.Thread] = None
        
        # 当前状态
        self._current_raw_coords = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._current_clipped_coords = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._current_euler = {"imu1": {}, "imu2": {}, "imu3": {}, "imu4": {}}
        
        # 发布间隔
        self._publish_interval = 1.0 / config.control.publish_rate
        
        # 统计
        self._publish_count = 0
        self._total_publish_count = 0
        self._start_time = 0.0
        self._last_stat_time = 0.0
        
        # 终端显示控制
        self._display_interval = 0.3  # 终端刷新间隔（秒）
        self._skip_count = 0
        
        # 多相机窗口管理
        self._camera_window_names: Dict[str, str] = {}  # camera_name -> window_title
        self._created_windows: Dict[str, bool] = {}     # camera_name -> is_created
        
        # 录制控制状态
        self._recording_state = "idle"  # idle, recording, pending
        self._episode_frame_count = 0
        self._last_recording_command = None
        self._recording_start_time = 0.0
        self._use_fixed_repo_id = False  # 是否使用固定的 repo_id（命令行指定）
        
        # 夹爪控制来源: "imu" 或 "keyboard"
        self._gripper_control_source = "keyboard"
        self._gripper_imu_value = 0.0  # 陀螺仪计算的夹爪值
        
    def setup(self) -> bool:
        """
        初始化所有连接
        
        Returns:
            bool: 初始化是否成功
        """
        print("=" * 50)
        print("IMU机械臂控制系统 - 初始化")
        print("=" * 50)
        
        # 连接IMU串口
        if not self.imu.connect():
            print("[Warning] IMU串口连接失败，将使用模拟数据")
            # return False  # 注释掉以允许无IMU运行
        
        # 建立ZMQ连接
        use_tunnel = config.network.ssh_tunnel.enabled
        if not self.zmq.setup_control_channel(use_tunnel=use_tunnel):
            print("[Warning] B服务器连接失败，将以离线模式运行")
        
        # 设置调试发布器
        if config.network.debug_ui_enabled:
            if not self.zmq.setup_debug_publisher():
                print("[Warning] 调试发布器绑定失败")
            # 同时设置 UI 命令接收器
            if not self.zmq.setup_ui_command_receiver():
                print("[Warning] UI命令接收器绑定失败")
        
        # 设置视频接收器
        if config.network.video.enabled:
            self.zmq.setup_video_receiver()
        
        # 设置音频接收器  
        if config.network.audio.enabled:
            self.zmq.setup_audio_receiver()
        
        # 设置LeRobot发布器
        if config.network.lerobot.enabled:
            self.zmq.setup_lerobot_publisher()
        
        print("[OK] 初始化完成")
        return True
    
    def start(self):
        """启动控制系统"""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        
        # 启动IMU读取
        self.imu.set_callback(self._on_imu_data)
        self.imu.start()
        
        # 启动夹爪控制（禁用其自带键盘监听，由统一键盘线程处理）
        self.gripper.start(enable_keyboard=False)
        
        # 启动ZMQ
        self.zmq.start()
        
        # 启动发布线程
        self._publisher_thread = threading.Thread(
            target=self._publisher_loop,
            daemon=True,
            name="Publisher"
        )
        self._publisher_thread.start()
        
        # 启动调试发布线程
        if config.network.debug_ui_enabled:
            self._debug_publisher_thread = threading.Thread(
                target=self._debug_publisher_loop,
                daemon=True,
                name="DebugPublisher"
            )
            self._debug_publisher_thread.start()
            
            # 启动 UI 命令接收线程
            self._ui_command_thread = threading.Thread(
                target=self._ui_command_loop,
                daemon=True,
                name="UICommandReceiver"
            )
            self._ui_command_thread.start()
        
        # 启动视频接收线程
        if config.network.video.enabled:
            self._video_thread = threading.Thread(
                target=self._video_receiver_loop,
                daemon=True,
                name="VideoReceiver"
            )
            self._video_thread.start()
            self.video.start()
        
        # 启动音频接收线程
        if config.network.audio.enabled:
            self._audio_thread = threading.Thread(
                target=self._audio_receiver_loop,
                daemon=True,
                name="AudioReceiver"
            )
            self._audio_thread.start()
            self.audio.start()
        
        # 打印启动信息（借鉴 triple 风格）
        self._print_startup_banner()
    
    def stop(self):
        """停止控制系统"""
        print("\n正在停止...")
        
        self._running = False
        
        # 停止各模块
        self.imu.stop()
        self.gripper.stop()
        self.zmq.stop()
        self.audio.stop()
        self.video.stop()
        
        # 等待线程结束
        threads = [
            self._publisher_thread,
            self._debug_publisher_thread,
            self._video_thread,
            self._audio_thread,
            getattr(self, '_keyboard_thread', None),
        ]
        for t in threads:
            if t and t.is_alive():
                t.join(timeout=1.0)
        
        # 清理资源
        self.zmq.cleanup()
        
        # 打印最终统计
        self._print_final_stats()
    
    # ==================== 终端显示方法 ====================
    
    def _print_startup_banner(self):
        """打印启动横幅（借鉴 triple 风格）"""
        W = self.BOX_WIDTH
        
        print("\n" + "=" * W)
        print("🤖 IMU机械臂控制系统 (Modular Full Project)")
        print("=" * W)
        print(f"串口设备: {config.imu.serial_port}")
        print(f"波特率: {config.imu.baudrate}")
        print(f"IMU 1 (杆1): 地址 0x50 (80)  │  长度: {config.arm.L1*1000:.0f} mm")
        print(f"IMU 2 (杆2): 地址 0x51 (81)  │  长度: {config.arm.L2*1000:.0f} mm")
        print(f"IMU 3 (机械爪): 地址 0x52 (82)")
        print(f"IMU 4 (手指): 地址 0x54 (84)")
        print("─" * W)
        
        # ZMQ 连接信息
        print(f"📡 ZMQ 发送到 B 端: tcp://{config.network.b_server.host}:{config.network.b_server.port} (PUSH)")
        
        if config.network.lerobot.enabled:
            print(f"📡 ZMQ 发送到 LeRobot: tcp://{config.network.lerobot.host}:{config.network.lerobot.port} (PUSH)")
        else:
            print(f"📡 ZMQ LeRobot: 未启用")
        
        if config.network.debug_ui_enabled:
            print(f"🖥️  调试 UI: tcp://*:{config.network.debug_ui_port} (PUB)")
        
        if config.network.video.enabled:
            print(f"📹 视频接收: tcp://localhost:{config.network.video.port} (SUB)")
        
        if config.network.audio.enabled:
            print(f"🔊 音频接收: tcp://localhost:{config.network.audio.port} (SUB)")
        
        print("─" * W)
        print(f"发布频率: {config.control.publish_rate} Hz (间隔 {1000/config.control.publish_rate:.0f} ms)")
        print(f"在线检查: {'✅ 启用' if config.control.online_only else '❌ 禁用'}")
        print("=" * W)
        print()
        print("⌨️  键盘控制已启用:")
        print("    按住 '1' - 夹爪持续打开")
        print("    按住 '2' - 夹爪持续闭合")
        print("    按 'S' - 开始录制 episode")
        print("    按 'E' - 结束录制 episode")
        print("    按 'Y' - 保存当前 episode")
        print("    按 'N' - 丢弃当前 episode")
        print("    按 'q' 或 Ctrl+C - 退出程序")
        print("=" * W)
        print()
        print("⏳ 等待 IMU 数据...")
        print()

    def _print_final_stats(self):
        """打印最终统计信息"""
        elapsed = time.time() - self._start_time
        avg_rate = self._total_publish_count / elapsed if elapsed > 0 else 0
        
        print("\n" + "=" * self.BOX_WIDTH)
        print("📊 运行统计")
        print("=" * self.BOX_WIDTH)
        print(f"  运行时间: {elapsed:.1f} 秒")
        print(f"  发布次数: {self._total_publish_count}")
        print(f"  平均发布率: {avg_rate:.1f} Hz")
        print(f"  跳过次数: {self._skip_count}")
        print("=" * self.BOX_WIDTH)
        print("✅ 已安全退出")
    
    def _print_status_display(self, euler1: dict, euler2: dict, euler3: dict,
                               raw_pos: tuple, mapped_pos: tuple, 
                               gripper_val: float, actual_rate: float,
                               euler4: dict = None):
        """
        打印优雅的终端状态显示（借鉴 triple 的风格）
        
        使用 Box Drawing 字符和 Emoji 图标
        """
        # ANSI 清屏
        print("\033[H\033[J", end="")
        
        W = self.BOX_WIDTH
        
        # 默认 euler4
        if euler4 is None:
            euler4 = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        
        # IMU 在线状态
        imu1_online = self.imu.is_online(0x50)
        imu2_online = self.imu.is_online(0x51)
        imu3_online = self.imu.is_online(0x52)
        imu4_online = self.imu.is_online(0x54)
        
        # Yaw 偏移
        yaw1_offset = self.imu.get_yaw_offset(0x50)
        yaw2_offset = self.imu.get_yaw_offset(0x51)
        yaw3_offset = self.imu.get_yaw_offset(0x52)
        yaw4_offset = self.imu.get_yaw_offset(0x54)
        
        # ========== IMU 1 ==========
        print("┌" + "─" * W + "┐")
        print(f"│ IMU 1 (杆1) - 地址: 0x50 (80)  │  长度: {config.arm.L1*1000:.0f} mm".ljust(W+1) + "│")
        status1 = "✅ 在线" if imu1_online else "⚠️  离线"
        yaw1_str = f"(偏移:{yaw1_offset:.2f}°)" if yaw1_offset is not None else "(未归零)"
        print(f"│ 状态: {status1}".ljust(W+1) + "│")
        print(f"│ Roll = {euler1.get('roll', 0):8.2f}°  │  Pitch = {euler1.get('pitch', 0):8.2f}°  │  Yaw = {euler1.get('yaw', 0):8.2f}° {yaw1_str}".ljust(W+17) + "│")
        
        # ========== IMU 2 ==========
        print("├" + "─" * W + "┤")
        print(f"│ IMU 2 (杆2) - 地址: 0x51 (81)  │  长度: {config.arm.L2*1000:.0f} mm".ljust(W+1) + "│")
        status2 = "✅ 在线" if imu2_online else "⚠️  离线"
        yaw2_str = f"(偏移:{yaw2_offset:.2f}°)" if yaw2_offset is not None else "(未归零)"
        print(f"│ 状态: {status2}".ljust(W+1) + "│")
        print(f"│ Roll = {euler2.get('roll', 0):8.2f}°  │  Pitch = {euler2.get('pitch', 0):8.2f}°  │  Yaw = {euler2.get('yaw', 0):8.2f}° {yaw2_str}".ljust(W+17) + "│")
        
        # ========== IMU 3 ==========
        print("├" + "─" * W + "┤")
        print(f"│ IMU 3 (机械爪) - 地址: 0x52 (82)".ljust(W+1) + "│")
        status3 = "✅ 在线" if imu3_online else "⚠️  离线"
        yaw3_str = f"(偏移:{yaw3_offset:.2f}°)" if yaw3_offset is not None else "(未归零)"
        print(f"│ 状态: {status3}".ljust(W+1) + "│")
        print(f"│ Roll = {euler3.get('roll', 0):8.2f}°  │  Pitch = {euler3.get('pitch', 0):8.2f}°  │  Yaw = {euler3.get('yaw', 0):8.2f}° {yaw3_str}".ljust(W+17) + "│")
        
        # ========== IMU 4 (手指) ==========
        print("├" + "─" * W + "┤")
        print(f"│ IMU 4 (手指) - 地址: 0x54 (84)".ljust(W+1) + "│")
        status4 = "✅ 在线" if imu4_online else "⚠️  离线"
        yaw4_str = f"(偏移:{yaw4_offset:.2f}°)" if yaw4_offset is not None else "(未归零)"
        print(f"│ 状态: {status4}".ljust(W+1) + "│")
        print(f"│ Roll = {euler4.get('roll', 0):8.2f}°  │  Pitch = {euler4.get('pitch', 0):8.2f}°  │  Yaw = {euler4.get('yaw', 0):8.2f}° {yaw4_str}".ljust(W+17) + "│")
        
        # ========== Pitch 差值 (机械爪 vs 手指) ==========
        print("├" + "─" * W + "┤")
        pitch3 = euler3.get('pitch', 0)
        pitch4 = euler4.get('pitch', 0)
        pitch_diff_raw = abs(pitch3 - pitch4)
        # Clip 到 30-130 范围
        pitch_diff_clipped = max(30, min(130, pitch_diff_raw))
        # 缩放到 1~0 区间 (30→1, 130→0)
        gripper_normalized = 1.0 - (pitch_diff_clipped - 30) / 100.0
        
        # 根据控制来源显示不同样式
        if self._gripper_control_source == "imu":
            ctrl_indicator = "🟢 IMU控制中"
        else:
            ctrl_indicator = "⚪ 未启用(键盘控制)"
        print(f"│ 🤏 手指张合: |{pitch3:.1f}° - {pitch4:.1f}°| = {pitch_diff_raw:.1f}° → {gripper_normalized:.3f}  {ctrl_indicator}".ljust(W+5) + "│")
        print("└" + "─" * W + "┘")
        
        # ========== 末端位置 & 发布状态 ==========
        print()
        print("┌" + "─" * W + "┐")
        print(f"│ 🤖 机械臂末端位置 & ZeroMQ 发布状态".ljust(W+2) + "│")
        print("├" + "─" * W + "┤")
        print(f"│ 原始位置: [{raw_pos[0]:7.3f}, {raw_pos[1]:7.3f}, {raw_pos[2]:7.3f}] m".ljust(W+1) + "│")
        print(f"│ 映射位置: [{mapped_pos[0]:7.3f}, {mapped_pos[1]:7.3f}, {mapped_pos[2]:7.3f}] m".ljust(W+1) + "│")
        
        # 发送的 x 值（水平距离 = sqrt(x^2 + y^2)）
        sent_x = 0.52-(0.52-pow(raw_pos[0]*raw_pos[0] + raw_pos[1]*raw_pos[1], 0.5))*2
        print(f"│ 📏 发送X (水平距离): {sent_x:.4f} m = {sent_x*1000:.1f} mm".ljust(W+1) + "│")
        
        # Shoulder Pan 角度
        shoulder_pan = np.arctan2(raw_pos[1], raw_pos[0])
        shoulder_pan_deg = np.rad2deg(shoulder_pan)
        print(f"│ Shoulder Pan: {shoulder_pan_deg:7.2f}° ({shoulder_pan:7.4f} rad)".ljust(W+1) + "│")
        
        # 发送姿态（弧度）
        sent_roll = np.deg2rad(euler3.get('roll', 0))
        sent_pitch = np.deg2rad(euler3.get('pitch', 0))
        sent_yaw = np.deg2rad(euler3.get('yaw', 0))
        print(f"│ 发送姿态: Roll={sent_roll:7.4f}, Pitch={sent_pitch:7.4f}, Yaw={sent_yaw:7.4f} rad".ljust(W+1) + "│")
        
        # 夹爪状态（进度条）+ 控制来源
        gripper_percent = gripper_val * 100
        bar_len = 20
        filled = int(gripper_val * bar_len)
        gripper_bar = "█" * filled + "░" * (bar_len - filled)
        
        # 显示控制来源
        if self._gripper_control_source == "imu":
            source_icon = "🎛️ IMU"
        else:
            source_icon = "⌨️ 键盘"
        print(f"│ 🦾 夹爪开合: [{gripper_bar}] {gripper_percent:5.1f}%  ({source_icon})".ljust(W+5) + "│")
        
        print("├" + "─" * W + "┤")
        
        # 发布统计
        print(f"│ 📡 发布频率: {actual_rate:.1f} Hz  │  消息计数: {self._total_publish_count}".ljust(W+1) + "│")
        
        # ZMQ 连接状态
        ctrl_status = "✅" if self.zmq.connection_status.get('control') else "❌"
        debug_status = "✅" if self.zmq.connection_status.get('debug') else "❌"
        lerobot_status = "✅" if self.zmq.connection_status.get('lerobot') else "⬜"
        print(f"│ 🔗 连接: B服务器{ctrl_status}  调试UI{debug_status}  LeRobot{lerobot_status}".ljust(W+5) + "│")
        
        print("├" + "─" * W + "┤")
        
        # 视频状态
        if config.network.video.enabled:
            video_frames = getattr(self.video, 'frame_count', 0)
            print(f"│ 📹 视频: 帧数={video_frames:6d}".ljust(W+1) + "│")
        else:
            print(f"│ 📹 视频: 未启用".ljust(W+1) + "│")
        
        # 音频状态
        if config.network.audio.enabled:
            audio_frames = getattr(self.audio, 'frame_count', 0)
            print(f"│ 🔊 音频: 帧数={audio_frames:6d}".ljust(W+1) + "│")
        else:
            print(f"│ 🔊 音频: 未启用".ljust(W+1) + "│")
        
        # 调试UI状态
        if config.network.debug_ui_enabled:
            print(f"│ 🖥️  调试UI: 端口 {config.network.debug_ui_port} (PUB)".ljust(W+2) + "│")
        else:
            print(f"│ 🖥️  调试UI: 未启用".ljust(W+2) + "│")
        
        # 录制状态
        print("├" + "─" * W + "┤")
        if self._recording_state == "recording":
            elapsed = time.time() - self._recording_start_time
            status_text = f"🔴 录制中 - 帧数: {self._episode_frame_count}, 时长: {elapsed:.1f}s"
        elif self._recording_state == "pending":
            status_text = f"⏸️  等待保存/丢弃 - 帧数: {self._episode_frame_count} (按Y/N)"
        else:
            status_text = "⚪ 未录制 (按S开始)"
        print(f"│ 📼 {status_text}".ljust(W+3) + "│")
        
        print("└" + "─" * W + "┘")
        
        # 控制提示
        print()
        print("─" * W)
        print("⌨️  控制: '1'/'2' 夹爪 │ S:开始 E:结束 Y:保存 N:丢弃 │ q:退出")
        print("─" * W)
    
    # ==================== 回调和循环 ====================
    
    def _on_imu_data(self, address: int, roll: float, pitch: float, yaw: float):
        """IMU数据回调"""
        # 由IMU模块自动更新数据，这里可以添加额外处理
        pass
    
    def _publisher_loop(self):
        """
        主数据发布循环
        
        同时负责:
        1. 读取IMU数据
        2. 计算运动学
        3. 发送到B服务器和LeRobot
        4. 定期刷新终端显示
        """
        self._last_stat_time = time.time()
        
        while self._running:
            loop_start = time.time()
            
            try:
                # ========== 步骤1: 检查IMU在线状态 ==========
                imu1_online = self.imu.is_online(0x50)
                imu2_online = self.imu.is_online(0x51)
                imu3_online = self.imu.is_online(0x52)
                
                # 如果启用了 online_only 模式，检查所有 IMU 是否在线
                if config.control.online_only and not (imu1_online and imu2_online and imu3_online):
                    self._skip_count += 1
                    if self._skip_count % 25 == 0:  # 每几秒打印一次
                        print(f"⚠️  等待IMU在线... IMU1: {'✓' if imu1_online else '✗'}, "
                              f"IMU2: {'✓' if imu2_online else '✗'}, "
                              f"IMU3: {'✓' if imu3_online else '✗'} (跳过 {self._skip_count} 次)")
                    time.sleep(self._publish_interval)
                    continue
                
                # ========== 步骤2: 读取IMU数据 ==========
                euler1 = {
                    "roll": self.imu.get_euler(0x50, "roll"),
                    "pitch": self.imu.get_euler(0x50, "pitch"),
                    "yaw": self.imu.get_normalized_yaw(0x50),
                }
                euler1["yaw"]=euler1["yaw"]*2  # IMU1 Yaw 放大 2 倍以增强控制灵敏度
                euler2 = {
                    "roll": self.imu.get_euler(0x51, "roll"),
                    "pitch": self.imu.get_euler(0x51, "pitch"),
                    "yaw": self.imu.get_normalized_yaw(0x51),
                }
                euler3 = {
                    "roll": self.imu.get_euler(0x52, "roll"),
                    "pitch": self.imu.get_euler(0x52, "pitch"),
                    "yaw": self.imu.get_normalized_yaw(0x52),
                }
                euler4 = {
                    "roll": self.imu.get_euler(0x54, "roll"),
                    "pitch": self.imu.get_euler(0x54, "pitch"),
                    "yaw": self.imu.get_normalized_yaw(0x54),
                }
                
                # 保存当前欧拉角（用于显示）
                self._current_euler = {"imu1": euler1, "imu2": euler2, "imu3": euler3, "imu4": euler4}
                
                # ========== 步骤3: 计算末端位置 ==========
                try:
                    end_pos, link1_pos, link2_pos = self.kinematics.calculate_end_effector(
                        euler1, euler2
                    )
                except Exception as e:
                    print(f"⚠️  运动学计算失败: {e}")
                    end_pos = np.array([0.0, 0.0, 0.0])
                
                # ========== 步骤3.5: 计算夹爪值 (IMU4 或 键盘) ==========
                # 检查 IMU4 (0x54) 是否配置且在线
                imu4_configured = 'imu4' in config.imu.addresses
                imu4_online = self.imu.is_online(0x54) if imu4_configured else False
                
                if imu4_configured and imu4_online:
                    # 使用陀螺仪 Pitch 差值控制夹爪
                    pitch3 = euler3["pitch"]
                    pitch4 = euler4["pitch"]
                    pitch_diff_raw = abs(pitch3 - pitch4)
                    # Clip 到 30-130 范围
                    pitch_diff_clipped = max(30, min(130, pitch_diff_raw))
                    # 缩放到 1~0 区间 (30→1, 130→0)
                    gripper_value = 1.0 - (pitch_diff_clipped - 30) / 100.0
                    self._gripper_control_source = "imu"
                    self._gripper_imu_value = gripper_value
                else:
                    # 使用键盘控制夹爪
                    gripper_value = self.gripper.value
                    self._gripper_control_source = "keyboard"
                
                # 原始坐标
                raw_x, raw_y, raw_z = end_pos[0], end_pos[1], end_pos[2]
                raw_base = euler3["yaw"]
                
                self._current_raw_coords = (raw_x, raw_y, raw_z, raw_base, gripper_value)
                
                # ========== 步骤4: 坐标映射 ==========
                mapped = self.kinematics.map_position_with_gripper(
                    end_pos, raw_base, gripper_value
                )
                self._current_clipped_coords = tuple(mapped)
                
                # ========== 步骤5: 构建并发送控制数据 ==========
                control_data = {
                    "type": "control",
                    "timestamp": time.time(),
                    "robot_info": {
                        "shoulder_pan": float(np.arctan2(raw_y, raw_x)),
                        "wrist_roll": float(np.deg2rad(euler3["roll"])),
                        "pitch": float(np.deg2rad(euler3["pitch"])),
                        "x": 0.52-(0.52-float(pow(end_pos[0]*end_pos[0]+end_pos[1]*end_pos[1], 0.5)))*2,  # x 坐标系转换
                        "y": float(end_pos[2]),  # z -> y 坐标系转换
                        "gripper": float(gripper_value),
                    },
                    "coordinates": {
                        "x": float(pow(mapped[0]*mapped[0]+mapped[1]*mapped[1], 0.5)),
                        "y": mapped[1],
                        "z": mapped[2],
                        "base": mapped[3],
                        "gripper": mapped[4],
                    },
                    "raw": {
                        "x": raw_x,
                        "y": raw_y,
                        "z": raw_z,
                        "base": raw_base,
                        "gripper": gripper_value,
                    },
                    "imu": {
                        "imu1": euler1,
                        "imu2": euler2,
                        "imu3": euler3,
                        "imu4": euler4,
                    },
                    "status": {
                        "imu1_online": imu1_online,
                        "imu2_online": imu2_online,
                        "imu3_online": imu3_online,
                        "imu4_online": self.imu.is_online(0x54),
                    }
                }
                
                # 添加录制控制命令（可选字段）
                if self._last_recording_command:
                    control_data["recording"] = self._last_recording_command
                    self._last_recording_command = None  # 发送后清除
                
                # 如果正在录制，增加帧计数
                if self._recording_state == "recording":
                    self._episode_frame_count += 1
                
                # 发送到B服务器
                self.zmq.send_control_data(control_data)
                
                # 发送到LeRobot
                if config.network.lerobot.enabled:
                    lerobot_data = {
                        "type": "lerobot",
                        "timestamp": time.time(),
                        "position": list(mapped[:3]),
                        "orientation": [
                            float(np.deg2rad(euler3["roll"])),
                            float(np.deg2rad(euler3["pitch"])),
                            float(np.deg2rad(euler3["yaw"])),
                        ],
                        "gripper": float(gripper_value),
                    }
                    self.zmq.send_to_lerobot(lerobot_data)
                
                self._publish_count += 1
                self._total_publish_count += 1
                
                # ========== 步骤6: 定期刷新终端显示 ==========
                current_time = time.time()
                if current_time - self._last_stat_time >= self._display_interval:
                    # 计算实际发布率
                    actual_rate = self._publish_count / (current_time - self._last_stat_time)
                    
                    # 刷新终端显示
                    self._print_status_display(
                        euler1, euler2, euler3,
                        (raw_x, raw_y, raw_z),
                        mapped[:3],
                        gripper_value,
                        actual_rate,
                        euler4  # 新增 IMU4 数据
                    )
                    
                    # 重置统计
                    self._publish_count = 0
                    self._last_stat_time = current_time
                
                # ========== 步骤7: 精确定时控制 ==========
                elapsed = time.time() - loop_start
                to_sleep = max(0.0, self._publish_interval - elapsed)
                time.sleep(to_sleep)
                
            except Exception as e:
                print(f"[Error] 发布循环异常: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
    
    def _debug_publisher_loop(self):
        """
        调试数据发布循环 (与triple debug_publisher_thread完全一致的数据格式)
        
        发送给 pyqt5_viewer 使用，格式必须匹配UI期望的结构
        """
        debug_interval = 1.0 / config.control.publish_rate
        publish_count = 0
        last_debug_print = 0
        
        while self._running:
            try:
                current_time = time.time()
                
                # 获取IMU欧拉角数据 (与triple格式一致)
                euler1 = self.imu.get_euler_dict(0x50)
                euler2 = self.imu.get_euler_dict(0x51)
                euler3 = self.imu.get_euler_dict(0x52)
                euler4 = self.imu.get_euler_dict(0x54)  # 新增 IMU4 (手指)
                
                # 每2秒打印一次调试信息
                if current_time - last_debug_print > 2.0:
                    print(f"[DEBUG SEND] euler1={euler1}, euler2={euler2}")
                    last_debug_print = current_time
                
                # 获取IMU在线状态
                imu1_online = self.imu.is_online(0x50)
                imu2_online = self.imu.is_online(0x51)
                imu3_online = self.imu.is_online(0x52)
                imu4_online = self.imu.is_online(0x54)  # 新增 IMU4
                
                # 获取视频帧 (如果有)
                video_left = self.video.get_latest_frame('left') if hasattr(self.video, 'get_latest_frame') else None
                video_top = self.video.get_latest_frame('top') if hasattr(self.video, 'get_latest_frame') else None
                
                # 获取音频数据 (如果有)
                audio_waveform = getattr(self.audio, 'latest_waveform', None)
                audio_rms = getattr(self.audio, 'latest_rms', 0.0)
                audio_frame_count = getattr(self.audio, 'frame_count', 0)
                audio_underrun_count = getattr(self.audio, 'underrun_count', 0)
                
                # 计算发布频率
                uptime = current_time - self._start_time
                publish_rate = self._publish_count / uptime if uptime > 0 else 0.0
                
                # === 构建调试数据 (与triple debug_data 完全一致) ===
                debug_data = {
                    "timestamp": current_time,
                    "imu1": {
                        "roll": float(euler1["roll"]),
                        "pitch": float(euler1["pitch"]),
                        "yaw": float(euler1["yaw"])
                    },
                    "imu2": {
                        "roll": float(euler2["roll"]),
                        "pitch": float(euler2["pitch"]),
                        "yaw": float(euler2["yaw"])
                    },
                    "imu3": {
                        "roll": float(euler3["roll"]),
                        "pitch": float(euler3["pitch"]),
                        "yaw": float(euler3["yaw"])
                    },
                    "imu4": {
                        "roll": float(euler4["roll"]),
                        "pitch": float(euler4["pitch"]),
                        "yaw": float(euler4["yaw"])
                    },
                    "position": {
                        "raw": list(self._current_raw_coords) if self._current_raw_coords else [0.0, 0.0, 0.0],
                        "mapped": list(self._current_clipped_coords) if self._current_clipped_coords else [0.0, 0.0, 0.0]
                    },
                    "gripper": float(self.gripper.value),
                    "online_status": {
                        "imu1": imu1_online,
                        "imu2": imu2_online,
                        "imu3": imu3_online,
                        "imu4": imu4_online
                    },
                    "stats": {
                        "publish_count": publish_count,
                        "publish_rate": publish_rate,
                        "video_frame_count": self.video.frame_count if hasattr(self.video, 'frame_count') else 0,
                        "video_latency": getattr(self.video, 'latency', 0.0)
                    },
                    "config": {
                        "L1": config.arm.L1,
                        "L2": config.arm.L2,
                        "yaw_mode": config.imu.yaw_normalization_mode
                    },
                    "video_left": video_left,  # JPEG bytes or None
                    "video_top": video_top,    # JPEG bytes or None
                    "audio": {
                        "waveform": audio_waveform.tolist() if audio_waveform is not None else [],
                        "rms": float(audio_rms),
                        "frame_count": audio_frame_count,
                        "underrun_count": audio_underrun_count,
                        "receiving": self.audio.is_receiving if hasattr(self.audio, 'is_receiving') else False
                    }
                }
                
                # 发布 (使用pickle格式，与triple一致)
                self.zmq.publish_debug_data(debug_data)
                publish_count += 1
                
                time.sleep(debug_interval)
                
            except Exception as e:
                print(f"[Error] 调试发布循环异常: {e}")
                time.sleep(0.1)
    
    def _init_opencv_windows(self) -> Dict[str, bool]:
        """
        初始化OpenCV视频显示窗口（动态多相机支持）
        
        Returns:
            Dict[str, bool]: 相机名称到窗口是否创建成功的映射
        """
        if not CV2_AVAILABLE or not config.network.video.display_opencv:
            return {}
        
        # 预定义的相机窗口配置 (相机名称 -> 窗口标题)
        self._camera_window_names = {
            'left_wrist': 'Left Wrist Camera',
            'left': 'Left Side Camera', 
            'right': 'Right Side Camera',
            'top': 'Top Camera',  # 保留兼容
        }
        self._created_windows: Dict[str, bool] = {}
        return self._created_windows
    
    def _ensure_camera_window(self, camera_name: str) -> bool:
        """
        确保指定相机的窗口已创建
        
        Args:
            camera_name: 相机名称
            
        Returns:
            bool: 窗口是否可用
        """
        if not CV2_AVAILABLE:
            return False
            
        if camera_name in self._created_windows:
            return self._created_windows[camera_name]
        
        # 获取窗口标题
        window_title = self._camera_window_names.get(camera_name, f'Camera: {camera_name}')
        
        try:
            cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window_title, 640, 480)
            self._created_windows[camera_name] = True
            print(f"✓ 创建相机窗口: {window_title}")
            return True
        except Exception as e:
            print(f"⚠️  创建窗口 {window_title} 失败: {e}")
            self._created_windows[camera_name] = False
            return False
    
    def _video_receiver_loop(self):
        """
        视频接收循环（支持动态多相机）
        
        功能:
        - 从ZMQ接收视频帧
        - 传递给VideoReceiver处理
        - 动态创建每个相机的显示窗口
        """
        # 初始化OpenCV窗口管理
        opencv_enabled = config.network.video.display_opencv and CV2_AVAILABLE
        if opencv_enabled:
            self._init_opencv_windows()
        
        video_frame_count = 0
        
        while self._running:
            try:
                frame_data = self.zmq.receive_video_frame()
                if frame_data:
                    # 处理视频数据（解码并存储）
                    self.video.process_data(frame_data)
                    video_frame_count += 1
                    
                    # OpenCV显示（动态多相机）
                    if opencv_enabled:
                        frames = self.video.get_all_frames()
                        
                        for camera_name, frame in frames.items():
                            if frame is not None:
                                # 确保窗口已创建
                                if self._ensure_camera_window(camera_name):
                                    # 获取窗口标题
                                    window_title = self._camera_window_names.get(
                                        camera_name, f'Camera: {camera_name}'
                                    )
                                    
                                    # 叠加信息
                                    display_frame = frame.copy()
                                    cv2.putText(
                                        display_frame, 
                                        f"{camera_name} - Frame: {video_frame_count}", 
                                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                                        0.6, (0, 255, 255), 2
                                    )
                                    cv2.imshow(window_title, display_frame)
                        
                        # 处理按键（按 'q' 退出）
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord('q'):
                            print("\n⚠️  视频窗口按下'q'，退出...")
                            self._running = False
                            break
                else:
                    time.sleep(0.001)
            except Exception as e:
                print(f"[Error] 视频接收异常: {e}")
                time.sleep(0.1)
        
        # 清理OpenCV窗口
        if opencv_enabled:
            cv2.destroyAllWindows()
    
    def _audio_receiver_loop(self):
        """音频接收循环"""
        while self._running:
            try:
                audio_data = self.zmq.receive_audio_data()
                if audio_data:
                    self.audio.process_data(audio_data)
                else:
                    time.sleep(0.001)
            except Exception as e:
                print(f"[Error] 音频接收异常: {e}")
                time.sleep(0.1)
    
    def _ui_command_loop(self):
        """UI 命令接收循环"""
        print("[UI Command] 命令接收器已启动")
        while self._running:
            try:
                cmd = self.zmq.receive_ui_command()
                if cmd:
                    self._handle_ui_command(cmd)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"[Error] UI命令接收异常: {e}")
                time.sleep(0.1)
    
    def _handle_ui_command(self, cmd: dict):
        """处理来自UI的命令"""
        cmd_type = cmd.get("type", "")
        
        if cmd_type == "gripper":
            action = cmd.get("action", "")
            
            if action == "open":
                # 增大夹爪值
                new_value = min(1.0, self.gripper.value + 0.05)
                self.gripper.set_value(new_value)
                print(f"[UI Command] 夹爪打开: {new_value:.2f}")
                
            elif action == "close":
                # 减小夹爪值
                new_value = max(0.0, self.gripper.value - 0.05)
                self.gripper.set_value(new_value)
                print(f"[UI Command] 夹爪关闭: {new_value:.2f}")
                
            elif action == "stop":
                # 停止（不做任何操作）
                pass
                
            elif action == "set":
                # 直接设置值
                value = cmd.get("value", self.gripper.value)
                self.gripper.set_value(value)
        
        else:
            print(f"[UI Command] 未知命令类型: {cmd_type}")
    
    # ==================== 录制控制方法 ====================
    
    def _start_recording(self):
        """开始录制"""
        if self._recording_state == "idle":
            self._recording_state = "recording"
            self._episode_frame_count = 0
            self._recording_start_time = time.time()
            
            # 简化版：只发送 "start" 命令，数据集配置由 B 端管理
            self._last_recording_command = "start"
            
            print(f"\n{'='*70}")
            print(f"🔴 开始录制 Episode")
            print(f"📝 任务: {config.dataset.instruction}")
            print(f"{'='*70}\n")
    
    def _end_recording(self):
        """结束录制（进入待决定状态）"""
        if self._recording_state == "recording":
            self._recording_state = "pending"
            self._last_recording_command = "end"
            elapsed = time.time() - self._recording_start_time
            print(f"\n{'='*70}")
            print(f"⏸️  录制暂停 - 帧数: {self._episode_frame_count}, 时长: {elapsed:.1f}s")
            print("按 'Y' 保存 或 'N' 丢弃")
            print(f"{'='*70}\n")
    
    def _save_episode(self):
        """保存当前 episode"""
        if self._recording_state == "pending":
            self._last_recording_command = "save"
            print(f"\n{'='*70}")
            print(f"💾 保存 Episode - 帧数: {self._episode_frame_count}")
            print(f"{'='*70}\n")
            # 重置状态
            self._recording_state = "idle"
            self._episode_frame_count = 0
    
    def _discard_episode(self):
        """丢弃当前 episode"""
        if self._recording_state == "pending":
            self._last_recording_command = "discard"
            print(f"\n{'='*70}")
            print(f"🗑️  丢弃 Episode - 帧数: {self._episode_frame_count}")
            print(f"{'='*70}\n")
            # 重置状态
            self._recording_state = "idle"
            self._episode_frame_count = 0
    
    def _keyboard_listener_loop(self):
        """
        统一键盘监听循环（处理录制控制 + 夹爪控制）
        
        按键说明:
        - S: 开始录制
        - E: 结束录制
        - Y: 保存 Episode
        - N: 丢弃 Episode
        - 1: 夹爪张开（持续按住）
        - 2: 夹爪闭合（持续按住）
        - Q: 退出程序
        """
        try:
            import sys
            import tty
            import termios
        except ImportError:
            print("⚠️ 警告: 无法导入termios，键盘控制功能禁用")
            return
        
        print("[键盘监听] 统一键盘控制已启动")
        print("  S=开始录制  E=结束录制  Y=保存  N=丢弃")
        print("  1=夹爪张开  2=夹爪闭合  Q=退出")
        
        # 保存原始终端设置
        old_settings = termios.tcgetattr(sys.stdin)
        
        try:
            tty.setcbreak(sys.stdin.fileno())
            
            while self._running:
                # 优化：减少轮询间隔从 0.1s 到 0.01s（10ms），提升响应速度 10 倍
                if sys.stdin in select.select([sys.stdin], [], [], 0.01)[0]:
                    char = sys.stdin.read(1).lower()
                    
                    # 录制控制按键
                    if char == 's':
                        self._start_recording()
                    elif char == 'e':
                        self._end_recording()
                    elif char == 'y':
                        self._save_episode()
                    elif char == 'n':
                        self._discard_episode()
                    
                    # 夹爪控制按键 - 直接设置夹爪的当前按键状态
                    elif char in ['1', '2']:
                        if hasattr(self, 'gripper') and self.gripper:
                            with self.gripper._lock:
                                self.gripper._current_key = char
                                self.gripper._last_key_time = time.time()
                    
                    # 退出按键
                    elif char == 'q':
                        print("\n[键盘] 检测到退出键，正在停止...")
                        self._running = False
                        break
                else:
                    # 没有按键输入时，清除夹爪按键状态（实现"松开停止"）
                    if hasattr(self, 'gripper') and self.gripper:
                        with self.gripper._lock:
                            # 只在超时后清除，允许短暂的按键间隙
                            if self.gripper._current_key and \
                               (time.time() - self.gripper._last_key_time > 0.05):
                                self.gripper._current_key = None
                        
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    
    def start(self):
        """启动控制系统"""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        
        # 启动IMU读取
        self.imu.set_callback(self._on_imu_data)
        self.imu.start()
        
        # 启动夹爪控制（禁用其自带键盘监听，由统一键盘线程处理）
        self.gripper.start(enable_keyboard=False)
        
        # 启动ZMQ
        self.zmq.start()
        
        # 启动发布线程
        self._publisher_thread = threading.Thread(
            target=self._publisher_loop,
            daemon=True,
            name="Publisher"
        )
        self._publisher_thread.start()
        
        # 启动调试发布线程
        if config.network.debug_ui_enabled:
            self._debug_publisher_thread = threading.Thread(
                target=self._debug_publisher_loop,
                daemon=True,
                name="DebugPublisher"
            )
            self._debug_publisher_thread.start()
            
            # 启动 UI 命令接收线程
            self._ui_command_thread = threading.Thread(
                target=self._ui_command_loop,
                daemon=True,
                name="UICommandReceiver"
            )
            self._ui_command_thread.start()
        
        # 启动视频接收线程
        if config.network.video.enabled:
            self._video_thread = threading.Thread(
                target=self._video_receiver_loop,
                daemon=True,
                name="VideoReceiver"
            )
            self._video_thread.start()
            self.video.start()
        
        # 启动音频接收线程
        if config.network.audio.enabled:
            self._audio_thread = threading.Thread(
                target=self._audio_receiver_loop,
                daemon=True,
                name="AudioReceiver"
            )
            self._audio_thread.start()
            self.audio.start()
        
        # 启动键盘监听线程（录制控制）
        self._keyboard_thread = threading.Thread(
            target=self._keyboard_listener_loop,
            daemon=True,
            name="KeyboardListener"
        )
        self._keyboard_thread.start()
        
        # 打印启动信息（借鉴 triple 风格）
        self._print_startup_banner()


def main():
    from datetime import datetime
    
    parser = argparse.ArgumentParser(
        description='IMU机械臂控制系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    python main.py                              # 使用默认配置，repo_id为当前时间戳
    python main.py --repo-id my_dataset         # 指定数据集ID
    python main.py --repo-id exp_001 --instruction "Pick and place task"
    python main.py --config custom.yaml         # 使用自定义配置文件
    
数据集参数:
    --repo-id: 数据集名称/ID (默认: 当前时间 YYYYMMDD_HHMMSS)
    --instruction: 任务描述 (默认: 配置文件中的值)
    --fps: 视频帧率 (默认: 配置文件中的值)
    
配置文件:
    其他参数在 config/settings.yaml 中配置
        """
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=None,
        help='配置文件路径 (默认: config/settings.yaml)'
    )
    parser.add_argument(
        '--repo-id', '-r',
        type=str,
        default=None,
        help='数据集ID/名称 (默认: 当前时间戳 YYYYMMDD_HHMMSS)'
    )
    parser.add_argument(
        '--instruction', '-i',
        type=str,
        default=None,
        help='任务描述/指令'
    )
    parser.add_argument(
        '--fps',
        type=int,
        default=None,
        help='视频帧率'
    )
    
    args = parser.parse_args()
    
    # 加载自定义配置
    if args.config:
        config.load(args.config)
    
    # 判断是否使用固定的 repo_id
    use_fixed_repo_id = False
    
    # 命令行参数覆盖配置文件中的数据集设置
    if args.repo_id:
        config.dataset.repo_id = args.repo_id
        use_fixed_repo_id = True  # 命令行指定了，使用固定 ID
    
    if args.instruction:
        config.dataset.instruction = args.instruction
    
    if args.fps:
        config.dataset.fps = args.fps
    
    # 打印数据集配置
    print(f"\n📊 数据集配置:")
    if use_fixed_repo_id:
        print(f"   ID: {config.dataset.repo_id} (固定)")
    else:
        print(f"   ID: 每次录制自动生成时间戳")
    print(f"   描述: {config.dataset.instruction}")
    print(f"   FPS: {config.dataset.fps}")
    print()
    
    # 创建控制器
    controller = IMUArmController()
    controller._use_fixed_repo_id = use_fixed_repo_id  # 设置是否使用固定 ID
    
    # 信号处理
    def signal_handler(sig, frame):
        controller.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 初始化
    if not controller.setup():
        print("[Error] 初始化失败")
        sys.exit(1)
    
    # 启动
    controller.start()
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()


if __name__ == '__main__':
    main()
