#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双摄像头视频显示组件
使用QLabel显示JPEG编码的视频帧
"""

import cv2
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap


class VideoPanelWidget(QWidget):
    """双摄像头视频显示面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # === 左腕摄像头 ===
        left_group = QGroupBox("📹 Left Wrist Camera")
        left_layout = QVBoxLayout(left_group)
        
        self.left_label = QLabel()
        self.left_label.setAlignment(Qt.AlignCenter)
        self.left_label.setMinimumSize(640, 480)
        self.left_label.setScaledContents(True)
        self.left_label.setStyleSheet("background-color: #1e1e1e; border: 2px solid #3e3e3e;")
        self.left_label.setText("等待左腕摄像头数据...")
        left_layout.addWidget(self.left_label)
        
        layout.addWidget(left_group)
        
        # === 顶部摄像头 ===
        top_group = QGroupBox("📹 Top Camera")
        top_layout = QVBoxLayout(top_group)
        
        self.top_label = QLabel()
        self.top_label.setAlignment(Qt.AlignCenter)
        self.top_label.setMinimumSize(640, 480)
        self.top_label.setScaledContents(True)
        self.top_label.setStyleSheet("background-color: #1e1e1e; border: 2px solid #3e3e3e;")
        self.top_label.setText("等待顶部摄像头数据...")
        top_layout.addWidget(self.top_label)
        
        layout.addWidget(top_group)
    
    def update_frames(self, video_left, video_top):
        """
        更新视频帧
        Args:
            video_left: JPEG编码的bytes数据或None
            video_top: JPEG编码的bytes数据或None
        """
        # 更新左腕摄像头
        if video_left and isinstance(video_left, bytes):
            self.display_frame(video_left, self.left_label)
        
        # 更新顶部摄像头
        if video_top and isinstance(video_top, bytes):
            self.display_frame(video_top, self.top_label)
    
    def display_frame(self, jpeg_bytes, label):
        """
        将JPEG bytes解码并显示到QLabel
        Args:
            jpeg_bytes: JPEG编码的图像数据
            label: 目标QLabel
        """
        try:
            # 解码JPEG
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                # BGR -> RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # 转换为QImage
                h, w, ch = frame_rgb.shape
                bytes_per_line = ch * w
                q_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                # 显示到QLabel
                pixmap = QPixmap.fromImage(q_image)
                label.setPixmap(pixmap)
        
        except Exception as e:
            # 解码失败时静默处理（避免刷屏）
            pass
    
    def clear_frames(self):
        """清空视频显示"""
        self.left_label.clear()
        self.left_label.setText("无视频数据")
        self.top_label.clear()
        self.top_label.setText("无视频数据")
