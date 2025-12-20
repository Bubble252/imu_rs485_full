# LeRobot 数据存储与交互流程详解

## 📊 目录
1. [B端数据存储架构](#b端数据存储架构)
2. [LeRobot数据集格式](#lerobot数据集格式)
3. [数据采集流程](#数据采集流程)
4. [存储与加载流程](#存储与加载流程)
5. [与A端的集成方案](#与a端的集成方案)

---

## 1. B端数据存储架构

### 1.1 核心类：`LeRobotDataHandler`

```python
class LeRobotDataHandler:
    """
    B端的数据存储管理器
    
    职责:
    - 接收来自C端的机器人数据
    - 转换为LeRobot标准格式
    - 管理Episode生命周期
    - 保存视频、音频和状态数据
    """
```

### 1.2 数据流架构图

```
C端(机器人)           →           B端(服务器)           →        LeRobot数据集
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│ 相机捕获     │              │ 数据接收     │              │ 数据集目录   │
│  - JPEG编码  │─────(ZMQ)────→│  - 解码图像  │              │              │
│ 状态读取     │              │  - 格式转换  │              │ ├ meta_data/ │
│  - 关节位置  │              │              │──(add_frame)─→│ ├ videos/    │
│ 音频捕获     │              │ Episode管理  │              │ ├ data.parquet│
│  - Opus编码  │              │  - 累积帧    │              │ └ audio/     │
└──────────────┘              │  - 触发保存  │              └──────────────┘
                              └──────────────┘
```

---

## 2. LeRobot数据集格式

### 2.1 目录结构

```
real_robot_data/12_13_test/
├── meta_data/
│   ├── info.json                    # 数据集元信息
│   ├── episodes.jsonl               # Episode索引
│   ├── stats.json                   # 数据统计信息
│   └── tasks.json                   # 任务列表
├── videos/
│   └── observation.images.left_wrist/
│       ├── episode_000000.mp4       # 视频文件（H264编码）
│       ├── episode_000001.mp4
│       └── ...
├── data/
│   ├── chunk-000/
│   │   └── episode_000000.parquet   # 状态和动作数据
│   └── chunk-001/
│       └── episode_000001.parquet
└── audio/
    └── audio_0/
        ├── episode_0_audio.pkl      # 音频数据（Pickle格式）
        └── episode_1_audio.pkl
```

### 2.2 数据schema

#### 2.2.1 info.json
```json
{
  "codebase_version": "v2.0",
  "fps": 30,
  "robot_type": "SO101",
  "total_episodes": 5,
  "total_frames": 1500,
  "features": {
    "observation.images.left_wrist": {
      "dtype": "video",
      "shape": [480, 640, 3],
      "video_info": {
        "fps": 30,
        "codec": "h264",
        "pix_fmt": "yuv420p"
      }
    },
    "observation.state": {
      "dtype": "float32",
      "shape": [13],
      "names": ["state_0", "state_1", ...]
    },
    "action": {
      "dtype": "float32", 
      "shape": [13],
      "names": ["action_0", "action_1", ...]
    }
  }
}
```

#### 2.2.2 episodes.jsonl
```jsonl
{"episode_index": 0, "tasks": ["pick_and_place"], "length": 300, "created_at": "2025-12-17"}
{"episode_index": 1, "tasks": ["pick_and_place"], "length": 280, "created_at": "2025-12-17"}
```

#### 2.2.3 Parquet数据
每个parquet文件包含一个Episode的所有帧：

| index | episode_index | frame_index | timestamp | observation.state | action | next.done |
|-------|--------------|-------------|-----------|------------------|--------|-----------|
| 0     | 0            | 0           | 0.000     | [0.1, 0.2, ...]  | [0.15, ...] | False |
| 1     | 0            | 1           | 0.033     | [0.11, 0.21, ...] | [0.16, ...] | False |
| ...   | ...          | ...         | ...       | ...              | ...    | ...       |
| 299   | 0            | 299         | 9.967     | [0.5, 0.3, ...]  | [0.5, ...] | True |

---

## 3. 数据采集流程

### 3.1 实时采集流程图

```
                        B端 LeRobotDataHandler
                        ┌─────────────────────────────┐
                        │                             │
  C端发送数据           │  1. add_frame()             │
  ──────────────→       │  ┌─────────────────────┐   │
                        │  │ 动态检测相机       │   │
  {                     │  │ camera_keys =      │   │
    'image.left_wrist': │  │ ['left_wrist',     │   │
    'image.left':       │  │  'left', 'right']  │   │
    'image.right':      │  └──────┬──────────────┘   │
    'state': [...],     │         │                  │
    'action': [...],    │         ▼                  │
    'timestamp': t      │  2. 延迟初始化数据集      │
  }                     │  ┌─────────────────────┐   │
                        │  │ 首次创建数据集时    │   │
                        │  │ 根据相机列表动态    │   │
                        │  │ 构建features       │   │
                        │  └──────┬──────────────┘   │
                        │         │                  │
                        │         ▼                  │
                        │  3. 处理图像数据          │
                        │  ┌─────────────────────┐   │
                        │  │ JPEG → numpy array  │   │
                        │  │ BGR → RGB           │   │
                        │  └──────┬──────────────┘   │
                        │         │                  │
                        │         ▼                  │
                        │  4. 音频对齐              │
                        │  ┌─────────────────────┐   │
                        │  │ _align_audio()      │   │
                        │  │ 按时间戳收集音频    │   │
                        │  └──────┬──────────────┘   │
                        │         │                  │
                        │         ▼                  │
                        │  5. 添加帧到buffer        │
                        │  ┌─────────────────────┐   │
                        │  │ dataset.add_frame() │   │
                        │  └──────┬──────────────┘   │
                        │         │                  │
                        │         ▼                  │
                        │  6. 检查Episode结束       │
                        │  ┌─────────────────────┐   │
  episode_end=True →    │  │ episode_end?        │   │
                        │  └──────┬──────────────┘   │
                        │         │ Yes              │
                        │         ▼                  │
                        │  7. 保存Episode           │
                        │  ┌─────────────────────┐   │
                        │  │ save_episode()      │   │
                        │  │ - 写入parquet       │   │
                        │  │ - 编码视频(H264)    │   │
                        │  │ - 保存音频(pickle)  │   │
                        │  └─────────────────────┘   │
                        └─────────────────────────────┘
```

### 3.2 关键代码流程

#### 3.2.1 数据接收（B端：`thread_data_handler`）

```python
# 接收C端数据
raw_data = socket_from_c.recv()

# 解析pickle数据
data_dict = pickle.loads(raw_data)
# data_dict = {
#     'image.left_wrist': jpeg_bytes,
#     'image.left': jpeg_bytes,
#     'image.right': jpeg_bytes,
#     'state': [13个浮点数],
#     'action': [13个浮点数],
#     'timestamp': 1234567890.123,
#     'episode_end': False
# }

# 保存到LeRobot
lerobot_handler.add_frame(data_dict)

# 提取并转发视频给A
video_frame = {
    'image.left_wrist': jpeg_bytes,
    'image.left': jpeg_bytes,
    'image.right': jpeg_bytes,
    'encoding': 'jpeg'
}
socket_to_a.send(pickle.dumps(video_frame))
```

#### 3.2.2 帧处理（B端：`add_frame`）

```python
def add_frame(self, data_dict: dict):
    # 1. 动态检测相机
    camera_keys = [k.replace("image.", "") 
                   for k in data_dict.keys() 
                   if k.startswith("image.")]
    
    # 2. 延迟初始化（第一帧时）
    if self.dataset is None:
        features = {}
        for cam_name in camera_keys:
            features[f"observation.images.{cam_name}"] = {
                "dtype": "video",
                "shape": (480, 640, 3),
                "video_info": {"fps": 30, "codec": "h264"}
            }
        self.dataset = LeRobotDataset.create(
            repo_id=self.repo_id,
            features=features,
            ...
        )
    
    # 3. 解码图像
    frame_images = {}
    for cam_name in camera_keys:
        jpeg_bytes = data_dict[f'image.{cam_name}']
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8))
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        frame_images[f"observation.images.{cam_name}"] = img_rgb
    
    # 4. 对齐音频
    timestamp = data_dict['timestamp']
    frame_audio = self._align_audio(timestamp)
    self.episode_audio_data.append(frame_audio)
    
    # 5. 添加帧
    frame_data = {
        **frame_images,
        "observation.state": np.array(data_dict['state']),
        "action": np.array(data_dict['action']),
        "task": "teleoperation"
    }
    self.dataset.add_frame(frame_data)
    
    # 6. Episode结束处理
    if data_dict.get('episode_end'):
        self.dataset.save_episode()  # 保存parquet和视频
        
        # 单独保存音频
        ep_idx = self.dataset.meta.total_episodes - 1
        audio_path = Path(self.dataset.root) / f"audio/audio_0/episode_{ep_idx}_audio.pkl"
        with open(audio_path, 'wb') as f:
            pickle.dump(self.episode_audio_data, f)
```

---

## 4. 存储与加载流程

### 4.1 数据写入流程

```
add_frame() 循环调用
     │
     ▼
┌─────────────────────┐
│ episode_buffer累积  │  ← 内存中缓存帧数据
│ {                   │
│   frame_0: {...}    │
│   frame_1: {...}    │
│   ...               │
│ }                   │
└──────────┬──────────┘
           │
           │ episode_end = True
           ▼
    save_episode()
           │
    ┌──────┴──────────┐
    │                 │
    ▼                 ▼
写入parquet      编码视频
    │                 │
    │            ┌────┴────┐
    │            │ ffmpeg  │
    │            │ -c:v    │
    │            │ h264    │
    │            └────┬────┘
    │                 │
    ▼                 ▼
data/chunk-000/   videos/observation.images.left_wrist/
episode_0.parquet episode_000000.mp4
```

### 4.2 数据读取流程

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset

# 1. 加载数据集
dataset = LeRobotDataset("real_robot_data/12_13_test")

# 2. 获取一帧
frame = dataset[0]
# frame = {
#     'observation.images.left_wrist': Tensor[3, 480, 640],  # RGB
#     'observation.images.left': Tensor[3, 480, 640],
#     'observation.images.right': Tensor[3, 480, 640],
#     'observation.state': Tensor[13],
#     'action': Tensor[13],
#     'episode_index': 0,
#     'frame_index': 0,
#     'timestamp': 0.0
# }

# 3. 时序查询（获取多帧）
dataset.delta_timestamps = {
    "observation.images.left_wrist": [-1.0, -0.5, 0]  # 1秒前，0.5秒前，当前
}
frames = dataset[100]
# frames['observation.images.left_wrist'] 是 [3, 3, 480, 640] 的Tensor

# 4. 遍历Episode
for episode_idx in range(dataset.num_episodes):
    episode_data = dataset.get_episode(episode_idx)
    # episode_data包含该Episode的所有帧
```

### 4.3 视频编码细节

LeRobot使用 **H.264编码** 存储视频：

```python
# LeRobot内部调用（简化版）
import av

container = av.open(video_path, mode='w')
stream = container.add_stream('h264', rate=fps)
stream.width = 640
stream.height = 480
stream.pix_fmt = 'yuv420p'

for frame_rgb in episode_frames:
    frame = av.VideoFrame.from_ndarray(frame_rgb, format='rgb24')
    packet = stream.encode(frame)
    container.mux(packet)

container.close()
```

**优势：**
- 节省存储空间（JPEG序列 → H264视频，压缩率约10:1）
- 支持随机访问（通过时间戳索引）
- 标准格式，易于分享和训练

---

## 5. 与A端的集成方案

### 5.1 当前架构（A端不直接存储）

```
A端                    B端                    LeRobot数据集
┌─────────┐         ┌─────────┐           ┌─────────────┐
│ IMU读取 │─控制命令→│ 接收命令│           │             │
│         │         │ ↓转发C端│           │             │
│ 视频显示│←────────│ 接收C数据│─add_frame→│ 自动保存    │
│         │  视频   │ ↓解析   │           │ - Parquet   │
│ 音频播放│←────────│ ↓转发A端│           │ - Video     │
│         │  音频   └─────────┘           │ - Audio     │
└─────────┘                               └─────────────┘
```

### 5.2 可选方案：A端本地缓存

如果需要A端也保存数据（例如用于本地训练）：

```python
# full_project/core/data_recorder.py (新增)

class LocalDataRecorder:
    """
    A端本地数据记录器（可选）
    """
    def __init__(self, save_dir: Path):
        self.save_dir = save_dir
        self.current_episode = []
        
    def add_observation(self, imu_data, video_frames):
        """记录当前观测"""
        self.current_episode.append({
            'timestamp': time.time(),
            'imu': imu_data,
            'video': video_frames
        })
    
    def save_episode(self):
        """保存Episode到本地"""
        ep_path = self.save_dir / f"episode_{len(os.listdir(self.save_dir))}.pkl"
        with open(ep_path, 'wb') as f:
            pickle.dump(self.current_episode, f)
        self.current_episode = []
```

在 `main.py` 中集成：

```python
# main.py
class IMUArmController:
    def __init__(self):
        ...
        # 可选：启用本地记录
        if config.local_recording.enabled:
            self.recorder = LocalDataRecorder(
                Path(config.local_recording.save_dir)
            )
    
    def _publisher_loop(self):
        while self._running:
            # 读取IMU数据
            euler1, euler2, euler3 = self._read_imu_data()
            
            # 获取视频帧（如果需要）
            if hasattr(self, 'recorder'):
                video_frames = self.video.get_all_frames()
                self.recorder.add_observation(
                    imu_data={'euler1': euler1, 'euler2': euler2, 'euler3': euler3},
                    video_frames=video_frames
                )
            
            # 发送控制命令...
```

### 5.3 推荐架构：集中式存储

**推荐使用当前架构（B端统一存储）：**

✅ **优势：**
1. **数据一致性** - 所有数据（A的控制命令 + C的执行结果）统一在B端对齐
2. **时间同步** - B端作为中心节点，统一时间戳
3. **存储优化** - B端通常有更大存储空间
4. **网络友好** - A端可以是轻量级客户端

❌ **A端本地存储的缺点：**
1. 数据分散，难以对齐
2. A端可能是笔记本，存储有限
3. 增加A端开销

---

## 6. 完整示例

### 6.1 C端发送代码示例

```python
# C_端代码片段
import pickle
import zmq

context = zmq.Context()
socket = context.socket(zmq.PUSH)
socket.connect("tcp://B_SERVER_IP:5558")

# 采集一帧数据
frame_data = {
    'image.left_wrist': capture_camera('left_wrist'),  # JPEG bytes
    'image.left': capture_camera('left'),
    'image.right': capture_camera('right'),
    'state': get_robot_state(),  # [13个关节角度]
    'action': get_last_action(),  # [13个目标位置]
    'timestamp': time.time(),
    'episode_end': False  # 最后一帧设为True
}

socket.send(pickle.dumps(frame_data))
```

### 6.2 训练模型使用数据集

```python
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

# 加载数据集
dataset = LeRobotDataset("real_robot_data/12_13_test")

# 设置时序窗口
dataset.delta_timestamps = {
    "observation.images.left_wrist": [-0.1, 0],  # 当前帧和前一帧
    "observation.state": [-0.1, 0]
}

# 创建DataLoader
dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

# 训练循环
for batch in dataloader:
    images = batch['observation.images.left_wrist']  # [B, 2, C, H, W]
    states = batch['observation.state']              # [B, 2, 13]
    actions = batch['action']                        # [B, 13]
    
    # 喂给模型...
    predictions = model(images, states)
    loss = criterion(predictions, actions)
```

---

## 7. 总结

### 7.1 B端数据存储特点

| 特性 | 实现方式 |
|------|---------|
| **格式** | LeRobot标准格式（Parquet + MP4 + Pickle） |
| **多相机** | 动态检测 `image.*` 字段，自动适配 |
| **音频对齐** | 基于时间戳的音频包对齐机制 |
| **存储优化** | 视频H264编码，压缩率高 |
| **易用性** | 兼容HuggingFace生态，直接加载训练 |

### 7.2 数据流总结

```
A端发控制命令 → B端转发C → C执行 → C返回数据+视频+音频 → B端存储LeRobot格式 → A端接收视频音频显示
                                                             ↓
                                                      可直接用于训练
```

### 7.3 推荐工作流

1. **采集阶段** - C端实时采集并发送到B端
2. **存储阶段** - B端自动保存为LeRobot数据集
3. **训练阶段** - 直接加载LeRobot数据集训练策略
4. **部署阶段** - 训练好的模型替换A端控制逻辑

---

**文档版本**: v1.0  
**更新日期**: 2025-12-18  
**作者**: GitHub Copilot
