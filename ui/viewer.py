#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMU可视化主界面

整合各Widget组件，显示:
- 双摄像头视频流
- IMU传感器数据和在线状态
- 3D轨迹可视化
- 夹爪控制
- 音频波形
"""

import sys
import os
import pickle
import time
import threading
from typing import Optional, Dict, Any

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGroupBox, QLabel, QSplitter, QStatusBar, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QKeyEvent
import zmq

# 导入widgets (使用绝对导入)
from ui.widgets.video_panel import VideoPanelWidget as VideoPanel
from ui.widgets.imu_panel import IMUPanelWidget as IMUPanel
from ui.widgets.trajectory_3d import Trajectory3DWidget
from ui.widgets.control_panel import ControlPanelWidget as ControlPanel
from ui.widgets.gripper_control import GripperControlWidget as GripperControl
from ui.widgets.audio_waveform import AudioWaveformWidget as AudioWaveform

from config import config


class CommandSender:
    """命令发送器（发送到主程序）"""
    
    def __init__(self):
        self.context = zmq.Context()
        self.socket: Optional[zmq.Socket] = None
        self._connected = False
    
    def connect(self, port: int) -> bool:
        """连接到主程序命令端口"""
        try:
            self.socket = self.context.socket(zmq.PUSH)
            self.socket.connect(f"tcp://127.0.0.1:{port}")
            self._connected = True
            print(f"[CommandSender] ✓ 已连接到命令端口: {port}")
            return True
        except Exception as e:
            print(f"[CommandSender] 连接失败: {e}")
            self._connected = False
            return False
    
    def send_command(self, command: Dict[str, Any]) -> bool:
        """发送命令到主程序"""
        if not self._connected or not self.socket:
            print("[CommandSender] 未连接，无法发送命令")
            return False
        try:
            self.socket.send(pickle.dumps(command))
            return True
        except Exception as e:
            print(f"[CommandSender] 发送失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.socket:
            self.socket.close()


class DataReceiver(QObject):
    """ZMQ数据接收器（Qt线程安全）"""
    
    # Qt信号
    data_received = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)
    
    def __init__(self):
        super().__init__()
        self.context = zmq.Context()
        self.socket: Optional[zmq.Socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
    def connect(self, port: int):
        """连接到数据源"""
        try:
            self.socket = self.context.socket(zmq.SUB)
            self.socket.connect(f"tcp://127.0.0.1:{port}")
            self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
            self.socket.setsockopt(zmq.RCVTIMEO, 100)
            self.connection_changed.emit(True)
            return True
        except Exception as e:
            print(f"[DataReceiver] 连接失败: {e}")
            self.connection_changed.emit(False)
            return False
    
    def start(self):
        """启动接收线程"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止接收"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.socket:
            self.socket.close()
    
    def _receive_loop(self):
        """接收循环"""
        while self._running:
            try:
                if self.socket:
                    message = self.socket.recv()
                    # 使用pickle反序列化（与主程序send_pyobj匹配）
                    data = pickle.loads(message)
                    self.data_received.emit(data)
            except zmq.Again:
                pass
            except Exception as e:
                print(f"[DataReceiver] 接收错误: {e}")
                time.sleep(0.1)


class IMUViewer(QMainWindow):
    """
    IMU可视化主窗口
    
    布局:
    ┌───────────────────────────────────────────────────┐
    │                    工具栏                          │
    ├─────────────────┬─────────────────────────────────┤
    │                 │                                 │
    │   摄像头1        │           3D轨迹               │
    │                 │                                 │
    ├─────────────────┤                                 │
    │                 ├─────────────────────────────────┤
    │   摄像头2        │   IMU数据    │    控制面板     │
    │                 │             │                  │
    ├─────────────────┴─────────────┴──────────────────┤
    │                   音频波形                        │
    ├─────────────────────────────────────────────────┤
    │                   状态栏                         │
    └─────────────────────────────────────────────────┘
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("IMU机械臂控制系统 - 可视化界面")
        self.setMinimumSize(1280, 800)
        
        # 数据接收器
        self.receiver = DataReceiver()
        self.receiver.data_received.connect(self._on_data_received)
        self.receiver.connection_changed.connect(self._on_connection_changed)
        
        # 命令发送器
        self.command_sender = CommandSender()
        
        # 轨迹缓冲区
        self._trajectory_buffer = []
        self._max_trajectory_points = 500
        
        # 创建UI
        self._setup_ui()
        
        # 状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("未连接")
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_ui)
        self.update_timer.start(50)  # 20 Hz UI刷新
        
        # 调试打印定时器 (每2秒打印一次接收的数据摘要)
        self.debug_timer = QTimer()
        self.debug_timer.timeout.connect(self._print_debug_info)
        self.debug_timer.start(2000)  # 每2秒打印
        
        # 统计
        self._last_data_time = 0.0
        self._data_count = 0
        self._last_received_data = None  # 保存最后接收的数据
    
    def _setup_ui(self):
        """设置UI布局"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧: 视频面板 (复用现有的双摄像头面板)
        left_panel = QVBoxLayout()
        
        # 双摄像头面板
        self.video_panel = VideoPanel()
        left_panel.addWidget(self.video_panel)
        
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setMaximumWidth(700)
        
        # 中间: 3D轨迹和IMU数据
        center_panel = QVBoxLayout()
        
        # 3D轨迹
        self.trajectory_widget = Trajectory3DWidget()
        center_panel.addWidget(self.trajectory_widget, stretch=2)
        
        # IMU数据面板 (复用现有的单个面板，显示所有3个IMU)
        self.imu_panel = IMUPanel()
        center_panel.addWidget(self.imu_panel, stretch=1)
        
        center_widget = QWidget()
        center_widget.setLayout(center_panel)
        
        # 右侧: 控制面板
        right_panel = QVBoxLayout()
        
        # 控制面板
        self.control_panel = ControlPanel()
        right_panel.addWidget(self.control_panel)
        
        # 夹爪控制
        self.gripper_control = GripperControl()
        right_panel.addWidget(self.gripper_control)
        
        # 连接夹爪控制信号到命令发送
        self.gripper_control.gripper_command.connect(self._on_gripper_command)
        self.gripper_control.gripper_value_changed.connect(self._on_gripper_value_changed)
        
        # 音频波形
        self.audio_waveform = AudioWaveform()
        right_panel.addWidget(self.audio_waveform)
        
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        right_widget.setMaximumWidth(350)
        
        # 添加到主布局
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([350, 580, 350])
        
        main_layout.addWidget(splitter)
    
    def connect_to_main(self):
        """连接到主程序"""
        # 连接数据接收
        port = config.network.debug_ui_port
        if self.receiver.connect(port):
            self.receiver.start()
            self.statusBar.showMessage(f"已连接到 localhost:{port}")
        
        # 连接命令发送
        cmd_port = config.network.ui_command_port
        self.command_sender.connect(cmd_port)
    
    def _on_gripper_command(self, command: str):
        """处理夹爪控制命令（open/close/stop）"""
        cmd = {
            "type": "gripper",
            "action": command,  # "open", "close", "stop"
            "timestamp": time.time()
        }
        if self.command_sender.send_command(cmd):
            print(f"[UI] 发送夹爪命令: {command}")
    
    def _on_gripper_value_changed(self, value: float):
        """处理夹爪值直接设置"""
        cmd = {
            "type": "gripper",
            "action": "set",
            "value": value,
            "timestamp": time.time()
        }
        if self.command_sender.send_command(cmd):
            print(f"[UI] 发送夹爪设置: {value:.2f}")
    
    def _on_data_received(self, data: Dict[str, Any]):
        """处理接收到的数据
        
        主程序发送的数据格式 (来自 main.py _debug_publisher_loop):
        {
            "timestamp": float,
            "imu1": {"roll": float, "pitch": float, "yaw": float},
            "imu2": {"roll": float, "pitch": float, "yaw": float},
            "imu3": {"roll": float, "pitch": float, "yaw": float},
            "position": {"raw": [x,y,z], "mapped": [x,y,z]},
            "gripper": float,
            "online_status": {"imu1": bool, "imu2": bool, "imu3": bool},
            "stats": {"publish_count": int, "publish_rate": float, ...},
            "config": {"L1": float, "L2": float, "yaw_mode": str},
            "video_left": bytes or None,
            "video_top": bytes or None,
            "audio": {"waveform": list, "rms": float, ...}
        }
        """
        self._last_data_time = time.time()
        self._data_count += 1
        self._last_received_data = data  # 保存用于调试打印
        
        # 直接读取IMU数据（主程序格式）
        imu1 = data.get("imu1", {})
        imu2 = data.get("imu2", {})
        imu3 = data.get("imu3", {})
        online_status = data.get("online_status", {})
        gripper = data.get("gripper", 0.5)
        
        # 更新IMU面板
        imu_data = {
            "imu1": imu1,
            "imu2": imu2,
            "imu3": imu3,
            "online_status": {
                "imu1": online_status.get("imu1", False),
                "imu2": online_status.get("imu2", False),
                "imu3": online_status.get("imu3", False),
            },
            "gripper": gripper
        }
        self.imu_panel.update_data(imu_data)
        
        # 计算IMU在线数量
        imu_online_count = sum([
            online_status.get("imu1", False),
            online_status.get("imu2", False),
            online_status.get("imu3", False)
        ])
        
        # 更新控制面板状态
        stats = data.get("stats", {})
        self.control_panel.update_status(
            connected=True,
            publish_rate=stats.get("publish_rate", 0),
            message_count=self._data_count,
            video_fps=0,
            imu_online=f"{imu_online_count}/3"
        )
        
        # 更新夹爪
        self.gripper_control.update_from_robot(gripper)
        
        # 更新3D轨迹 (使用 position 数据)
        position = data.get("position", {})
        mapped_pos = position.get("mapped", None)
        if mapped_pos and len(mapped_pos) >= 3:
            # 添加到轨迹缓冲区
            self._trajectory_buffer.append({
                "pos": [mapped_pos[0], mapped_pos[1], mapped_pos[2]],
                "timestamp": self._last_data_time
            })
            # 限制缓冲区大小
            if len(self._trajectory_buffer) > self._max_trajectory_points:
                self._trajectory_buffer = self._trajectory_buffer[-self._max_trajectory_points:]
            # 更新3D显示
            self.trajectory_widget.update_trajectory(self._trajectory_buffer)
        
        # 更新视频面板 (如果有视频数据)
        video_left = data.get("video_left")
        video_top = data.get("video_top")
        if video_left or video_top:
            self.video_panel.update_frames(video_left, video_top)
        
        # 更新音频波形 (如果有音频数据)
        audio = data.get("audio", {})
        if audio:
            self.audio_waveform.update_audio_data(audio)
    
    def _on_connection_changed(self, connected: bool):
        """连接状态变化"""
        if connected:
            self.statusBar.showMessage("已连接")
        else:
            self.statusBar.showMessage("连接断开")
    
    def _update_ui(self):
        """定期UI更新"""
        # 检查连接状态
        if time.time() - self._last_data_time > 2.0:
            self.statusBar.showMessage("等待数据...")
    
    def _print_debug_info(self):
        """定时打印接收的数据摘要"""
        if self._last_received_data is None:
            print(f"[UI Debug] 尚未收到任何数据 (count={self._data_count})")
            return
        
        data = self._last_received_data
        
        # 打印数据摘要
        print(f"\n{'='*60}")
        print(f"[UI Debug] ZMQ 接收数据摘要 (总计: {self._data_count} 条)")
        print(f"{'='*60}")
        
        # 打印时间戳（检查是否在变化）
        timestamp = data.get("timestamp", 0)
        print(f"数据时间戳: {timestamp:.3f} (距现在: {time.time() - timestamp:.3f}秒)")
        
        # 打印数据的键
        print(f"数据键: {list(data.keys())}")
        
        # IMU数据
        for imu_key in ["imu1", "imu2", "imu3"]:
            imu = data.get(imu_key, {})
            if imu:
                print(f"  {imu_key}: roll={imu.get('roll', 0):.1f}°, pitch={imu.get('pitch', 0):.1f}°, yaw={imu.get('yaw', 0):.1f}°")
        
        # 在线状态
        online = data.get("online_status", {})
        print(f"  在线状态: IMU1={online.get('imu1', False)}, IMU2={online.get('imu2', False)}, IMU3={online.get('imu3', False)}")
        
        # 位置
        pos = data.get("position", {})
        if pos:
            raw = pos.get("raw", [0, 0, 0])
            mapped = pos.get("mapped", [0, 0, 0])
            print(f"  位置 raw: [{raw[0]:.3f}, {raw[1]:.3f}, {raw[2]:.3f}]")
            print(f"  位置 mapped: [{mapped[0]:.3f}, {mapped[1]:.3f}, {mapped[2]:.3f}]")
        
        # 夹爪
        print(f"  夹爪: {data.get('gripper', 0):.2f}")
        
        # 视频
        video_left = data.get("video_left")
        video_top = data.get("video_top")
        print(f"  视频: left={len(video_left) if video_left else 0} bytes, top={len(video_top) if video_top else 0} bytes")
        
        # 音频
        audio = data.get("audio", {})
        if audio:
            print(f"  音频: rms={audio.get('rms', 0):.3f}, waveform_len={len(audio.get('waveform', []))}")
        
        # 统计信息
        stats = data.get("stats", {})
        if stats:
            print(f"  统计: publish_count={stats.get('publish_count', 0)}, publish_rate={stats.get('publish_rate', 0):.1f} Hz")
        
        print(f"{'='*60}\n")
    
    def keyPressEvent(self, event: QKeyEvent):
        """全局键盘按下事件 - 支持在任何地方按 1/2 控制夹爪"""
        key = event.key()
        
        if key == Qt.Key_1 and not event.isAutoRepeat():
            # 按下 '1' 键 - 打开夹爪
            self.gripper_control.on_open_pressed()
        elif key == Qt.Key_2 and not event.isAutoRepeat():
            # 按下 '2' 键 - 关闭夹爪
            self.gripper_control.on_close_pressed()
        else:
            super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event: QKeyEvent):
        """全局键盘松开事件"""
        key = event.key()
        
        if key == Qt.Key_1 and not event.isAutoRepeat():
            # 松开 '1' 键
            self.gripper_control.on_open_released()
        elif key == Qt.Key_2 and not event.isAutoRepeat():
            # 松开 '2' 键
            self.gripper_control.on_close_released()
        else:
            super().keyReleaseEvent(event)
    
    def closeEvent(self, event):
        """窗口关闭"""
        self.receiver.stop()
        self.command_sender.close()
        self.update_timer.stop()
        self.debug_timer.stop()
        event.accept()


def main():
    """主入口"""
    app = QApplication(sys.argv)
    
    # 设置样式
    app.setStyle('Fusion')
    
    # 创建窗口
    viewer = IMUViewer()
    viewer.show()
    
    # 自动连接
    viewer.connect_to_main()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
