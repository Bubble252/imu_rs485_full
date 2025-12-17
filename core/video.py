# -*- coding: utf-8 -*-
"""
视频接收和处理模块

负责:
- 接收JPEG编码的视频流
- 视频帧解码
- 多摄像头视频管理（支持动态数量）
- 帧率统计
"""

import threading
import time
import struct
import pickle
from typing import Optional, Callable, Dict, Tuple, List
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
    视频接收和处理类（多摄像头版本）
    
    功能:
    - 从ZMQ接收多摄像头JPEG编码的视频数据
    - 解码为OpenCV图像格式
    - 动态支持任意数量摄像头
    - 提供帧数据给UI显示
    
    支持的视频数据格式:
    
    Pickle Dict格式 (B端发送的格式):
       pickle.dumps({
           'image.left_wrist': JPEG bytes,  # 摄像头1 - 手腕
           'image.left': JPEG bytes,         # 摄像头2 - 左侧
           'image.right': JPEG bytes,        # 摄像头3 - 右侧
           'encoding': 'jpeg',
           'timestamp': float
       })
    
    Usage:
        receiver = VideoReceiver()
        receiver.start()
        
        # 获取所有帧
        frames = receiver.get_all_frames()
        # 返回: {'left_wrist': np.ndarray, 'left': np.ndarray, 'right': np.ndarray}
        
        # 获取特定相机帧
        frame = receiver.get_frame('left_wrist')
        
        # 获取相机列表
        cameras = receiver.get_camera_names()
        # 返回: ['left_wrist', 'left', 'right']
        
        receiver.stop()
    """
    
    def __init__(self):
        """初始化视频接收器"""
        self._running = False
        
        # 多相机帧存储 (camera_name -> frame)
        self._frames: Dict[str, np.ndarray] = {}
        self._frame_lock = threading.Lock()
        
        # 已知的相机名称列表（按接收顺序）
        self._camera_names: List[str] = []
        
        # 帧率统计
        self._fps_window = deque(maxlen=30)  # 最近30帧的时间戳
        self._frames_received = 0
        
        # 最后接收时间
        self._last_frame_time = 0.0
        
        # 数据回调 (参数为 Dict[str, np.ndarray])
        self._frame_callback: Optional[Callable[[Dict[str, np.ndarray]], None]] = None
    
    def process_data(self, data: bytes):
        """
        处理接收到的视频数据（支持多摄像头）
        
        自动检测所有 'image.*' 格式的相机数据并解码
        
        Args:
            data: pickle序列化的字典，包含多个相机的JPEG数据
                  格式: {'image.left_wrist': bytes, 'image.left': bytes, 'image.right': bytes, ...}
        """
        if not CV2_AVAILABLE:
            return
        
        try:
            # 解析pickle数据
            try:
                video_frame = pickle.loads(data)
                if not isinstance(video_frame, dict):
                    return
            except (pickle.UnpicklingError, TypeError):
                return
            
            # 动态检测所有相机 (image.* 格式)
            decoded_frames: Dict[str, np.ndarray] = {}
            
            for key, value in video_frame.items():
                if key.startswith('image.') and isinstance(value, bytes):
                    camera_name = key.replace('image.', '')
                    frame = self._decode_jpeg(value)
                    if frame is not None:
                        decoded_frames[camera_name] = frame
                        
                        # 记录新发现的相机
                        if camera_name not in self._camera_names:
                            self._camera_names.append(camera_name)
                            print(f"[Video] 🎥 发现新相机: {camera_name}")
            
            # 更新帧
            if decoded_frames:
                self._update_frames(decoded_frames)
                    
        except Exception as e:
            print(f"[Video] 处理视频数据失败: {e}")
    
    def _update_frames(self, frames: Dict[str, np.ndarray]):
        """
        更新帧数据并触发回调
        
        Args:
            frames: 相机名称到帧的映射
        """
        with self._frame_lock:
            for camera_name, frame in frames.items():
                self._frames[camera_name] = frame
        
        # 更新统计
        current_time = time.time()
        self._fps_window.append(current_time)
        self._frames_received += 1
        self._last_frame_time = current_time
        
        # 触发回调
        if self._frame_callback:
            self._frame_callback(self._frames.copy())
    
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
    
    def set_frame_callback(self, callback: Callable[[Dict[str, np.ndarray]], None]):
        """
        设置帧回调函数
        
        Args:
            callback: 当有新帧时的回调函数，参数为 Dict[camera_name, frame]
        """
        self._frame_callback = callback
    
    def get_all_frames(self) -> Dict[str, np.ndarray]:
        """
        获取所有相机的最新帧
        
        Returns:
            Dict[str, np.ndarray]: 相机名称到帧的映射
        """
        with self._frame_lock:
            return {name: frame.copy() for name, frame in self._frames.items()}
    
    def get_frame(self, camera_name: str) -> Optional[np.ndarray]:
        """
        获取指定相机的最新帧
        
        Args:
            camera_name: 相机名称（如 'left_wrist', 'left', 'right'）
            
        Returns:
            Optional[np.ndarray]: 帧数据，不存在返回None
        """
        with self._frame_lock:
            frame = self._frames.get(camera_name)
            return frame.copy() if frame is not None else None
    
    def get_camera_names(self) -> List[str]:
        """
        获取所有已发现的相机名称列表
        
        Returns:
            List[str]: 相机名称列表（按发现顺序）
        """
        return self._camera_names.copy()
    
    def get_camera_count(self) -> int:
        """获取相机数量"""
        return len(self._camera_names)
    
    # === 兼容旧API（保留以防UI依赖） ===
    def get_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        获取前两个相机的帧（兼容旧API）
        
        Returns:
            Tuple[frame1, frame2]: 前两个摄像头的最新帧
        """
        with self._frame_lock:
            frame1 = None
            frame2 = None
            if len(self._camera_names) > 0:
                frame1 = self._frames.get(self._camera_names[0])
            if len(self._camera_names) > 1:
                frame2 = self._frames.get(self._camera_names[1])
            return (
                frame1.copy() if frame1 is not None else None,
                frame2.copy() if frame2 is not None else None
            )
    
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
        print(f"[Video] 已停止，共接收 {self._frames_received} 帧，相机: {self._camera_names}")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'frames_received': self._frames_received,
            'fps': self.get_fps(),
            'is_receiving': self.is_receiving(),
            'camera_count': len(self._camera_names),
            'camera_names': self._camera_names.copy(),
            'has_frames': {name: True for name in self._frames.keys()},
        }
