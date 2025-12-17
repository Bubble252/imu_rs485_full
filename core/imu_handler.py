# -*- coding: utf-8 -*-
"""
IMU数据处理模块

负责:
- RS485串口通信 (使用device_model.DeviceModel)
- 多IMU数据读取 (主臂、从臂、底座)
- 数据解析和验证
- Yaw角标准化处理

协议说明:
- 使用Modbus RTU协议与WIT传感器通信
- 主动发送读取命令，等待设备响应
- 支持三个设备地址: 0x50, 0x51, 0x52
"""

import threading
import time
from typing import Optional, Callable, Dict, List, Tuple

# 导入配置
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config, get_config

# 导入device_model (与triple相同的RS485通信模块)
# 先尝试从父目录导入
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    import device_model
except ImportError:
    # 如果导入失败，尝试从imu_RS485目录导入
    imu_rs485_dir = os.path.join(parent_dir, 'imu_RS485')
    if imu_rs485_dir not in sys.path:
        sys.path.insert(0, imu_rs485_dir)
    import device_model


class IMUHandler:
    """
    IMU传感器管理类 (使用device_model.DeviceModel)
    
    管理三个WIT传感器:
    - 主臂IMU (地址0x50): 控制机械臂关节1
    - 从臂IMU (地址0x51): 控制机械臂关节2  
    - 底座IMU (地址0x52): 控制旋转底座
    
    与triple_imu_rs485_publisher_dual_cam_UI_voice.py使用相同的:
    - device_model.DeviceModel 类
    - Modbus RTU 协议
    - 数据回调机制
    """
    
    def __init__(self, config: Config = None):
        """
        初始化IMU处理器
        
        Args:
            config: 全局配置对象，None则使用默认配置
        """
        self.config = config or get_config()
        self.imu_config = self.config.imu
        
        # RS485设备对象 (与triple相同)
        self._rs485_device: Optional[device_model.DeviceModel] = None
        
        # IMU地址列表 (从配置中获取值)
        self.imu_addresses: List[int] = self.imu_config.address_list
        
        # 数据存储
        self.euler_data: Dict[int, Tuple[float, float, float]] = {
            addr: (0.0, 0.0, 0.0) for addr in self.imu_addresses
        }
        self.normalized_yaw: Dict[int, float] = {
            addr: 0.0 for addr in self.imu_addresses
        }
        self.online_status: Dict[int, bool] = {
            addr: False for addr in self.imu_addresses
        }
        
        # Yaw标准化参考点
        self._yaw_initial: Dict[int, Optional[float]] = {
            addr: None for addr in self.imu_addresses
        }
        
        # 首次有效数据标记
        self._first_valid_data: Dict[int, bool] = {
            addr: False for addr in self.imu_addresses
        }
        
        # 回调函数
        self._callback: Optional[Callable[[int, float, float, float], None]] = None
        
        # 统计信息
        self._last_data_time: Dict[int, float] = {
            addr: 0.0 for addr in self.imu_addresses
        }
        self._timeout_seconds = 1.0  # 超时判定时间
        self._callback_count = 0  # 回调计数器
    
    def _data_callback(self, device_model_instance):
        """
        RS485数据回调函数 (与triple相同)
        当接收到IMU数据时被调用
        
        Args:
            device_model_instance: DeviceModel实例
        """
        self._callback_count += 1
        data = device_model_instance.deviceData
        current_time = time.time()
        
        # 调试：每500次打印一次回调计数
        if self._callback_count % 500 == 0:
            times = [f"{self._last_data_time.get(addr, 0):.1f}" for addr in self.imu_addresses]
            print(f"[DEBUG CB] count={self._callback_count}, last_times={times}")
        
        # 处理每个IMU地址
        for addr in self.imu_addresses:
            if addr in data:
                device_data = data[addr]
                
                # 提取欧拉角（度）- 与triple相同
                roll = device_data.get('AngY', 0.0)
                pitch = -device_data.get('AngX', 0.0)
                yaw = device_data.get('AngZ', 0.0)
                
                # 只处理有效数据（跳过全0数据）
                if abs(roll) > 0.01 or abs(pitch) > 0.01 or abs(yaw) > 0.01:
                    # 打印第一次有效数据
                    if not self._first_valid_data.get(addr, False):
                        print(f"📍 [IMU{addr-0x4F}] 首次有效数据: Roll={roll:.2f}°, Pitch={pitch:.2f}°, Yaw={yaw:.2f}°")
                        self._first_valid_data[addr] = True
                    
                    # Yaw归零处理
                    yaw_normalized = self._normalize_yaw(yaw, addr)
                    
                    # 存储数据
                    self.euler_data[addr] = (roll, pitch, yaw)
                    self.normalized_yaw[addr] = yaw_normalized
                    self._last_data_time[addr] = current_time
                    self.online_status[addr] = True
                    
                    # 触发用户回调
                    if self._callback:
                        self._callback(addr, roll, pitch, yaw_normalized)
    
    def _normalize_yaw(self, yaw: float, addr: int) -> float:
        """
        Yaw角标准化处理 (与triple相同)
        
        Args:
            yaw: 原始yaw角
            addr: IMU地址
            
        Returns:
            float: 标准化后的yaw角
        """
        # 设置初始参考点
        if self._yaw_initial.get(addr) is None:
            self._yaw_initial[addr] = yaw
            print(f"[IMU] IMU 0x{addr:02X} Yaw参考点设置: {yaw:.2f}°")
        
        # 计算偏移
        normalized = yaw - self._yaw_initial[addr]
        
        # 标准化到 [-180, 180] 范围
        while normalized > 180:
            normalized -= 360
        while normalized < -180:
            normalized += 360
        
        return normalized
    
    def connect(self) -> bool:
        """
        连接串口并初始化RS485设备
        
        使用device_model.DeviceModel (与triple相同)
        
        Returns:
            bool: 连接是否成功
        """
        try:
            print("[IMU] 正在初始化RS485设备...")
            
            # 创建DeviceModel实例 (与triple相同)
            self._rs485_device = device_model.DeviceModel(
                "三IMU机械臂",                    # 设备名称
                self.imu_config.serial_port,      # 串口路径
                self.imu_config.baudrate,         # 波特率
                self.imu_addresses,               # 地址列表 [0x50, 0x51, 0x52]
                self._data_callback               # 数据回调函数
            )
            
            # 打开设备
            self._rs485_device.openDevice()
            
            if not self._rs485_device.isOpen:
                print("[IMU] ❌ 无法打开RS485设备")
                return False
            
            print(f"[IMU] ✓ RS485设备已打开: {self.imu_config.serial_port}")
            return True
            
        except Exception as e:
            print(f"[IMU] 串口连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开串口连接"""
        if self._rs485_device:
            self._rs485_device.closeDevice()
            self._rs485_device = None
            print("[IMU] 串口已断开")
    
    def start(self):
        """启动IMU读取"""
        self.start_reading()
    
    def stop(self):
        """停止IMU读取"""
        self.stop_reading()
        self.disconnect()
    
    def set_callback(self, callback: Callable[[int, float, float, float], None]):
        """
        设置数据回调函数
        
        Args:
            callback: 回调函数，参数为 (地址, roll, pitch, yaw)
        """
        self._callback = callback
    
    def start_reading(self):
        """
        启动循环读取 (使用device_model的startLoopRead)
        
        这会启动一个线程，循环向每个IMU发送Modbus读取命令
        """
        if not self._rs485_device or not self._rs485_device.isOpen:
            print("[IMU] ❌ 设备未打开，无法启动读取")
            return
        
        self._rs485_device.startLoopRead()
        print("[IMU] ✓ IMU数据采集已启动 (Modbus循环读取)")
    
    def stop_reading(self):
        """停止数据读取"""
        if self._rs485_device:
            self._rs485_device.stopLoopRead()
            print("[IMU] 循环读取已停止")
    
    def reset_yaw_reference(self, address: Optional[int] = None):
        """
        重置Yaw参考点
        
        Args:
            address: 指定IMU地址，None表示重置所有
        """
        if address is not None:
            self._yaw_initial[address] = None
            print(f"[IMU] 已重置IMU 0x{address:02X}的Yaw参考点")
        else:
            for addr in self.imu_addresses:
                self._yaw_initial[addr] = None
            print("[IMU] 已重置所有IMU的Yaw参考点")
    
    def get_euler_data(self, address: int) -> Tuple[float, float, float]:
        """
        获取指定IMU的欧拉角数据
        
        Args:
            address: IMU地址
            
        Returns:
            Tuple[roll, pitch, yaw]: 欧拉角 (度)
        """
        return self.euler_data.get(address, (0.0, 0.0, 0.0))
    
    def get_normalized_yaw(self, address: int) -> float:
        """
        获取标准化后的Yaw角
        
        Args:
            address: IMU地址
            
        Returns:
            float: 标准化Yaw角 (度)
        """
        return self.normalized_yaw.get(address, 0.0)
    
    def is_online(self, address: int) -> bool:
        """
        检查IMU是否在线
        
        Args:
            address: IMU地址
            
        Returns:
            bool: 是否在线
        """
        return self.online_status.get(address, False)
    
    def get_all_online_status(self) -> Dict[int, bool]:
        """获取所有IMU在线状态"""
        # 更新在线状态
        current_time = time.time()
        for addr in self.imu_addresses:
            last_time = self._last_data_time.get(addr, 0.0)
            self.online_status[addr] = (current_time - last_time) < self._timeout_seconds
        return self.online_status.copy()
    
    def send_command(self, address: int, command: bytes) -> bool:
        """
        向指定IMU发送命令
        
        Args:
            address: IMU地址
            command: 命令字节
            
        Returns:
            bool: 发送是否成功
        """
        try:
            if self._rs485_device and self._rs485_device.isOpen:
                self._rs485_device.sendData(list(command))
                return True
            return False
        except Exception as e:
            print(f"[IMU] 发送命令失败: {e}")
            return False
    
    def get_euler(self, address: int, component: str) -> float:
        """
        获取指定IMU的单个欧拉角分量
        
        Args:
            address: IMU地址
            component: 分量名 ('roll', 'pitch', 'yaw')
            
        Returns:
            float: 角度值
        """
        data = self.euler_data.get(address, (0.0, 0.0, 0.0))
        if component == 'roll':
            return data[0]
        elif component == 'pitch':
            return data[1]
        elif component == 'yaw':
            return data[2]
        return 0.0
    
    def get_euler_dict(self, address: int) -> Dict[str, float]:
        """
        获取指定IMU的欧拉角字典
        
        Args:
            address: IMU地址
            
        Returns:
            Dict: {'roll': float, 'pitch': float, 'yaw': float}
        """
        data = self.euler_data.get(address, (0.0, 0.0, 0.0))
        return {
            'roll': data[0],
            'pitch': data[1],
            'yaw': self.normalized_yaw.get(address, data[2])
        }
    
    def get_yaw_offset(self, address: int) -> Optional[float]:
        """
        获取指定IMU的Yaw偏移量（用于终端显示）
        
        Args:
            address: IMU地址
            
        Returns:
            Optional[float]: Yaw偏移量（度），如果未设置则返回None
        """
        return self._yaw_initial.get(address, None)
