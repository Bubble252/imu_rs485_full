# -*- coding: utf-8 -*-
"""
音频接收和播放模块 (与 triple 保持一致)

负责:
- 接收Opus编码的音频流
- 解码和播放音频 (使用sounddevice，与triple一致)
- 音频波形数据提取 (用于UI显示)
- 缓冲队列平滑网络抖动

参考: triple_imu_rs485_publisher_dual_cam_UI_voice.py
"""

import threading
import time
import pickle
import queue
import numpy as np
from typing import Optional, Callable
from collections import deque

# 音频播放库 (与triple使用相同的库)
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("[Audio] Warning: sounddevice不可用，音频播放将被禁用")
    print("[Audio] 安装方法: pip install sounddevice")

# Opus解码库
try:
    import opuslib
    OPUS_AVAILABLE = True
except ImportError:
    OPUS_AVAILABLE = False
    print("[Audio] Warning: opuslib不可用，音频功能将被禁用")
    print("[Audio] 安装方法: pip install opuslib")

# 音频功能总开关
AUDIO_ENABLED = SOUNDDEVICE_AVAILABLE and OPUS_AVAILABLE

from config import config


class AudioReceiver:
    """
    音频接收和播放类 (与triple架构一致)
    
    架构:
    - 接收线程: 从ZMQ接收数据，放入缓冲队列
    - 播放线程: 从队列取数据，解码并播放
    - 缓冲队列: 平滑网络抖动
    
    功能:
    - 从ZMQ接收Opus编码的音频数据
    - 解码为PCM数据
    - 通过sounddevice播放 (与triple一致)
    - 提供波形数据给UI显示
    
    Usage:
        receiver = AudioReceiver()
        receiver.start()
        
        # 获取波形数据 (用于UI)
        waveform = receiver.get_waveform()
        
        receiver.stop()
    """
    
    # 音频参数 (与triple和C端完全一致)
    SAMPLE_RATE = 48000           # 48kHz 采样率
    CHANNELS = 1                   # 单声道
    FRAME_SIZE = 2880              # Opus帧大小 (60ms @ 48kHz)
    BUFFER_SIZE = 5                # 缓冲队列大小（帧数），用于平滑网络抖动
    
    def __init__(self):
        """初始化音频接收器"""
        self._running = False
        self._muted = False
        
        # 解码器
        self._decoder = None
        if OPUS_AVAILABLE:
            try:
                self._decoder = opuslib.Decoder(self.SAMPLE_RATE, self.CHANNELS)
                print(f"[Audio] ✓ Opus解码器已创建 (采样率: {self.SAMPLE_RATE}Hz)")
            except Exception as e:
                print(f"[Audio] ❌ Opus解码器创建失败: {e}")
        
        # 音频输出流 (sounddevice)
        self._stream = None
        if SOUNDDEVICE_AVAILABLE:
            try:
                self._stream = sd.OutputStream(
                    samplerate=self.SAMPLE_RATE,
                    channels=self.CHANNELS,
                    dtype='int16',
                    blocksize=self.FRAME_SIZE,
                )
                print(f"[Audio] ✓ 音频输出流已创建 (帧大小: {self.FRAME_SIZE})")
            except Exception as e:
                print(f"[Audio] ❌ 音频流创建失败: {e}")
        
        # 缓冲队列 (与triple一致)
        self._buffer_queue = queue.Queue(maxsize=self.BUFFER_SIZE)
        
        # 波形缓冲 (保存最近1秒数据，用于UI显示)
        self._waveform_buffer = deque(maxlen=self.SAMPLE_RATE)
        self._waveform_lock = threading.Lock()
        
        # 最新波形样本 (256个，用于UI显示)
        self._latest_waveform = None
        self._latest_rms = 0.0
        
        # 播放线程
        self._play_thread: Optional[threading.Thread] = None
        
        # 统计
        self._frames_received = 0
        self._frames_played = 0
        self._frames_dropped = 0
        self._underrun_count = 0
    
    def process_data(self, raw_data: bytes):
        """
        处理接收到的音频数据 (放入缓冲队列)
        
        支持两种格式 (与triple一致):
        1. Pickle dict格式 (来自C/B端): pickle.dumps({'data': opus_bytes, 'codec': 'opus', ...})
        2. 原始Opus字节 (旧格式): 直接是opus编码的bytes
        
        Args:
            raw_data: 接收到的原始字节数据
        """
        if not AUDIO_ENABLED:
            return
        
        self._frames_received += 1
        
        try:
            opus_data = None
            
            # 首先尝试pickle格式 (C/B端发送的格式)
            try:
                audio_dict = pickle.loads(raw_data)
                if isinstance(audio_dict, dict) and 'data' in audio_dict:
                    opus_data = audio_dict['data']
            except (pickle.UnpicklingError, TypeError, KeyError):
                # 不是pickle格式，假设是原始Opus数据
                opus_data = raw_data
            
            if not opus_data or not isinstance(opus_data, bytes) or len(opus_data) == 0:
                return
            
            # 放入缓冲队列 (非阻塞)
            try:
                self._buffer_queue.put_nowait(opus_data)
            except queue.Full:
                # 队列满，丢弃最旧的帧
                try:
                    self._buffer_queue.get_nowait()
                    self._buffer_queue.put_nowait(opus_data)
                    self._frames_dropped += 1
                except:
                    pass
                    
        except Exception as e:
            if self._frames_received % 100 == 0:
                print(f"[Audio] 处理音频数据失败: {e}")
    
    def _playback_loop(self):
        """
        音频播放循环 (与triple的audio_player_thread一致)
        
        从缓冲队列取数据，解码并播放
        """
        if not AUDIO_ENABLED or not self._decoder or not self._stream:
            print("[Audio] ⚠️ 音频功能未启用，播放线程退出")
            return
        
        print(f"[Audio] 🔊 播放线程启动")
        print(f"[Audio]    采样率: {self.SAMPLE_RATE} Hz")
        print(f"[Audio]    声道: {self.CHANNELS}")
        print(f"[Audio]    帧大小: {self.FRAME_SIZE} 样本 ({self.FRAME_SIZE/self.SAMPLE_RATE*1000:.0f}ms)")
        print(f"[Audio]    缓冲: {self.BUFFER_SIZE} 帧")
        
        # 启动音频流
        try:
            self._stream.start()
        except Exception as e:
            print(f"[Audio] ❌ 音频流启动失败: {e}")
            return
        
        while self._running:
            try:
                # 从队列获取Opus编码数据（阻塞，1秒超时）
                opus_bytes = self._buffer_queue.get(timeout=1.0)
                
                # Opus解码
                pcm_data = self._decoder.decode(opus_bytes, self.FRAME_SIZE)
                
                # 转换为numpy array
                audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                
                # 播放音频 (如果未静音)
                if not self._muted:
                    self._stream.write(audio_array)
                
                self._frames_played += 1
                
                # 更新波形数据 (用于UI显示)
                self._update_waveform(audio_array)
                
            except queue.Empty:
                # 队列空，播放静音 (防止underrun)
                self._underrun_count += 1
                continue
            except Exception as e:
                if self._frames_played % 100 == 0:
                    print(f"[Audio] 播放异常: {e}")
                time.sleep(0.01)
        
        # 停止音频流
        try:
            self._stream.stop()
        except:
            pass
        
        print(f"[Audio] 播放线程退出，已播放 {self._frames_played} 帧")
    
    def _update_waveform(self, audio_array: np.ndarray):
        """更新波形数据 (用于UI显示)"""
        try:
            # 采样：取256个样本用于显示
            sample_step = max(1, len(audio_array) // 256)
            waveform_samples = audio_array[::sample_step][:256]
            
            # 计算RMS音量
            rms = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
            normalized_rms = min(1.0, rms / 32768.0 * 10)  # 放大10倍便于显示
            
            with self._waveform_lock:
                self._latest_waveform = waveform_samples.copy()
                self._latest_rms = normalized_rms
                self._waveform_buffer.extend(audio_array.tolist())
        except:
            pass
    
    def get_waveform(self, length: int = 256) -> np.ndarray:
        """
        获取波形数据 (用于UI显示)
        
        Args:
            length: 返回的采样点数量
            
        Returns:
            np.ndarray: 标准化到[-1, 1]的波形数据
        """
        with self._waveform_lock:
            if self._latest_waveform is not None:
                data = self._latest_waveform.astype(float) / 32768.0
                if len(data) < length:
                    data = np.pad(data, (0, length - len(data)), mode='constant')
                return data[:length]
            else:
                return np.zeros(length)
    
    def get_rms(self) -> float:
        """获取当前音量RMS值 (0.0-1.0)"""
        with self._waveform_lock:
            return self._latest_rms
    
    def set_mute(self, muted: bool):
        """设置静音状态"""
        self._muted = muted
        print(f"[Audio] 静音: {muted}")
    
    def toggle_mute(self) -> bool:
        """切换静音状态，返回新状态"""
        self._muted = not self._muted
        print(f"[Audio] 静音: {self._muted}")
        return self._muted
    
    @property
    def is_muted(self) -> bool:
        """是否静音"""
        return self._muted
    
    def start(self):
        """启动音频接收器"""
        if self._running:
            return
        
        self._running = True
        
        # 启动播放线程
        if AUDIO_ENABLED:
            self._play_thread = threading.Thread(
                target=self._playback_loop,
                daemon=True,
                name="AudioPlayer"
            )
            self._play_thread.start()
        
        print("[Audio] ✓ 音频接收器已启动")
    
    def stop(self):
        """停止音频接收器"""
        self._running = False
        
        # 等待播放线程结束
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=2.0)
        
        # 关闭音频流
        if self._stream:
            try:
                self._stream.close()
            except:
                pass
        
        print(f"[Audio] 已停止")
        print(f"[Audio]   接收帧: {self._frames_received}")
        print(f"[Audio]   播放帧: {self._frames_played}")
        print(f"[Audio]   丢弃帧: {self._frames_dropped}")
        print(f"[Audio]   下溢次数: {self._underrun_count}")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'frames_received': self._frames_received,
            'frames_played': self._frames_played,
            'frames_dropped': self._frames_dropped,
            'underrun_count': self._underrun_count,
            'queue_size': self._buffer_queue.qsize(),
            'is_muted': self._muted,
            'decoder_available': self._decoder is not None,
            'player_available': self._stream is not None,
            'rms': self._latest_rms,
        }
