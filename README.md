# IMU 机械臂控制系统 (Full Project)

模块化的 IMU 遥操作控制系统，用于通过 IMU 传感器控制机械臂并采集数据。

## 快速开始

### 1. 建立 SSH 隧道（连接远程 B 服务器）

```bash
# 进入 whole3_2 目录
cd ../whole3_2

# 只建立后台隧道（推荐）
./connect.sh --tunnel-only

# 或者连接服务器同时建立隧道
./connect.sh --with-tunnel

# 验证隧道是否建立
ss -tuln | grep -E '5555|5557|5559|5561'
```

> **注意**: 需要先配置 `~/.ssh/config` 中的 `capri_target` 主机

隧道会转发以下端口：
- `5555`: 控制数据 A → B
- `5557`: 视频 B → A  
- `5561`: 音频 B → A

### 2. 运行主程序

```bash
# 激活环境
conda activate lerobot

# 进入项目目录
cd full_project

# 运行
python main.py
```

### 3. 键盘控制

| 按键 | 功能 |
|------|------|
| `S` | 开始录制 episode |
| `E` | 结束录制 |
| `Y` | 保存当前 episode |
| `N` | 丢弃当前 episode |
| `1` | 夹爪张开（按住） |
| `2` | 夹爪闭合（按住） |
| `Q` | 退出程序 |

---

## 配置说明

所有配置在 `config/settings.yaml` 中修改，修改后重启生效。

### IMU 陀螺仪配置

```yaml
imu:
  # 串口设备（推荐用 by-id 方式，更稳定）
  serial_port: "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
  
  # 波特率
  baudrate: 115200
  
  # IMU 地址（十六进制）
  addresses:
    imu1: 0x50    # 80 - 杆1
    imu2: 0x51    # 81 - 杆2  
    imu3: 0x52    # 82 - 机械爪
    imu4: 0x54    # 84 - 手指（用于夹爪控制）
```

**查找串口设备：**
```bash
ls /dev/serial/by-id/
# 或
ls /dev/ttyUSB*
```

### 机械臂杆长配置

```yaml
arm:
  link1_length: 0.25    # 杆1长度（米）
  link2_length: 0.27    # 杆2长度（米）
```

### 网络端口配置

```yaml
network:
  b_server:
    host: "localhost"   # SSH 隧道后用 localhost
    port: 5555
    
  video:
    enabled: true
    port: 5557
    
  audio:
    enabled: true
    port: 5561
```

### 控制频率

```yaml
control:
  publish_rate: 20      # 发布频率 Hz
  online_only: true     # 仅在所有 IMU 在线时发布
```

---

## 目录结构

```
full_project/
├── main.py              # 主程序入口
├── config/
│   └── settings.yaml    # 配置文件
├── core/                # 核心模块
│   ├── imu_handler.py   # IMU 数据处理
│   ├── kinematics.py    # 运动学计算
│   ├── zmq_manager.py   # ZMQ 通信
│   ├── gripper.py       # 夹爪控制
│   ├── audio.py         # 音频接收
│   └── video.py         # 视频接收
├── scripts/
│   └── setup_tunnel.sh  # SSH 隧道脚本
├── keys/                # SSH 密钥文件
└── ui/                  # PyQt5 UI（可选）
```

---

## 常见问题

### 1. 串口权限问题
```bash
sudo chmod 666 /dev/ttyUSB0
# 或永久添加用户到 dialout 组
sudo usermod -a -G dialout $USER
```

### 2. 查看 IMU 是否识别
```bash
# 查看串口
ls -la /dev/ttyUSB*
# 查看设备 ID
ls /dev/serial/by-id/
```

### 3. SSH 隧道断开
重新运行 `./scripts/setup_tunnel.sh`

### 4. 端口被占用
```bash
# 查看端口占用
lsof -i :5555
# 或
netstat -tlnp | grep 5555
```

---

## 夹爪控制模式

系统支持两种夹爪控制方式：

1. **IMU 控制**（自动）：当 IMU4 (0x54) 配置且在线时
   - 通过 IMU3 和 IMU4 的 Pitch 差值控制
   - 差值 30° → 夹爪全闭 (1.0)
   - 差值 130° → 夹爪全开 (0.0)

2. **键盘控制**（备用）：当 IMU4 离线或未配置时
   - 按住 `1` 张开
   - 按住 `2` 闭合

面板会显示当前控制来源：`🎛️ IMU` 或 `⌨️ 键盘`
