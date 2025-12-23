#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
负责加载和管理YAML配置文件
"""

import os
import yaml
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ArmConfig:
    """机械臂配置"""
    link1_length: float = 0.25
    link2_length: float = 0.27
    
    @property
    def L1(self) -> float:
        """杆1长度（别名，兼容 triple 风格）"""
        return self.link1_length
    
    @property
    def L2(self) -> float:
        """杆2长度（别名，兼容 triple 风格）"""
        return self.link2_length


@dataclass
class IMUConfig:
    """IMU配置"""
    serial_port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    timeout: float = 0.1  # 串口超时(秒)
    addresses: Dict[str, int] = field(default_factory=lambda: {
        "imu1": 0x50,
        "imu2": 0x51,
        "imu3": 0x52
    })
    yaw_normalization_mode: str = "NORMAL"
    yaw_normalization_threshold: float = 100.0
    
    @property
    def address_list(self) -> List[int]:
        """获取IMU地址列表"""
        return list(self.addresses.values())


@dataclass
class NetworkEndpoint:
    """网络端点配置"""
    enabled: bool = True
    host: str = "localhost"
    port: int = 5555


@dataclass
class VideoEndpoint:
    """视频端点配置（扩展了display_opencv选项）"""
    enabled: bool = True
    host: str = "localhost"
    port: int = 5557
    display_opencv: bool = False  # 是否使用OpenCV窗口显示视频


@dataclass
class SSHTunnelConfig:
    """SSH隧道配置"""
    enabled: bool = False
    proxy_host: str = ""
    proxy_port: int = 22
    proxy_user: str = ""
    proxy_key: str = ""
    target_host: str = ""
    target_port: int = 22
    target_user: str = ""
    target_key: str = ""
    port_forwards: List[int] = field(default_factory=list)


@dataclass
class NetworkConfig:
    """网络配置"""
    b_server: NetworkEndpoint = field(default_factory=lambda: NetworkEndpoint(port=5555))
    lerobot: NetworkEndpoint = field(default_factory=lambda: NetworkEndpoint(enabled=False, port=5559))
    video: VideoEndpoint = field(default_factory=VideoEndpoint)
    audio: NetworkEndpoint = field(default_factory=lambda: NetworkEndpoint(port=5561))
    debug_ui_port: int = 5560
    debug_ui_enabled: bool = True
    ui_command_port: int = 5562
    ssh_tunnel: SSHTunnelConfig = field(default_factory=SSHTunnelConfig)


@dataclass
class GripperConfig:
    """夹爪控制配置"""
    initial_value: float = 0.5
    step: float = 0.005
    update_rate: int = 50
    key_timeout: float = 0.1


@dataclass
class ControlConfig:
    """控制参数配置"""
    publish_rate: int = 20
    online_only: bool = True
    
    @property
    def publish_interval(self) -> float:
        """获取发布间隔(秒)"""
        return 1.0 / self.publish_rate


@dataclass
class CoordinateRange:
    """坐标范围"""
    x_min: float = 0.0
    x_max: float = 1.0
    y_min: float = -0.5
    y_max: float = 0.5
    z_min: float = 0.0
    z_max: float = 0.5


@dataclass
class CoordinateMappingConfig:
    """坐标映射配置"""
    raw: CoordinateRange = field(default_factory=CoordinateRange)
    target: CoordinateRange = field(default_factory=CoordinateRange)


@dataclass
class DatasetConfig:
    """数据集配置（LeRobot）"""
    repo_id: str = ""                       # 数据集名称/ID (空字符串表示使用时间戳)
    instruction: str = "Real robot teleoperation"  # 任务描述
    fps: int = 30                           # 视频帧率
    data_root: str = "real_robot_data"      # 数据保存根目录
    action_dim: int = 13                    # 动作维度
    state_dim: int = 13                     # 状态维度
    image_height: int = 480                 # 图像高度
    image_width: int = 640                  # 图像宽度


class Config:
    """
    配置管理器
    
    使用方法:
        from config import config
        print(config.arm.link1_length)
        print(config.network.b_server.port)
    """
    
    def __init__(self):
        self.arm = ArmConfig()
        self.imu = IMUConfig()
        self.network = NetworkConfig()
        self.control = ControlConfig()
        self.gripper = GripperConfig()
        self.coordinate_mapping = CoordinateMappingConfig()
        self.dataset = DatasetConfig()
        self.debug = False
        self._raw_config: Dict[str, Any] = {}
    
    @classmethod
    def load(cls, config_path: str = "config/settings.yaml") -> "Config":
        """
        从YAML文件加载配置
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            Config对象
        """
        cfg = cls()
        
        # 获取配置文件绝对路径
        if not os.path.isabs(config_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, config_path)
        
        if not os.path.exists(config_path):
            print(f"⚠️  配置文件不存在: {config_path}")
            print("   使用默认配置")
            return cfg
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f)
                cfg._raw_config = raw or {}
            
            cfg._parse_config(raw)
            print(f"✓ 配置已加载: {config_path}")
            
        except Exception as e:
            print(f"❌ 配置加载失败: {e}")
            print("   使用默认配置")
        
        return cfg
    
    def _parse_config(self, raw: Dict[str, Any]):
        """解析原始配置字典"""
        if not raw:
            return
        
        # 系统配置
        system = raw.get("system", {})
        self.debug = system.get("debug", False)
        
        # 机械臂配置
        arm = raw.get("arm", {})
        self.arm.link1_length = arm.get("link1_length", 0.25)
        self.arm.link2_length = arm.get("link2_length", 0.27)
        
        # IMU配置
        imu = raw.get("imu", {})
        self.imu.serial_port = imu.get("serial_port", "/dev/ttyUSB0")
        self.imu.baudrate = imu.get("baudrate", 115200)
        self.imu.timeout = imu.get("timeout", 0.1)
        self.imu.addresses = imu.get("addresses", self.imu.addresses)
        self.imu.yaw_normalization_mode = imu.get("yaw_normalization_mode", "NORMAL")
        self.imu.yaw_normalization_threshold = imu.get("yaw_normalization_threshold", 100.0)
        
        # 网络配置
        network = raw.get("network", {})
        
        b_server = network.get("b_server", {})
        self.network.b_server = NetworkEndpoint(
            enabled=b_server.get("enabled", True),
            host=b_server.get("host", "localhost"),
            port=b_server.get("port", 5555)
        )
        
        lerobot = network.get("lerobot", {})
        self.network.lerobot = NetworkEndpoint(
            enabled=lerobot.get("enabled", False),
            host=lerobot.get("host", "localhost"),
            port=lerobot.get("port", 5559)
        )
        
        video = network.get("video", {})
        self.network.video = VideoEndpoint(
            enabled=video.get("enabled", True),
            host=video.get("host", "localhost"),
            port=video.get("port", 5557),
            display_opencv=video.get("display_opencv", False)
        )
        
        audio = network.get("audio", {})
        self.network.audio = NetworkEndpoint(
            enabled=audio.get("enabled", True),
            host=audio.get("host", "localhost"),
            port=audio.get("port", 5561)
        )
        
        debug_ui = network.get("debug_ui", {})
        self.network.debug_ui_port = debug_ui.get("port", 5560)
        self.network.debug_ui_enabled = debug_ui.get("enabled", True)
        
        ui_command = network.get("ui_command", {})
        self.network.ui_command_port = ui_command.get("port", 5562)
        
        # SSH隧道配置
        ssh = raw.get("ssh_tunnel", {})
        proxy = ssh.get("proxy", {})
        target = ssh.get("target", {})
        self.network.ssh_tunnel = SSHTunnelConfig(
            enabled=ssh.get("enabled", False),
            proxy_host=proxy.get("host", ""),
            proxy_port=proxy.get("port", 22),
            proxy_user=proxy.get("user", ""),
            proxy_key=proxy.get("key_file", ""),
            target_host=target.get("host", ""),
            target_port=target.get("port", 22),
            target_user=target.get("user", ""),
            target_key=target.get("key_file", ""),
            port_forwards=ssh.get("port_forwards", [])
        )
        
        # 控制配置
        control = raw.get("control", {})
        self.control.publish_rate = control.get("publish_rate", 20)
        self.control.online_only = control.get("online_only", True)
        
        # 夹爪配置
        gripper_cfg = control.get("gripper", {})
        self.gripper.initial_value = gripper_cfg.get("initial_value", 0.5)
        self.gripper.step = gripper_cfg.get("step", 0.005)
        self.gripper.update_rate = gripper_cfg.get("update_rate", 50)
        self.gripper.key_timeout = gripper_cfg.get("key_timeout", 0.1)
        
        # 坐标映射配置
        mapping = raw.get("coordinate_mapping", {})
        
        raw_range = mapping.get("raw", {})
        self.coordinate_mapping.raw = CoordinateRange(
            x_min=raw_range.get("x_min", 0.39),
            x_max=raw_range.get("x_max", 0.52),
            y_min=raw_range.get("y_min", -0.4),
            y_max=raw_range.get("y_max", 0.4),
            z_min=raw_range.get("z_min", 0.0),
            z_max=raw_range.get("z_max", 0.3)
        )
        
        target_range = mapping.get("target", {})
        self.coordinate_mapping.target = CoordinateRange(
            x_min=target_range.get("x_min", 0.22),
            x_max=target_range.get("x_max", 0.42),
            y_min=target_range.get("y_min", -0.2),
            y_max=target_range.get("y_max", 0.2),
            z_min=target_range.get("z_min", 0.1),
            z_max=target_range.get("z_max", 0.4)
        )
        
        # 数据集配置
        dataset = raw.get("dataset", {})
        self.dataset.repo_id = dataset.get("repo_id", "")  # 空字符串表示使用时间戳
        self.dataset.instruction = dataset.get("instruction", "Real robot teleoperation")
        self.dataset.fps = dataset.get("fps", 30)
        self.dataset.data_root = dataset.get("data_root", "real_robot_data")
        self.dataset.action_dim = dataset.get("action_dim", 13)
        self.dataset.state_dim = dataset.get("state_dim", 13)
        self.dataset.image_height = dataset.get("image_height", 480)
        self.dataset.image_width = dataset.get("image_width", 640)
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取原始配置值"""
        keys = key.split(".")
        value = self._raw_config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default
    
    @property
    def publish_interval(self) -> float:
        """获取发布间隔（秒）"""
        return 1.0 / self.control.publish_rate


# 全局配置实例（延迟加载）
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config(config_path: str = "config/settings.yaml") -> Config:
    """重新加载配置"""
    global _config
    _config = Config.load(config_path)
    return _config


# 创建全局配置实例供直接导入使用
config = get_config()
