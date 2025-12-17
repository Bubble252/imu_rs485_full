#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夹爪控制面板组件
提供键盘快捷键和按钮控制夹爪开合
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QProgressBar, QSlider
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QKeyEvent


class GripperControlWidget(QWidget):
    """夹爪控制面板"""
    
    # 信号：发送夹爪控制命令到主程序
    gripper_command = pyqtSignal(str)  # "open" 或 "close"
    gripper_value_changed = pyqtSignal(float)  # 直接设置夹爪值 0.0-1.0
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_value = 0.0  # 当前夹爪值
        self.is_opening = False   # 是否正在打开
        self.is_closing = False   # 是否正在闭合
        
        # 定时器：持续发送命令（模拟按住按键）
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.on_timer_update)
        self.update_timer.setInterval(50)  # 50ms = 20Hz
        
        self.init_ui()
        self.setFocusPolicy(Qt.StrongFocus)  # 接收键盘事件
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # === 标题 ===
        title = QLabel("🤏 夹爪控制")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # === 当前状态显示 ===
        status_group = QGroupBox("当前状态")
        status_layout = QVBoxLayout(status_group)
        
        self.value_label = QLabel("位置: 0.00 (0%)")
        self.value_label.setAlignment(Qt.AlignCenter)
        value_font = QFont()
        value_font.setPointSize(14)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(30)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bbb;
                border-radius: 5px;
                text-align: center;
                font-size: 11pt;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #ff4444,
                    stop: 0.5 #ffdd44,
                    stop: 1 #44ff44
                );
            }
        """)
        
        status_layout.addWidget(self.value_label)
        status_layout.addWidget(self.progress_bar)
        layout.addWidget(status_group)
        
        # === 按钮控制 ===
        btn_group = QGroupBox("按钮控制")
        btn_layout = QVBoxLayout(btn_group)
        
        # 打开/闭合按钮（横向）
        action_layout = QHBoxLayout()
        
        self.open_btn = QPushButton("⬆️ 打开 (1)")
        self.open_btn.setMinimumHeight(45)
        self.open_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.open_btn.pressed.connect(self.on_open_pressed)
        self.open_btn.released.connect(self.on_open_released)
        
        self.close_btn = QPushButton("⬇️ 闭合 (2)")
        self.close_btn.setMinimumHeight(45)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #c0180a;
            }
        """)
        self.close_btn.pressed.connect(self.on_close_pressed)
        self.close_btn.released.connect(self.on_close_released)
        
        action_layout.addWidget(self.open_btn)
        action_layout.addWidget(self.close_btn)
        btn_layout.addLayout(action_layout)
        
        # 快速设置按钮
        preset_layout = QHBoxLayout()
        
        self.fully_close_btn = QPushButton("完全闭合")
        self.fully_close_btn.clicked.connect(lambda: self.set_gripper_value(0.0))
        
        self.half_open_btn = QPushButton("半开")
        self.half_open_btn.clicked.connect(lambda: self.set_gripper_value(0.5))
        
        self.fully_open_btn = QPushButton("完全打开")
        self.fully_open_btn.clicked.connect(lambda: self.set_gripper_value(1.0))
        
        for btn in [self.fully_close_btn, self.half_open_btn, self.fully_open_btn]:
            btn.setMinimumHeight(30)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #607D8B;
                    color: white;
                    border: none;
                    border-radius: 3px;
                    font-size: 9pt;
                }
                QPushButton:hover {
                    background-color: #546E7A;
                }
            """)
        
        preset_layout.addWidget(self.fully_close_btn)
        preset_layout.addWidget(self.half_open_btn)
        preset_layout.addWidget(self.fully_open_btn)
        btn_layout.addLayout(preset_layout)
        
        layout.addWidget(btn_group)
        
        # === 滑动条控制 ===
        slider_group = QGroupBox("精确控制")
        slider_layout = QVBoxLayout(slider_group)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(0)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(10)
        self.slider.valueChanged.connect(self.on_slider_changed)
        
        slider_layout.addWidget(self.slider)
        layout.addWidget(slider_group)
        
        # === 键盘提示 ===
        hint_label = QLabel("💡 提示：点击此面板后，按住 '1' 打开，'2' 闭合")
        hint_label.setStyleSheet("""
            QLabel {
                background-color: #FFF3CD;
                color: #856404;
                border: 1px solid #FFC107;
                border-radius: 3px;
                padding: 8px;
                font-size: 9pt;
            }
        """)
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        
        layout.addStretch()
    
    def keyPressEvent(self, event: QKeyEvent):
        """处理键盘按下事件"""
        key = event.key()
        
        if key == Qt.Key_1 and not event.isAutoRepeat():
            # 按下 '1' 键 - 打开
            self.on_open_pressed()
        elif key == Qt.Key_2 and not event.isAutoRepeat():
            # 按下 '2' 键 - 闭合
            self.on_close_pressed()
        else:
            super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event: QKeyEvent):
        """处理键盘松开事件"""
        key = event.key()
        
        if key == Qt.Key_1 and not event.isAutoRepeat():
            # 松开 '1' 键
            self.on_open_released()
        elif key == Qt.Key_2 and not event.isAutoRepeat():
            # 松开 '2' 键
            self.on_close_released()
        else:
            super().keyReleaseEvent(event)
    
    def on_open_pressed(self):
        """打开按钮/键被按下"""
        self.is_opening = True
        self.is_closing = False
        if not self.update_timer.isActive():
            self.update_timer.start()
        self.gripper_command.emit("open")
    
    def on_open_released(self):
        """打开按钮/键被松开"""
        self.is_opening = False
        if not self.is_closing:
            self.update_timer.stop()
            self.gripper_command.emit("stop")  # 发送停止命令
    
    def on_close_pressed(self):
        """闭合按钮/键被按下"""
        self.is_closing = True
        self.is_opening = False
        if not self.update_timer.isActive():
            self.update_timer.start()
        self.gripper_command.emit("close")
    
    def on_close_released(self):
        """闭合按钮/键被松开"""
        self.is_closing = False
        if not self.is_opening:
            self.update_timer.stop()
            self.gripper_command.emit("stop")  # 发送停止命令
    
    def on_timer_update(self):
        """定时器更新 - 持续发送命令"""
        if self.is_opening:
            self.gripper_command.emit("open")
        elif self.is_closing:
            self.gripper_command.emit("close")
    
    def on_slider_changed(self, value):
        """滑动条变化"""
        gripper_value = value / 100.0
        self.set_gripper_value(gripper_value)
    
    def set_gripper_value(self, value):
        """设置夹爪值（0.0-1.0）"""
        value = max(0.0, min(1.0, value))
        self.current_value = value
        self.update_display(value)
        self.gripper_value_changed.emit(value)
    
    def update_display(self, value):
        """更新显示"""
        percent = int(value * 100)
        self.value_label.setText(f"位置: {value:.2f} ({percent}%)")
        self.progress_bar.setValue(percent)
        
        # 更新滑动条（不触发信号）
        self.slider.blockSignals(True)
        self.slider.setValue(percent)
        self.slider.blockSignals(False)
        
        # 根据值更新状态文字颜色
        if value < 0.3:
            status = "闭合"
            color = "#f44336"
        elif value < 0.7:
            status = "半开"
            color = "#ff9800"
        else:
            status = "打开"
            color = "#4CAF50"
        
        self.value_label.setStyleSheet(f"color: {color};")
    
    def update_from_robot(self, gripper_value):
        """从机器人状态更新显示（不发送命令）"""
        self.current_value = gripper_value
        self.update_display(gripper_value)


if __name__ == "__main__":
    """测试代码"""
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    widget = GripperControlWidget()
    widget.setWindowTitle("夹爪控制测试")
    widget.resize(350, 500)
    
    # 连接信号
    widget.gripper_command.connect(lambda cmd: print(f"命令: {cmd}"))
    widget.gripper_value_changed.connect(lambda val: print(f"设置值: {val:.2f}"))
    
    widget.show()
    sys.exit(app.exec_())
