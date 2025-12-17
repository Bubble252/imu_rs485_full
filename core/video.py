# -*- coding: utf-8 -*-
"""
视频接收和处理模块

负责:
- 接收JPEG编码的视频流
- 视频帧解码
- 双摄像头视频管理
- 帧率统计
"""

import threading
import time
import struct
import pickle
from typing import Optional, Callable, Dict, Tuple
from collections import deque
import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[Video] Warning: OpenCV不可用，视频功能将被禁用")

from config import config


class VideoReceiver:
    """
    视频接收和处理类
    
    功能:
    - 从ZMQ接收双摄像头JPEG编码的视频数据
    - 解码为OpenCV图像格式
    - 提供帧数据给UI显示
    
    支持两种视频数据格式:
    
    1. Pickle Dict格式 (B端发送的格式):
       pickle.dumps({
           'image.left_wrist': JPEG bytes,  # 摄像头1
           'image.top': JPEG bytes,          # 摄像头2
           'encoding': 'jpeg',
           'timestamp': float
       })
    
    2. Length-prefixed二进制格式 (旧格式):
       - 4字节: 摄像头1帧大小 (uint32 little-endian)
       - N字节: 摄像头1 JPEG数据
       - 4字节: 摄像头2帧大小 (uint32 little-endian)  
       - M字节: 摄像头2 JPEG数据
    
    Usage:
        receiver = VideoReceiver()
        receiver.start()
        
        # 获取最新帧
        frame1, frame2 = receiver.get_frames()
        
        receiver.stop()
    """
    
    def __init__(self):
        """初始化视频接收器"""
        self._running = False
        
        # 帧存储
        self._frame1: Optional[np.ndarray] = None
        self._frame2: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        
        # 帧率统计
        self._fps_window = deque(maxlen=30)  # 最近30帧的时间戳
        self._frames_received = 0
        
        # 最后接收时间
        self._last_frame_time = 0.0
        
        # 数据回调
        self._frame_callback: Optional[Callable[[np.ndarray, np.ndarray], None]] = None
    
    def process_data(self, data: bytes):
        """
        处理接收到的视频数据
        
        支持两种格式:
        1. Pickle dict格式 (来自B端): {'image.left_wrist': JPEG bytes, 'image.top': JPEG bytes, ...}
        2. Length-prefixed二进制格式 (旧格式): 4字节size + JPEG + 4字节size + JPEG
        
        Args:
            data: 包含双摄像头JPEG数据的字节流
        """
        if not CV2_AVAILABLE:
            return
        
        try:
            frame1 = None
            frame2 = None
            
            # 首先尝试pickle格式 (B端发送的格式)
            try:
                video_frame = pickle.loads(data)
                if isinstance(video_frame, dict):
                    # 从dict中提取JPEG数据
                    # B端格式: {'image.left_wrist': bytes, 'image.top': bytes, 'encoding': 'jpeg', 'timestamp': ...}
                    frame1_data = video_frame.get('image.left_wrist') or video_frame.get('frame1')
                    frame2_data = video_frame.get('image.top') or video_frame.get('frame2')
                    
                    if frame1_data:
                        frame1 = self._decode_jpeg(frame1_data)
                    if frame2_data:
                        frame2 = self._decode_jpeg(frame2_data)
                    
                    # 如果至少解码了一个帧，则认为成功
                    if frame1 is not None or frame2 is not None:
                        self._update_frames(frame1, frame2)
                        return
            except (pickle.UnpicklingError, TypeError, KeyError):
                # 不是pickle格式，尝试下一种格式
                pass
            
            # 回退到length-prefixed二进制格式 (旧格式)
            if len(data) < 8:
                return
            
            # 读取摄像头1帧大小
            frame1_size = struct.unpack('<I', data[0:4])[0]
            
            if len(data) < 8 + frame1_size:
                return
            
            # 读取摄像头1数据
            frame1_data = data[4:4 + frame1_size]
            
            # 读取摄像头2帧大小
            frame2_offset = 4 + frame1_size
            frame2_size = struct.unpack('<I', data[frame2_offset:frame2_offset + 4])[0]
            
            if len(data) < frame2_offset + 4 + frame2_size:
                return
            
            # 读取摄像头2数据
            frame2_data = data[frame2_offset + 4:frame2_offset + 4 + frame2_size]
            
            # 解码JPEG
            frame1 = self._decode_jpeg(frame1_data)
            frame2 = self._decode_jpeg(frame2_data)
            
            self._update_frames(frame1, frame2)
                    
        except Exception as e:
            print(f"[Video] 处理视频数据失败: {e}")
    
    def _update_frames(self, frame1: Optional[np.ndarray], frame2: Optional[np.ndarray]):
        """
        更新帧数据并触发回调
        
        Args:
            frame1: 摄像头1帧
            frame2: 摄像头2帧
        """
        if frame1 is not None or frame2 is not None:
            with self._frame_lock:
                if frame1 is not None:
                    self._frame1 = frame1
                if frame2 is not None:
                    self._frame2 = frame2
            
            # 更新统计
            current_time = time.time()
            self._fps_window.append(current_time)
            self._frames_received += 1
            self._last_frame_time = current_time
            
            # 触发回调
            if self._frame_callback and self._frame1 is not None and self._frame2 is not None:
                self._frame_callback(self._frame1, self._frame2)
    
    def _decode_jpeg(self, data: bytes) -> Optional[np.ndarray]:
        """
        解码JPEG数据
        
        Args:
            data: JPEG编码的字节数据
            
        Returns:
            Optional[np.ndarray]: 解码后的图像，失败返回None
        """
        try:
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            print(f"[Video] JPEG解码失败: {e}")
            return None
    
    def set_frame_callback(self, callback: Callable[[np.ndarray, np.ndarray], None]):
        """
        设置帧回调函数
        
        Args:
            callback: 当有新帧时的回调函数，参数为(frame1, frame2)
        """
        self._frame_callback = callback
    
    def get_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        获取最新帧
        
        Returns:
            Tuple[frame1, frame2]: 两个摄像头的最新帧
        """
        with self._frame_lock:
            return (
                self._frame1.copy() if self._frame1 is not None else None,
                self._frame2.copy() if self._frame2 is not None else None
            )
    
    def get_frame1(self) -> Optional[np.ndarray]:
        """获取摄像头1最新帧"""
        with self._frame_lock:
            return self._frame1.copy() if self._frame1 is not None else None
    
    def get_frame2(self) -> Optional[np.ndarray]:
        """获取摄像头2最新帧"""
        with self._frame_lock:
            return self._frame2.copy() if self._frame2 is not None else None
    
    def get_fps(self) -> float:
        """
        获取当前帧率
        
        Returns:
            float: 每秒帧数
        """
        if len(self._fps_window) < 2:
            return 0.0
        
        time_span = self._fps_window[-1] - self._fps_window[0]
        if time_span <= 0:
            return 0.0
        
        return len(self._fps_window) / time_span
    
    def is_receiving(self) -> bool:
        """
        检查是否正在接收视频
        
        Returns:
            bool: 最近1秒内是否收到帧
        """
        return (time.time() - self._last_frame_time) < 1.0
    
    def start(self):
        """启动视频接收器"""
        if self._running:
            return
        
        self._running = True
        print("[Video] 视频接收器已启动")
    
    def stop(self):
        """停止视频接收器"""
        self._running = False
        print(f"[Video] 已停止，共接收 {self._frames_received} 帧")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'frames_received': self._frames_received,
            'fps': self.get_fps(),
            'is_receiving': self.is_receiving(),
            'has_frame1': self._frame1 is not None,
            'has_frame2': self._frame2 is not None,
        }
