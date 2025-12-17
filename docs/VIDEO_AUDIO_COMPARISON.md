# Full Project 与 Triple 文件的视频/音频接收对比

> 创建日期: 2024-12-12

---

## ❓ 核心问题回答

### Q1: full_project 的 A 端能正确收到视频和音频吗？

**⚠️ 视频: 不能直接兼容，需要修复！**

| 对比项 | Triple 文件 | Full Project | 兼容性 |
|--------|-------------|--------------|--------|
| 视频数据格式 | `pickle.loads()` → dict → `frame_dict['image.left_wrist']` | `struct.unpack` 解析长度前缀 | ❌ 不兼容 |
| 期望输入 | pickle 序列化的 dict | 4字节长度 + JPEG + 4字节长度 + JPEG | ❌ 格式不同 |

**🔊 音频: 兼容！**

| 对比项 | Triple 文件 | Full Project | 兼容性 |
|--------|-------------|--------------|--------|
| 音频数据格式 | 原始 Opus bytes | 原始 Opus bytes | ✅ 相同 |
| 解码器 | opuslib.Decoder | opuslib.Decoder | ✅ 相同 |
| 播放器 | pyaudio | pyaudio | ✅ 相同 |

### Q2: 音频和视频接收是单开线程吗？

**✅ 是的，两者都是单开线程！**

| 对比项 | Triple 文件 | Full Project |
|--------|-------------|--------------|
| 视频接收线程 | `video_thread = threading.Thread(target=video_receiver_thread, ...)` | `_video_thread = threading.Thread(target=self._video_receiver_loop, ...)` |
| 音频接收线程 | `audio_receiver_thread_obj = threading.Thread(target=audio_receiver_thread, ...)` | `_audio_thread = threading.Thread(target=self._audio_receiver_loop, ...)` |
| 线程名称 | "VideoReceiver", "AudioReceiver" | "VideoReceiver", "AudioReceiver" |
| 后台运行 | `daemon=True` | `daemon=True` |

---

## 📊 详细架构对比

### 1. 端口配置（完全相同）

```
┌─────────────────────────────────────────────────────────────┐
│                    端口架构 (Triple = Full Project)          │
├─────────┬────────────┬──────────┬──────────────────────────┤
│ 端口    │ Socket类型 │ 方向     │ 用途                      │
├─────────┼────────────┼──────────┼──────────────────────────┤
│ 5555    │ PUSH       │ A → B    │ 控制数据发送              │
│ 5557    │ SUB        │ B → A    │ 视频流接收                │
│ 5559    │ PUSH       │ A → LeR  │ LeRobot数据               │
│ 5560    │ PUB        │ A → UI   │ 调试UI数据                │
│ 5561    │ SUB        │ B → A    │ 音频流接收                │
│ 5562    │ PULL       │ UI → A   │ UI命令接收                │
└─────────┴────────────┴──────────┴──────────────────────────┘
```

### 2. 线程架构对比

#### Triple 文件的线程（内联在一个文件）

```python
# triple_imu_rs485_publisher_dual_cam_UI_voice.py 中的线程

# 视频接收线程 (行 1859)
video_thread = threading.Thread(
    target=video_receiver_thread,
    args=(video_host, video_port),
    daemon=True,
    name="VideoReceiver"
)
video_thread.start()

# 音频接收线程 (行 1841)
audio_receiver_thread_obj = threading.Thread(
    target=audio_receiver_thread,
    args=(audio_host, audio_port),
    daemon=True,
    name="AudioReceiver"
)
audio_receiver_thread_obj.start()
```

#### Full Project 的线程（模块化）

```python
# full_project/main.py 中的线程 (行 182-197)

# 视频接收线程
self._video_thread = threading.Thread(
    target=self._video_receiver_loop,
    daemon=True,
    name="VideoReceiver"
)
self._video_thread.start()

# 音频接收线程
self._audio_thread = threading.Thread(
    target=self._audio_receiver_loop,
    daemon=True,
    name="AudioReceiver"
)
self._audio_thread.start()
```

**结论: 线程架构完全一致！**

---

## ⚠️ 关键兼容性问题：视频数据格式

### B 端发送的视频格式 (B_reverse_whole_voice.py)

```python
# B 端发送给 A 的视频数据格式
video_frame = {
    "image.left_wrist": jpeg_bytes_1,   # JPEG 编码的 bytes
    "image.top": jpeg_bytes_2,           # JPEG 编码的 bytes
    "encoding": "jpeg",
    "timestamp": 1702368000.123,
    "resolution": "640x480",
    "frame_count": 42
}

# 序列化并发送
socket_to_a.send(pickle.dumps(video_frame))  # ← pickle 格式！
```

### Triple 如何接收视频（正确方式）

```python
# triple_imu_rs485_publisher_dual_cam_UI_voice.py 中的视频接收
video_data = video_socket.recv()

# 先尝试 pickle 反序列化
try:
    frame_dict = pickle.loads(video_data)  # ← 先 pickle
except:
    frame_dict = json.loads(video_data.decode('utf-8'))  # ← 回退 JSON

# 提取 JPEG 数据
encoded_data_left = frame_dict['image.left_wrist']   # bytes
encoded_data_top = frame_dict['image.top']           # bytes

# 解码 JPEG
frame_left = cv2.imdecode(np.frombuffer(encoded_data_left, np.uint8), cv2.IMREAD_COLOR)
frame_top = cv2.imdecode(np.frombuffer(encoded_data_top, np.uint8), cv2.IMREAD_COLOR)
```

### Full Project 当前如何接收视频（有问题！）

```python
# full_project/core/video.py 中的 process_data()
def process_data(self, data: bytes):
    # ❌ 直接按长度前缀解析，没有先 pickle.loads()！
    frame1_size = struct.unpack('<I', data[0:4])[0]  # 期望 4 字节长度前缀
    frame1_data = data[4:4 + frame1_size]
    # ...
```

**问题: Full Project 期望的是 `[4字节长度][JPEG][4字节长度][JPEG]` 格式，但 B 端发送的是 `pickle.dumps(dict)` 格式！**

---

## 🔧 修复方案

需要修改 `full_project/core/video.py` 的 `process_data()` 方法，使其兼容 B 端发送的 pickle dict 格式：

```python
def process_data(self, data: bytes):
    """
    处理接收到的视频数据
    
    支持两种格式:
    1. pickle dict 格式 (B_reverse_whole_voice.py 发送)
    2. 长度前缀格式 (备用)
    """
    if not CV2_AVAILABLE:
        return
    
    try:
        # 方式1: 尝试 pickle 反序列化 (B 端发送的格式)
        try:
            frame_dict = pickle.loads(data)
            if isinstance(frame_dict, dict):
                # 提取双摄像头 JPEG 数据
                jpeg_left = frame_dict.get('image.left_wrist')
                jpeg_top = frame_dict.get('image.top')
                
                if jpeg_left and jpeg_top:
                    frame1 = self._decode_jpeg(jpeg_left)
                    frame2 = self._decode_jpeg(jpeg_top)
                    
                    if frame1 is not None and frame2 is not None:
                        with self._frame_lock:
                            self._frame1 = frame1
                            self._frame2 = frame2
                        
                        self._fps_window.append(time.time())
                        self._frames_received += 1
                        self._last_frame_time = time.time()
                        
                        if self._frame_callback:
                            self._frame_callback(frame1, frame2)
                    return
        except:
            pass  # 不是 pickle 格式，尝试其他方式
        
        # 方式2: 长度前缀格式 (备用)
        if len(data) < 8:
            return
        
        frame1_size = struct.unpack('<I', data[0:4])[0]
        # ... 原有代码 ...
```

---

## 📋 完整对比表

| 功能 | Triple 文件 | Full Project | 状态 |
|------|-------------|--------------|------|
| **视频接收** ||||
| 端口 | 5557 (SUB) | 5557 (SUB) | ✅ 相同 |
| 独立线程 | ✅ video_thread | ✅ _video_thread | ✅ 相同 |
| 数据格式解析 | pickle → dict → JPEG | struct 长度前缀 | ❌ **需修复** |
| OpenCV 显示 | ✅ cv2.imshow | ❌ 不显示 | 功能差异 |
| **音频接收** ||||
| 端口 | 5561 (SUB) | 5561 (SUB) | ✅ 相同 |
| 独立线程 | ✅ audio_receiver_thread | ✅ _audio_thread | ✅ 相同 |
| 数据格式 | Opus bytes | Opus bytes | ✅ 相同 |
| 解码器 | opuslib.Decoder | opuslib.Decoder | ✅ 相同 |
| 播放器 | pyaudio | pyaudio | ✅ 相同 |
| **ZMQ 连接** ||||
| 控制发送 | PUSH → 5555 | PUSH → 5555 | ✅ 相同 |
| 调试发布 | PUB bind 5560 | PUB bind 5560 | ✅ 相同 |
| 序列化格式 | pickle | pickle | ✅ 相同 |

---

## 🎯 结论与建议

### 当前状态

1. **音频接收**: ✅ 可以正常工作
   - 端口、格式、解码器都兼容
   - 需要安装 `opuslib` 和 `pyaudio`

2. **视频接收**: ❌ 需要修复
   - 端口正确
   - 数据格式解析不兼容
   - **需要修改 `video.py` 支持 pickle dict 格式**

### 下一步行动

运行以下命令让我修复视频接收：

```bash
# 我会修改 full_project/core/video.py
# 使其兼容 B 端发送的 pickle dict 格式
```

---

## 🔗 相关文件

| 文件 | 用途 |
|------|------|
| `full_project/main.py` | 主程序，启动视频/音频线程 |
| `full_project/core/video.py` | 视频接收和解码 (需修复) |
| `full_project/core/audio.py` | 音频接收和播放 |
| `full_project/core/zmq_manager.py` | ZMQ 连接管理 |
| `whole3_2/B_reverse_whole_voice.py` | B 端视频/音频转发 |
| `triple_imu_rs485_publisher_dual_cam_UI_voice.py` | 原始 Triple 文件参考 |
