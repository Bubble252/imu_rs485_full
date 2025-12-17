# IMU机械臂控制系统

## 项目概述

本项目是一个模块化的IMU机械臂遥操作系统，通过三个WIT传感器读取操作者手臂姿态，计算末端位置，并通过ZeroMQ发送到远程机器人控制器。

### 核心功能

- **三IMU数据采集**: 主臂、从臂、底座三个IMU传感器的数据读取和处理
- **运动学计算**: 二连杆机械臂正运动学，计算末端位置
- **远程通信**: 通过ZeroMQ与远程B服务器进行双向通信
- **可视化UI**: PyQt5实时显示视频、IMU数据、3D轨迹
- **音视频反馈**: 接收远程摄像头视频和音频流

## 项目结构

```
full_project/
├── config/                 # 配置模块
│   ├── __init__.py        # 配置加载器
│   └── settings.yaml      # 统一配置文件 ⭐
├── core/                   # 核心功能模块
│   ├── __init__.py
│   ├── imu_handler.py     # IMU数据读取和处理
│   ├── zmq_manager.py     # ZeroMQ通信管理
│   ├── kinematics.py      # 运动学计算
│   ├── gripper.py         # 夹爪控制
│   ├── audio.py           # 音频处理
│   └── video.py           # 视频处理
├── ui/                     # 可视化界面
│   ├── __init__.py
│   ├── viewer.py          # 主界面
│   └── widgets/           # UI组件
│       ├── video_panel.py
│       ├── imu_panel.py
│       ├── trajectory_3d.py
│       ├── control_panel.py
│       ├── gripper_control.py
│       └── audio_waveform.py
├── scripts/                # 启动脚本
│   ├── setup_tunnel.sh    # SSH隧道建立
│   ├── start_main.sh      # 主程序启动
│   └── start_ui.sh        # UI启动
├── docs/                   # 文档
│   └── README.md          # 本文件
└── main.py                 # 主程序入口 ⭐
```

## 快速开始

### 1. 环境准备

系统使用两个独立的Conda环境：

```bash
# 主程序环境 (lerobot)
conda create -n lerobot python=3.10
conda activate lerobot
pip install pyserial pyzmq numpy scipy

# UI环境 (pyqt5_ui)
conda create -n pyqt5_ui python=3.10
conda activate pyqt5_ui
pip install PyQt5 pyqtgraph numpy pyzmq
```

### 2. 配置参数

编辑 `config/settings.yaml` 配置所有参数：

```yaml
# 机械臂参数
arm:
  link1_length: 0.3  # 主臂长度（米）
  link2_length: 0.25 # 从臂长度（米）

# 网络配置
network:
  b_server:
    host: "192.168.1.121"
    push_port: 5555
    pull_port: 5556
  
  # SSH隧道 (如需通过跳板机连接)
  ssh_tunnel:
    enabled: true
    jump_host: "capriai@capri.icu"
    target_host: "yhx@192.168.1.121"
    key_file: "keys/capri_yhx_2237"
  
  # 调试UI
  debug_ui:
    enabled: true
    port: 5560

# IMU配置
imu:
  serial_port: "/dev/ttyUSB0"
  baudrate: 115200
  timeout: 0.1
  addresses: [0x50, 0x51, 0x52]  # 主臂、从臂、底座

# 控制频率
control:
  publish_rate: 20  # Hz
  online_only: false

# 夹爪配置  
gripper:
  initial_value: 0.5
  step: 0.02
  update_rate: 20  # Hz
  key_timeout: 0.3  # 秒
```

### 3. 建立SSH隧道（可选）

如果需要通过跳板机连接远程B服务器：

```bash
cd full_project
./scripts/setup_tunnel.sh
```

### 4. 运行系统

**启动主程序**（在lerobot环境）：
```bash
./scripts/start_main.sh
```

**启动UI**（在pyqt5_ui环境，新终端）：
```bash
./scripts/start_ui.sh
```

## 配置说明

所有参数都在 `config/settings.yaml` 中统一管理，**无需复杂的命令行参数**。

### 主要配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `network.b_server.port` | B服务器端口 | 5555 |
| `network.video.port` | 视频接收端口 | 5557 |
| `network.audio.port` | 音频接收端口 | 5561 |
| `network.debug_ui_port` | UI调试端口 | 5560 |
| `imu.serial_port` | IMU串口 | /dev/ttyUSB0 |
| `control.publish_frequency` | 发布频率 | 20 Hz |
| `arm.link1_length` | 主臂长度 | 0.25 m |
| `arm.link2_length` | 从臂长度 | 0.27 m |

### 坐标映射

系统支持将原始坐标映射到目标范围：

```yaml
coordinate_mapping:
  # 原始范围
  raw_range:
    x_min: -0.5
    x_max: 0.5
    y_min: 0.0
    y_max: 0.6
    z_min: -0.3
    z_max: 0.3
  
  # 目标范围
  target_range:
    x_min: -0.35
    x_max: 0.35
    y_min: 0.0
    y_max: 0.5
    z_min: -0.25
    z_max: 0.25
```

## 系统架构

```
┌─────────────────┐     ┌─────────────────┐
│  IMU传感器 x3   │────▶│  IMUHandler     │
│  (RS485)        │     │  数据读取       │
└─────────────────┘     └────────┬────────┘
                                 │
                                 ▼
┌─────────────────┐     ┌─────────────────┐
│  Kinematics     │◀────│  main.py        │
│  运动学计算     │     │  主控制器       │
└─────────────────┘     └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  ZMQ PUSH       │    │  ZMQ PUB        │    │  ZMQ PUB        │
│  发送到B服务器   │    │  发送到UI       │    │  发送到LeRobot  │
│  (端口5555)     │    │  (端口5560)     │    │  (端口5559)     │
└────────┬────────┘    └────────┬────────┘    └─────────────────┘
         │                      │
         ▼                      ▼
┌─────────────────┐    ┌─────────────────┐
│  B服务器        │    │  PyQt5 UI       │
│  机器人控制     │    │  可视化界面     │
│  (远程)         │    │  (本地)         │
└─────────────────┘    └─────────────────┘
```

## 数据格式

### 控制数据 (发送到B服务器)

```json
{
    "type": "control",
    "timestamp": 1699999999.123,
    "coordinates": {
        "x": 0.15,
        "y": 0.30,
        "z": 0.05,
        "base": 45.0,
        "gripper": 0.7
    },
    "raw": {
        "x": 0.18,
        "y": 0.35,
        "z": 0.06,
        "base": 50.0,
        "gripper": 0.7
    },
    "imu": {
        "imu1": {"roll": 5.2, "pitch": 30.5, "yaw": 0.0},
        "imu2": {"roll": 2.1, "pitch": 45.3, "yaw": 0.0},
        "imu3": {"roll": 0.5, "pitch": 1.2, "yaw": 45.0}
    }
}
```

### 调试数据 (发送到UI)

```json
{
    "type": "debug",
    "timestamp": 1699999999.123,
    "euler": {
        "imu1": {"roll": 5.2, "pitch": 30.5, "yaw": 0.0},
        "imu2": {"roll": 2.1, "pitch": 45.3, "yaw": 0.0},
        "imu3": {"roll": 0.5, "pitch": 1.2, "yaw": 45.0}
    },
    "status": {
        "imu1_online": true,
        "imu2_online": true,
        "imu3_online": true
    },
    "coordinates": {
        "raw": [0.18, 0.35, 0.06, 50.0, 0.7],
        "clipped": [0.15, 0.30, 0.05, 45.0, 0.7]
    },
    "gripper": 0.7
}
```

## 常见问题

### Q: 串口连接失败

```bash
# 检查串口设备
ls -la /dev/ttyUSB*

# 添加用户到dialout组
sudo usermod -a -G dialout $USER

# 临时权限
sudo chmod 666 /dev/ttyUSB0
```

### Q: 端口被占用

```bash
# 查看端口占用
lsof -i :5560

# 终止占用进程
kill -9 <PID>
```

### Q: SSH隧道断开

```bash
# 重新建立隧道
./scripts/setup_tunnel.sh
```

### Q: UI无法启动

```bash
# 确保在pyqt5_ui环境中
conda activate pyqt5_ui

# 检查依赖
pip install PyQt5 pyqtgraph numpy pyzmq
```

## 开发说明

### 添加新功能

1. 在 `core/` 目录下创建新模块
2. 在 `config/settings.yaml` 添加相关配置
3. 在 `main.py` 中初始化和调用新模块

### 自定义UI组件

1. 在 `ui/widgets/` 创建新组件
2. 在 `ui/viewer.py` 中导入和使用

## 版本历史

- v1.0.0: 初始模块化版本，从单文件重构

## 许可证

MIT License
