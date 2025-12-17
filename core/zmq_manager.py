# -*- coding: utf-8 -*-
"""
ZeroMQ通信管理模块

负责:
- 与远程B服务器的通信 (PUSH控制数据发送)
- 本地调试UI的数据发布 (PUB)
- UI命令接收 (PULL)
- 视频流接收 (SUB)
- 音频流接收 (SUB)
- LeRobot数据发送 (PUSH)

ZMQ Socket架构 (与原始 triple_imu 文件对应):
- control_push  → PUSH, connect:5555 → B端bind接收 (pickle格式)
- debug_pub     → PUB,  bind:5560   → UI SUB接收 (pickle格式，支持视频bytes)
- ui_command    → PULL, bind:5562   → UI PUSH发送命令
- video         → SUB,  connect:5557 → B端PUB视频
- audio         → SUB,  connect:5561 → B端PUB音频
- lerobot       → PUSH, connect:5559 → LeRobot端bind接收 (pickle格式)
"""

import pickle
import socket as std_socket  # 用于端口检查

import json
import threading
import time
from typing import Optional, Dict, Any, Callable
import zmq

from config import config


def is_port_in_use(port: int) -> bool:
    """
    检查端口是否已被占用
    
    Args:
        port: 端口号
        
    Returns:
        bool: True 表示端口被占用，False 表示端口空闲
    """
    with std_socket.socket(std_socket.AF_INET, std_socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


class ZMQManager:
    """
    ZeroMQ通信管理类
    
    管理多个ZMQ连接:
    - control_push: PUSH 发送控制数据到B服务器
    - debug_pub: PUB 本地调试UI数据发布
    - ui_command: PULL 接收UI控制命令
    - video: SUB 接收视频流
    - audio: SUB 接收音频流
    - lerobot: PUSH 向LeRobot发送数据
    """
    
    def __init__(self):
        """
        初始化ZMQ管理器
        """
        # ZMQ上下文
        self.context = zmq.Context()
        
        # Socket存储
        self._sockets: Dict[str, zmq.Socket] = {}
        self._locks: Dict[str, threading.Lock] = {}
        
        # 回调函数
        self._callbacks: Dict[str, Callable] = {}
        
        # 接收线程
        self._receivers: Dict[str, threading.Thread] = {}
        self._running = False
        
        # 连接状态
        self.connection_status: Dict[str, bool] = {}
    
    def setup_control_channel(self, use_tunnel: bool = False) -> bool:
        """
        建立与B服务器的控制通道 (只发送，不接收)
        
        原始架构: PUSH → B端:5555
        
        Args:
            use_tunnel: 是否使用SSH隧道
            
        Returns:
            bool: 是否成功
        """
        try:
            # 发送socket (PUSH) - 发送传感器数据到B端
            push_socket = self.context.socket(zmq.PUSH)
            port = config.network.b_server.port
            if use_tunnel:
                address = f"tcp://127.0.0.1:{port}"
            else:
                address = f"tcp://{config.network.b_server.host}:{port}"
            push_socket.connect(address)
            self._sockets['control_push'] = push_socket
            self._locks['control_push'] = threading.Lock()
            
            self.connection_status['control'] = True
            print(f"[ZMQ] 控制通道已建立 (PUSH→B): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] 控制通道建立失败: {e}")
            self.connection_status['control'] = False
            return False
    
    def setup_debug_publisher(self) -> bool:
        """
        建立调试数据发布通道 (PUB, bind)
        
        原始架构: PUB bind *:5560
        
        Returns:
            bool: 是否成功
        """
        try:
            port = config.network.debug_ui_port
            
            # 检查端口是否被占用
            if is_port_in_use(port):
                print(f"[ZMQ] ⚠️ 端口 {port} 已被占用！可能有旧进程在运行")
                print(f"[ZMQ] 请运行以下命令杀掉旧进程:")
                print(f"      kill $(lsof -t -i:{port})")
                self.connection_status['debug'] = False
                return False
            
            socket = self.context.socket(zmq.PUB)
            address = f"tcp://*:{port}"
            socket.bind(address)
            self._sockets['debug_pub'] = socket
            self._locks['debug_pub'] = threading.Lock()
            
            self.connection_status['debug'] = True
            print(f"[ZMQ] ✓ 调试发布器已绑定 (PUB): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] 调试发布器绑定失败: {e}")
            self.connection_status['debug'] = False
            return False
    
    def setup_ui_command_receiver(self) -> bool:
        """
        建立UI命令接收通道 (PULL, bind)
        
        原始架构: PULL bind *:5562
        
        Returns:
            bool: 是否成功
        """
        try:
            port = config.network.ui_command_port
            
            # 检查端口是否被占用
            if is_port_in_use(port):
                print(f"[ZMQ] ⚠️ 端口 {port} 已被占用！可能有旧进程在运行")
                print(f"[ZMQ] 请运行以下命令杀掉旧进程:")
                print(f"      kill $(lsof -t -i:{port})")
                self.connection_status['ui_command'] = False
                return False
            
            socket = self.context.socket(zmq.PULL)
            address = f"tcp://*:{port}"
            socket.bind(address)
            socket.setsockopt(zmq.RCVTIMEO, 100)
            self._sockets['ui_command'] = socket
            self._locks['ui_command'] = threading.Lock()
            
            self.connection_status['ui_command'] = True
            print(f"[ZMQ] ✓ UI命令接收器已绑定 (PULL): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] UI命令接收器绑定失败: {e}")
            self.connection_status['ui_command'] = False
            return False
    
    def setup_video_receiver(self) -> bool:
        """
        建立视频接收通道 (SUB, connect)
        
        原始架构: SUB connect → B:5557
        
        Returns:
            bool: 是否成功
        """
        try:
            socket = self.context.socket(zmq.SUB)
            address = f"tcp://127.0.0.1:{config.network.video.port}"
            socket.connect(address)
            socket.setsockopt_string(zmq.SUBSCRIBE, "")
            socket.setsockopt(zmq.RCVHWM, 2)  # 限制缓冲
            self._sockets['video'] = socket
            self._locks['video'] = threading.Lock()
            
            self.connection_status['video'] = True
            print(f"[ZMQ] 视频接收器已连接 (SUB): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] 视频接收器连接失败: {e}")
            self.connection_status['video'] = False
            return False
    
    def setup_audio_receiver(self) -> bool:
        """
        建立音频接收通道 (SUB, connect)
        
        原始架构: SUB connect → B:5561
        
        Returns:
            bool: 是否成功
        """
        try:
            socket = self.context.socket(zmq.SUB)
            address = f"tcp://127.0.0.1:{config.network.audio.port}"
            socket.connect(address)
            socket.setsockopt_string(zmq.SUBSCRIBE, "")
            self._sockets['audio'] = socket
            self._locks['audio'] = threading.Lock()
            
            self.connection_status['audio'] = True
            print(f"[ZMQ] 音频接收器已连接 (SUB): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] 音频接收器连接失败: {e}")
            self.connection_status['audio'] = False
            return False
    
    def setup_lerobot_publisher(self) -> bool:
        """
        建立LeRobot数据发送通道 (PUSH, connect)
        
        原始架构: PUSH connect → localhost:5559
        
        Returns:
            bool: 是否成功
        """
        try:
            socket = self.context.socket(zmq.PUSH)
            address = f"tcp://{config.network.lerobot.host}:{config.network.lerobot.port}"
            socket.connect(address)
            self._sockets['lerobot'] = socket
            self._locks['lerobot'] = threading.Lock()
            
            self.connection_status['lerobot'] = True
            print(f"[ZMQ] LeRobot发送器已连接 (PUSH): {address}")
            return True
            
        except Exception as e:
            print(f"[ZMQ] LeRobot发送器连接失败: {e}")
            self.connection_status['lerobot'] = False
            return False
    
    def send_control_data(self, data: Dict[str, Any]) -> bool:
        """
        发送控制数据到B服务器 (使用pickle格式，与triple一致)
        
        Args:
            data: 控制数据字典
            
        Returns:
            bool: 是否成功
        """
        try:
            socket = self._sockets.get('control_push')
            if not socket:
                return False
            
            with self._locks['control_push']:
                # 使用pickle格式 (与triple一致)
                message = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
                socket.send(message, zmq.NOBLOCK)
            return True
            
        except zmq.Again:
            return False
        except Exception as e:
            print(f"[ZMQ] 发送控制数据失败: {e}")
            return False
    
    def publish_debug_data(self, data: Dict[str, Any]) -> bool:
        """
        发布调试数据到UI (使用pickle格式，与triple一致)
        
        支持视频帧等bytes类型数据
        
        Args:
            data: 调试数据字典
            
        Returns:
            bool: 是否成功
        """
        try:
            socket = self._sockets.get('debug_pub')
            if not socket:
                return False
            
            with self._locks['debug_pub']:
                # 使用send_pyobj (pickle格式，与triple debug_socket.send_pyobj一致)
                socket.send_pyobj(data)
            return True
            
        except Exception as e:
            print(f"[ZMQ] 发布调试数据失败: {e}")
            return False
    
    def send_to_lerobot(self, data: Dict[str, Any]) -> bool:
        """
        发送数据到LeRobot (PUSH socket)
        
        使用pickle格式 (与triple一致)
        
        Args:
            data: LeRobot数据字典
            
        Returns:
            bool: 是否成功
        """
        try:
            socket = self._sockets.get('lerobot')
            if not socket:
                return False
            
            with self._locks['lerobot']:
                # 使用pickle格式 (与triple一致)
                message = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
                socket.send(message, zmq.NOBLOCK)
            return True
            
        except Exception as e:
            print(f"[ZMQ] 发送LeRobot数据失败: {e}")
            return False
    
    # 保持向后兼容的别名
    publish_lerobot_data = send_to_lerobot
    
    def receive_video_frame(self) -> Optional[bytes]:
        """
        接收视频帧
        
        Returns:
            Optional[bytes]: JPEG编码的视频帧数据
        """
        try:
            socket = self._sockets.get('video')
            if not socket:
                return None
            
            with self._locks['video']:
                return socket.recv(zmq.NOBLOCK)
                
        except zmq.Again:
            return None
        except Exception as e:
            return None
    
    def receive_audio_data(self) -> Optional[bytes]:
        """
        接收音频数据
        
        Returns:
            Optional[bytes]: Opus编码的音频数据
        """
        try:
            socket = self._sockets.get('audio')
            if not socket:
                return None
            
            with self._locks['audio']:
                return socket.recv(zmq.NOBLOCK)
                
        except zmq.Again:
            return None
        except Exception as e:
            return None
    
    def receive_ui_command(self) -> Optional[Dict[str, Any]]:
        """
        接收UI命令
        
        Returns:
            Optional[Dict]: UI命令数据
        """
        try:
            socket = self._sockets.get('ui_command')
            if not socket:
                return None
            
            with self._locks['ui_command']:
                message = socket.recv(zmq.NOBLOCK)
                # 使用 pickle 反序列化（与 UI 发送端匹配）
                return pickle.loads(message)
                
        except zmq.Again:
            return None
        except Exception as e:
            return None
    
    def start_receiver_thread(self, channel: str, callback: Callable):
        """
        启动接收线程
        
        Args:
            channel: 通道名称 ('video', 'audio', 'ui_command')
            callback: 数据回调函数
        """
        if channel in self._receivers:
            return
        
        self._callbacks[channel] = callback
        thread = threading.Thread(
            target=self._receiver_loop,
            args=(channel,),
            daemon=True,
            name=f"ZMQ-{channel}-Receiver"
        )
        self._receivers[channel] = thread
        thread.start()
    
    def _receiver_loop(self, channel: str):
        """接收循环"""
        receive_methods = {
            'video': self.receive_video_frame,
            'audio': self.receive_audio_data,
            'ui_command': self.receive_ui_command,
        }
        
        receive_method = receive_methods.get(channel)
        callback = self._callbacks.get(channel)
        
        if not receive_method or not callback:
            return
        
        while self._running:
            try:
                data = receive_method()
                if data is not None:
                    callback(data)
                else:
                    time.sleep(0.001)
            except Exception as e:
                print(f"[ZMQ] {channel}接收循环错误: {e}")
                time.sleep(0.1)
    
    def start(self):
        """启动所有接收线程"""
        self._running = True
    
    def stop(self):
        """停止所有接收线程"""
        self._running = False
        for thread in self._receivers.values():
            thread.join(timeout=1.0)
    
    def cleanup(self):
        """清理所有资源"""
        self.stop()
        
        for socket in self._sockets.values():
            socket.close()
        self._sockets.clear()
        
        self.context.term()
        print("[ZMQ] 资源已清理")
    
    def get_status(self) -> Dict[str, bool]:
        """获取所有通道状态"""
        return self.connection_status.copy()
