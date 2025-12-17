#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D轨迹可视化组件
使用PyQtGraph的GLViewWidget显示机械臂末端轨迹
"""

import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt

try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False
    print("⚠️  PyQtGraph未安装，3D轨迹功能不可用")


class Trajectory3DWidget(QWidget):
    """3D轨迹显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.trajectory_data = []
        self.scatter_item = None
        self.line_item = None
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("🎯 3D轨迹可视化")
        group_layout = QVBoxLayout(group)
        
        if PYQTGRAPH_AVAILABLE:
            # 创建3D视图
            self.view = gl.GLViewWidget()
            self.view.opts['distance'] = 1.0
            self.view.opts['fov'] = 60
            self.view.opts['elevation'] = 30
            self.view.opts['azimuth'] = 45
            
            # 添加坐标网格
            grid = gl.GLGridItem()
            grid.scale(0.1, 0.1, 0.1)
            self.view.addItem(grid)
            
            # 添加坐标轴
            axis = gl.GLAxisItem()
            axis.setSize(0.3, 0.3, 0.3)
            self.view.addItem(axis)
            
            # 初始化散点图（轨迹点）
            self.scatter_item = gl.GLScatterPlotItem(
                pos=np.array([[0, 0, 0]]),
                color=(0, 1, 1, 0.8),
                size=5,
                pxMode=True
            )
            self.view.addItem(self.scatter_item)
            
            # 初始化线图（连接轨迹）
            self.line_item = gl.GLLinePlotItem(
                pos=np.array([[0, 0, 0]]),
                color=(1, 1, 0, 0.6),
                width=2,
                antialias=True
            )
            self.view.addItem(self.line_item)
            
            group_layout.addWidget(self.view)
        
        else:
            # PyQtGraph不可用时显示提示
            label = QLabel("⚠️  PyQtGraph未安装\n请运行: pip install pyqtgraph PyOpenGL")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: orange; font-size: 12pt;")
            group_layout.addWidget(label)
        
        layout.addWidget(group)
    
    def update_trajectory(self, trajectory_buffer):
        """
        更新轨迹数据
        Args:
            trajectory_buffer: List[{"pos": [x,y,z], "timestamp": float}]
        """
        if not PYQTGRAPH_AVAILABLE or not trajectory_buffer:
            return
        
        try:
            # 提取位置数据
            positions = np.array([point["pos"] for point in trajectory_buffer])
            
            # 更新散点图
            if len(positions) > 0:
                self.scatter_item.setData(pos=positions)
            
            # 更新线图（需要至少2个点）
            if len(positions) > 1:
                self.line_item.setData(pos=positions)
        
        except Exception as e:
            print(f"⚠️  3D轨迹更新错误: {e}")
    
    def clear_trajectory(self):
        """清空轨迹"""
        if PYQTGRAPH_AVAILABLE:
            empty_pos = np.array([[0, 0, 0]])
            self.scatter_item.setData(pos=empty_pos)
            self.line_item.setData(pos=empty_pos)
