#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时曲线图组件
使用PyQtGraph绘制IMU姿态角曲线
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt

try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False


class ChartPanelWidget(QWidget):
    """实时曲线图面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_points = 100  # 显示最近100个点
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("📈 IMU姿态曲线（最近100点）")
        group_layout = QVBoxLayout(group)
        
        if PYQTGRAPH_AVAILABLE:
            # 配置PyQtGraph
            pg.setConfigOptions(antialias=True)
            
            # 创建绘图窗口
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground('w')
            self.plot_widget.showGrid(x=True, y=True)
            self.plot_widget.setLabel('left', '角度 (°)')
            self.plot_widget.setLabel('bottom', '时间点')
            self.plot_widget.addLegend()
            
            # 创建曲线（IMU3的pitch, roll, yaw）
            self.pitch_curve = self.plot_widget.plot(
                pen=pg.mkPen(color='r', width=2),
                name='Pitch'
            )
            self.roll_curve = self.plot_widget.plot(
                pen=pg.mkPen(color='g', width=2),
                name='Roll'
            )
            self.yaw_curve = self.plot_widget.plot(
                pen=pg.mkPen(color='b', width=2),
                name='Yaw'
            )
            
            group_layout.addWidget(self.plot_widget)
        
        else:
            label = QLabel("⚠️  PyQtGraph未安装\n请运行: pip install pyqtgraph")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: orange; font-size: 10pt;")
            group_layout.addWidget(label)
        
        layout.addWidget(group)
    
    def update_charts(self, chart_buffer):
        """
        更新曲线数据
        Args:
            chart_buffer: List[{
                "timestamp": float,
                "imu1": {...},
                "imu2": {...},
                "imu3": {"roll": ..., "pitch": ..., "yaw": ...}
            }]
        """
        if not PYQTGRAPH_AVAILABLE or not chart_buffer:
            return
        
        try:
            # 提取IMU3数据（末端姿态）
            pitch_data = [point["imu3"].get("pitch", 0) for point in chart_buffer]
            roll_data = [point["imu3"].get("roll", 0) for point in chart_buffer]
            yaw_data = [point["imu3"].get("yaw", 0) for point in chart_buffer]
            
            # X轴（时间点索引）
            x_data = list(range(len(pitch_data)))
            
            # 更新曲线
            self.pitch_curve.setData(x_data, pitch_data)
            self.roll_curve.setData(x_data, roll_data)
            self.yaw_curve.setData(x_data, yaw_data)
        
        except Exception as e:
            print(f"⚠️  曲线图更新错误: {e}")
