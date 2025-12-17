#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMU数据显示面板
显示3个IMU的姿态角和夹爪状态
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox,
    QTableWidget, QTableWidgetItem, QProgressBar, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor


class IMUPanelWidget(QWidget):
    """IMU数据显示面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # === IMU数据表格 ===
        imu_group = QGroupBox("📊 IMU姿态数据")
        imu_layout = QVBoxLayout(imu_group)
        
        self.imu_table = QTableWidget(3, 4)  # 3行（IMU1-3）x 4列（名称+Roll+Pitch+Yaw）
        self.imu_table.setHorizontalHeaderLabels(["IMU", "Roll (°)", "Pitch (°)", "Yaw (°)"])
        self.imu_table.setVerticalHeaderLabels(["0x50", "0x51", "0x52"])
        self.imu_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.imu_table.setEditTriggers(QTableWidget.NoEditTriggers)  # 只读
        
        # 设置初始值
        for row in range(3):
            for col in range(4):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignCenter)
                self.imu_table.setItem(row, col, item)
            
            # 第一列显示IMU名称
            self.imu_table.setItem(row, 0, QTableWidgetItem(f"IMU{row+1}"))
        
        imu_layout.addWidget(self.imu_table)
        layout.addWidget(imu_group)
        
        # === 夹爪状态 ===
        gripper_group = QGroupBox("🤏 夹爪状态")
        gripper_layout = QVBoxLayout(gripper_group)
        
        self.gripper_label = QLabel("位置: 0%")
        self.gripper_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.gripper_label.setFont(font)
        
        self.gripper_bar = QProgressBar()
        self.gripper_bar.setRange(0, 100)
        self.gripper_bar.setValue(0)
        self.gripper_bar.setTextVisible(True)
        self.gripper_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
                text-align: center;
                background-color: #2e2e2e;
            }
            QProgressBar::chunk {
                background-color: #05B8CC;
                width: 10px;
            }
        """)
        
        gripper_layout.addWidget(self.gripper_label)
        gripper_layout.addWidget(self.gripper_bar)
        layout.addWidget(gripper_group)
        
        # === 在线状态指示器 ===
        status_group = QGroupBox("🔌 连接状态")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label1 = QLabel("IMU1: ⚪ 离线")
        self.status_label2 = QLabel("IMU2: ⚪ 离线")
        self.status_label3 = QLabel("IMU3: ⚪ 离线")
        
        status_layout.addWidget(self.status_label1)
        status_layout.addWidget(self.status_label2)
        status_layout.addWidget(self.status_label3)
        layout.addWidget(status_group)
    
    def update_data(self, imu_data):
        """
        更新IMU数据
        Args:
            imu_data: {
                "imu1": {"roll": ..., "pitch": ..., "yaw": ...},
                "imu2": {...},
                "imu3": {...},
                "online_status": {"imu1": True, ...},
                "gripper": 0.0-1.0
            }
        """
        try:
            # 更新IMU姿态角
            for i, imu_key in enumerate(["imu1", "imu2", "imu3"]):
                imu = imu_data.get(imu_key, {})
                
                roll = imu.get("roll", 0.0)
                pitch = imu.get("pitch", 0.0)
                yaw = imu.get("yaw", 0.0)
                
                self.imu_table.item(i, 1).setText(f"{roll:.1f}")
                self.imu_table.item(i, 2).setText(f"{pitch:.1f}")
                self.imu_table.item(i, 3).setText(f"{yaw:.1f}")
                
                # 根据在线状态着色
                online = imu_data.get("online_status", {}).get(imu_key, False)
                color = QColor(0, 255, 0) if online else QColor(150, 150, 150)
                for col in range(1, 4):
                    self.imu_table.item(i, col).setForeground(color)
            
            # 更新夹爪
            gripper_value = imu_data.get("gripper", 0.0)
            gripper_percent = int(gripper_value * 100)
            self.gripper_label.setText(f"位置: {gripper_percent}%")
            self.gripper_bar.setValue(gripper_percent)
            
            # 更新连接状态
            online_status = imu_data.get("online_status", {})
            self.status_label1.setText(f"IMU1: {'🟢 在线' if online_status.get('imu1') else '⚪ 离线'}")
            self.status_label2.setText(f"IMU2: {'🟢 在线' if online_status.get('imu2') else '⚪ 离线'}")
            self.status_label3.setText(f"IMU3: {'🟢 在线' if online_status.get('imu3') else '⚪ 离线'}")
        
        except Exception as e:
            print(f"⚠️  IMU面板更新错误: {e}")
