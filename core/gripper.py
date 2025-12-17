#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夹爪控制模块

处理键盘输入和UI命令，控制夹爪开合
"""

import time
import threading
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_config


class GripperController:
    """
    夹爪控制器
    
    支持两种控制方式：
    1. 键盘控制：按住'1'打开，按住'2'闭合
    2. UI命令：接收ZMQ命令
    
    Usage:
        gripper = GripperController()
        gripper.start()
        
        # 获取当前值
        value = gripper.value
        
        # 设置值
        gripper.set_value(0.5)
        
        gripper.stop()
    """
    
    def __init__(self,
                 initial_value: float = None,
                 step: float = None,
                 update_rate: float = None,
                 config = None):
        """
        初始化夹爪控制器
        
        Args:
            initial_value: 初始值（0.0-1.0），None则从配置读取
            step: 调整步长，None则从配置读取
            update_rate: 更新频率（Hz），None则从配置读取
            config: 配置对象，None则使用默认配置
        """
        cfg = config or get_config()
        gripper_cfg = cfg.gripper
        
        self._value = initial_value if initial_value is not None else gripper_cfg.initial_value
        self._step = step or gripper_cfg.step
        # 将Hz转换为秒间隔
        update_hz = update_rate or gripper_cfg.update_rate
        self._update_interval = 1.0 / update_hz
        self._key_timeout = gripper_cfg.key_timeout
        
        self._lock = threading.Lock()
        self._running = False
        
        # 当前按键状态
        self._current_key = None
        self._last_key_time = 0.0
        
        # 线程
        self._keyboard_thread = None
        self._update_thread = None
        
        # 原始终端设置（用于恢复）
        self._original_settings = None
    
    @property
    def value(self) -> float:
        """获取当前夹爪值（线程安全）"""
        with self._lock:
            return self._value
    
    def set_value(self, value: float):
        """
        设置夹爪值
        
        Args:
            value: 目标值（0.0-1.0）
        """
        with self._lock:
            self._value = max(0.0, min(1.0, value))
    
    def open(self):
        """打开夹爪一步"""
        with self._lock:
            self._value = min(1.0, self._value + self._step)
    
    def close(self):
        """闭合夹爪一步"""
        with self._lock:
            self._value = max(0.0, self._value - self._step)
    
    def start(self, enable_keyboard: bool = True):
        """
        启动夹爪控制
        
        Args:
            enable_keyboard: 是否启用键盘控制
        """
        self._running = True
        
        if enable_keyboard:
            self._start_keyboard_control()
        
        # 启动更新线程
        self._update_thread = threading.Thread(
            target=self._update_loop,
            daemon=True,
            name="GripperUpdate"
        )
        self._update_thread.start()
        
        print("✓ 夹爪控制已启动")
    
    def stop(self):
        """停止夹爪控制"""
        self._running = False
        
        # 恢复终端设置
        self._restore_terminal()
        
        print("✓ 夹爪控制已停止")
    
    def handle_command(self, command: dict):
        """
        处理UI命令
        
        Args:
            command: 命令字典
                {'type': 'gripper_command', 'action': 'open'/'close'/'stop'}
                {'type': 'gripper_value', 'value': 0.0-1.0}
        """
        cmd_type = command.get('type', '')
        
        if cmd_type == 'gripper_command':
            action = command.get('action', '')
            if action == 'open':
                with self._lock:
                    self._current_key = '1'
                    self._last_key_time = time.time()
            elif action == 'close':
                with self._lock:
                    self._current_key = '2'
                    self._last_key_time = time.time()
            elif action == 'stop':
                with self._lock:
                    self._current_key = None
        
        elif cmd_type == 'gripper_value':
            value = command.get('value', 0.0)
            self.set_value(value)
    
    def _start_keyboard_control(self):
        """启动键盘控制"""
        try:
            import termios
            import tty
            
            # 保存原始终端设置
            self._original_settings = termios.tcgetattr(sys.stdin)
            
            # 设置终端为非阻塞模式
            tty.setcbreak(sys.stdin.fileno())
            
            # 启动键盘监听线程
            self._keyboard_thread = threading.Thread(
                target=self._keyboard_loop,
                daemon=True,
                name="KeyboardListener"
            )
            self._keyboard_thread.start()
            
            print("\n" + "="*60)
            print("键盘控制已启用:")
            print("  按住 '1' - 夹爪打开")
            print("  按住 '2' - 夹爪闭合")
            print("  按 'q' - 退出程序")
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"⚠️  键盘控制初始化失败: {e}")
    
    def _keyboard_loop(self):
        """键盘监听循环"""
        import select
        
        while self._running:
            try:
                # 非阻塞检查输入
                if select.select([sys.stdin], [], [], 0.01)[0]:
                    key = sys.stdin.read(1)
                    
                    if key == 'q':
                        print("\n检测到退出键...")
                        self._running = False
                        # 发送退出信号
                        os._exit(0)
                    
                    elif key in ['1', '2']:
                        with self._lock:
                            self._current_key = key
                            self._last_key_time = time.time()
                
            except Exception as e:
                break
            
            time.sleep(0.001)
    
    def _update_loop(self):
        """夹爪值更新循环"""
        last_print_value = self._value
        
        while self._running:
            current_time = time.time()
            
            with self._lock:
                # 检查按键超时
                if self._current_key and (current_time - self._last_key_time > self._key_timeout):
                    self._current_key = None
                
                # 根据按键状态更新夹爪值
                if self._current_key == '1':
                    self._value = min(1.0, self._value + self._step)
                elif self._current_key == '2':
                    self._value = max(0.0, self._value - self._step)
                
                current_value = self._value
            
            # 值变化时打印（静默，避免干扰主输出）
            # if abs(current_value - last_print_value) > 0.05:
            #     print(f"\r夹爪: {current_value:.2f} ({current_value*100:.0f}%)  ", end="", flush=True)
            #     last_print_value = current_value
            
            time.sleep(self._update_interval)
    
    def _restore_terminal(self):
        """恢复终端设置"""
        if self._original_settings:
            try:
                import termios
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._original_settings)
            except:
                pass


if __name__ == "__main__":
    # 测试夹爪控制
    print("=== 夹爪控制测试 ===\n")
    
    gripper = GripperController()
    gripper.start(enable_keyboard=True)
    
    try:
        while True:
            print(f"\r夹爪值: {gripper.value:.2f} ({gripper.value*100:.0f}%)  ", end="", flush=True)
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\n中断")
    
    finally:
        gripper.stop()
    
    print("\n测试完成")
