#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制面板组件
提供按钮和状态显示
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class ControlPanelWidget(QWidget):
    """控制面板"""
    
    # 信号
    reset_clicked = pyqtSignal()
    export_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # === 标题 ===
        title = QLabel("🎮 控制面板")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # === 按钮组 ===
        btn_group = QGroupBox("操作")
        btn_layout = QVBoxLayout(btn_group)
        
        self.reset_btn = QPushButton("🔄 重置轨迹")
        self.reset_btn.setMinimumHeight(35)
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        
        self.export_btn = QPushButton("💾 导出数据")
        self.export_btn.setMinimumHeight(35)
        self.export_btn.clicked.connect(self.export_clicked.emit)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
            QPushButton:pressed {
                background-color: #0960a0;
            }
        """)
        
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.export_btn)
        layout.addWidget(btn_group)
        
        # === 状态信息 ===
        status_group = QGroupBox("📈 运行状态")
        status_layout = QVBoxLayout(status_group)
        
        self.conn_label = QLabel("连接: ⚪ 未连接")
        self.rate_label = QLabel("发布率: -- Hz")
        self.count_label = QLabel("消息数: 0")
        self.video_label = QLabel("视频帧: 0")
        self.imu_label = QLabel("IMU在线: 0/3")
        
        for label in [self.conn_label, self.rate_label, self.count_label, 
                      self.video_label, self.imu_label]:
            label.setStyleSheet("padding: 3px;")
            status_layout.addWidget(label)
        
        layout.addWidget(status_group)
    
    def update_status(self, connected=False, publish_rate=0, message_count=0,
                     video_fps=0, imu_online="0/3"):
        """更新状态显示"""
        self.conn_label.setText(f"连接: {'🟢 已连接' if connected else '⚪ 未连接'}")
        self.rate_label.setText(f"发布率: {publish_rate:.1f} Hz")
        self.count_label.setText(f"消息数: {message_count}")
        self.video_label.setText(f"视频帧: {video_fps}")
        self.imu_label.setText(f"IMU在线: {imu_online}")
