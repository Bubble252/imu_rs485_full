#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频波形显示组件
实时显示音频接收状态、波形和音量
"""

import numpy as np
from collections import deque
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QProgressBar
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QPainterPath


class AudioWaveformWidget(QWidget):
    """音频波形显示面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 数据缓冲
        self.waveform_buffer = deque(maxlen=256)  # 波形数据点
        self.volume_history = deque(maxlen=100)   # 音量历史
        
        # 状态
        self.current_rms = 0.0
        self.frame_count = 0
        self.last_update_time = 0
        self.fps = 0.0
        
        # 音频状态指示
        self.is_receiving = False
        self.underrun_count = 0
        
        self.init_ui()
        
        # 定时重绘
        self.redraw_timer = QTimer()
        self.redraw_timer.timeout.connect(self.update)
        self.redraw_timer.start(33)  # 30 FPS
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # === 标题 ===
        title = QLabel("🔊 音频状态")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # === 状态信息 ===
        status_group = QGroupBox("接收状态")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("状态: ⚪ 等待连接")
        self.fps_label = QLabel("帧率: -- fps")
        self.frame_label = QLabel("帧数: 0")
        self.underrun_label = QLabel("下溢: 0")
        
        for label in [self.status_label, self.fps_label, self.frame_label, self.underrun_label]:
            label.setStyleSheet("padding: 3px;")
            status_layout.addWidget(label)
        
        layout.addWidget(status_group)
        
        # === 音量表 ===
        volume_group = QGroupBox("音量 (RMS)")
        volume_layout = QVBoxLayout(volume_group)
        
        self.volume_label = QLabel("0.00")
        self.volume_label.setAlignment(Qt.AlignCenter)
        vol_font = QFont()
        vol_font.setPointSize(16)
        vol_font.setBold(True)
        self.volume_label.setFont(vol_font)
        
        self.volume_bar = QProgressBar()
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setValue(0)
        self.volume_bar.setTextVisible(True)
        self.volume_bar.setMinimumHeight(25)
        self.volume_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bbb;
                border-radius: 5px;
                text-align: center;
                font-size: 10pt;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #44ff44,
                    stop: 0.6 #ffdd44,
                    stop: 1 #ff4444
                );
            }
        """)
        
        volume_layout.addWidget(self.volume_label)
        volume_layout.addWidget(self.volume_bar)
        layout.addWidget(volume_group)
        
        # === 波形显示区域 ===
        waveform_group = QGroupBox("波形")
        waveform_layout = QVBoxLayout(waveform_group)
        
        self.waveform_canvas = WaveformCanvas()
        self.waveform_canvas.setMinimumHeight(120)
        waveform_layout.addWidget(self.waveform_canvas)
        
        layout.addWidget(waveform_group)
        
        layout.addStretch()
    
    def update_audio_data(self, audio_data):
        """
        更新音频数据
        
        Args:
            audio_data: {
                "waveform": np.array (256 int16样本),
                "rms": float (0.0-1.0),
                "frame_count": int,
                "fps": float,
                "underrun_count": int,
                "receiving": bool
            }
        """
        try:
            # 更新波形数据
            waveform = audio_data.get("waveform")
            if waveform is not None:
                # 归一化到 -1.0 到 1.0
                if isinstance(waveform, np.ndarray):
                    normalized = waveform.astype(np.float32) / 32767.0
                    self.waveform_buffer = deque(normalized, maxlen=256)
                    self.waveform_canvas.update_waveform(list(self.waveform_buffer))
            
            # 更新RMS音量
            rms = audio_data.get("rms", 0.0)
            self.current_rms = rms
            self.volume_history.append(rms)
            
            # 更新显示
            volume_percent = int(min(rms * 200, 100))  # *2 放大显示
            self.volume_label.setText(f"{rms:.3f}")
            self.volume_bar.setValue(volume_percent)
            
            # 根据音量着色
            if rms < 0.3:
                color = "#44ff44"  # 绿色
            elif rms < 0.7:
                color = "#ffdd44"  # 黄色
            else:
                color = "#ff4444"  # 红色
            self.volume_label.setStyleSheet(f"color: {color};")
            
            # 更新状态信息
            self.frame_count = audio_data.get("frame_count", 0)
            self.fps = audio_data.get("fps", 0.0)
            self.underrun_count = audio_data.get("underrun_count", 0)
            self.is_receiving = audio_data.get("receiving", False)
            
            self.frame_label.setText(f"帧数: {self.frame_count}")
            self.fps_label.setText(f"帧率: {self.fps:.1f} fps")
            self.underrun_label.setText(f"下溢: {self.underrun_count}")
            
            # 状态指示
            if self.is_receiving:
                self.status_label.setText("状态: 🟢 正常接收")
                self.status_label.setStyleSheet("color: green; padding: 3px;")
            else:
                self.status_label.setText("状态: 🔴 未接收")
                self.status_label.setStyleSheet("color: red; padding: 3px;")
        
        except Exception as e:
            print(f"⚠️  音频数据更新错误: {e}")


class WaveformCanvas(QWidget):
    """波形绘制画布"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data = []
        self.setMinimumSize(200, 100)
        self.setStyleSheet("background-color: #2b2b2b;")
    
    def update_waveform(self, data):
        """更新波形数据"""
        self.waveform_data = data
        self.update()  # 触发重绘
    
    def paintEvent(self, event):
        """绘制波形"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        center_y = height / 2
        
        # 背景
        painter.fillRect(0, 0, width, height, QColor(43, 43, 43))
        
        # 中线
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        painter.drawLine(0, int(center_y), width, int(center_y))
        
        # 绘制波形
        if len(self.waveform_data) > 1:
            path = QPainterPath()
            
            # 起点
            x_step = width / max(1, len(self.waveform_data) - 1)
            first_val = self.waveform_data[0]
            first_y = center_y - (first_val * center_y * 0.9)  # 0.9留边距
            path.moveTo(0, first_y)
            
            # 绘制路径
            for i, val in enumerate(self.waveform_data[1:], 1):
                x = i * x_step
                y = center_y - (val * center_y * 0.9)
                path.lineTo(x, y)
            
            # 绘制波形线
            painter.setPen(QPen(QColor(0, 255, 0), 2))
            painter.drawPath(path)
        else:
            # 无数据提示
            painter.setPen(QColor(150, 150, 150))
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "等待音频数据...")


if __name__ == "__main__":
    """测试代码"""
    import sys
    from PyQt5.QtWidgets import QApplication
    import time
    
    app = QApplication(sys.argv)
    
    widget = AudioWaveformWidget()
    widget.setWindowTitle("音频波形测试")
    widget.resize(350, 450)
    
    # 模拟数据定时器
    def update_test_data():
        # 生成测试波形（正弦波）
        t = time.time()
        samples = np.sin(np.linspace(0, 10 * np.pi, 256) + t) * 16000
        waveform = samples.astype(np.int16)
        
        # 生成测试RMS
        rms = (np.sin(t * 2) + 1) / 4 + 0.1  # 0.1 - 0.6
        
        test_data = {
            "waveform": waveform,
            "rms": rms,
            "frame_count": int(t * 16.7),
            "fps": 16.7,
            "underrun_count": 0,
            "receiving": True
        }
        
        widget.update_audio_data(test_data)
    
    timer = QTimer()
    timer.timeout.connect(update_test_data)
    timer.start(60)  # 60ms = ~16.7 Hz
    
    widget.show()
    sys.exit(app.exec_())
