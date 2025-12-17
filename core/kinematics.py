#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机械臂运动学计算模块

计算两杆串联机械臂的末端位置
支持坐标映射和约束
"""

import numpy as np
from scipy.spatial.transform import Rotation
from dataclasses import dataclass
from typing import Tuple, List
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_config


@dataclass
class Position:
    """3D位置"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    
    def to_list(self) -> List[float]:
        return [self.x, self.y, self.z]
    
    def to_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


class Kinematics:
    """
    机械臂运动学计算器
    
    计算两杆串联机械臂的末端位置，并进行坐标映射
    
    Usage:
        kin = Kinematics()
        
        # 计算末端位置
        end_pos, link1_pos, link2_pos = kin.calculate_end_effector(euler1, euler2)
        
        # 坐标映射
        mapped = kin.map_position(end_pos)
    """
    
    def __init__(self,
                 link1_length: float = None,
                 link2_length: float = None,
                 config = None):
        """
        初始化运动学计算器
        
        Args:
            link1_length: 杆1长度（米），None则从配置读取
            link2_length: 杆2长度（米），None则从配置读取
            config: 配置对象，None则使用默认配置
        """
        cfg = config or get_config()
        
        self.L1 = link1_length or cfg.arm.link1_length
        self.L2 = link2_length or cfg.arm.link2_length
        
        # 工作空间范围
        ws_raw = cfg.coordinate_mapping.raw
        ws_target = cfg.coordinate_mapping.target
        
        self.raw_min = Position(ws_raw.x_min, ws_raw.y_min, ws_raw.z_min)
        self.raw_max = Position(ws_raw.x_max, ws_raw.y_max, ws_raw.z_max)
        self.target_min = Position(ws_target.x_min, ws_target.y_min, ws_target.z_min)
        self.target_max = Position(ws_target.x_max, ws_target.y_max, ws_target.z_max)
    
    def calculate_end_effector(self, 
                                euler1: dict, 
                                euler2: dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        计算两杆串联机械臂的末端位置
        
        使用欧拉角（XYZ顺序）构建旋转矩阵，计算末端位置
        
        公式:
            末端位置 = R1 @ [L1, 0, 0]^T + R2 @ [L2, 0, 0]^T
        
        Args:
            euler1: IMU1的欧拉角 {"roll": ..., "pitch": ..., "yaw": ...} (度)
            euler2: IMU2的欧拉角 {"roll": ..., "pitch": ..., "yaw": ...} (度)
        
        Returns:
            end_pos: 末端位置 [x, y, z]（米）
            link1_pos: 杆1末端位置 [x, y, z]（米）
            link2_pos: 杆2末端位置 [x, y, z]（米）
        """
        # 转换为弧度
        roll1_rad = np.deg2rad(euler1.get("roll", 0.0))
        pitch1_rad = np.deg2rad(euler1.get("pitch", 0.0))
        yaw1_rad = np.deg2rad(euler1.get("yaw", 0.0))
        
        roll2_rad = np.deg2rad(euler2.get("roll", 0.0))
        pitch2_rad = np.deg2rad(euler2.get("pitch", 0.0))
        yaw2_rad = np.deg2rad(euler2.get("yaw", 0.0))
        
        # 构建旋转矩阵（XYZ欧拉角顺序）
        R1 = Rotation.from_euler('xyz', [roll1_rad, pitch1_rad, yaw1_rad]).as_matrix()
        R2 = Rotation.from_euler('xyz', [roll2_rad, pitch2_rad, yaw2_rad]).as_matrix()
        
        # 杆在局部坐标系下的向量（沿x轴）
        link1_local = np.array([self.L1, 0.0, 0.0])
        link2_local = np.array([self.L2, 0.0, 0.0])
        
        # 转换到世界坐标系
        link1_world = R1 @ link1_local
        link2_world = R2 @ link2_local
        
        # 末端位置 = 杆1末端 + 杆2末端
        end_pos = link1_world + link2_world
        
        return end_pos, link1_world, link2_world
    
    def clip_position(self, pos: np.ndarray) -> np.ndarray:
        """
        将位置裁剪到原始工作空间范围内
        
        Args:
            pos: 原始位置 [x, y, z]
        
        Returns:
            裁剪后的位置 [x, y, z]
        """
        return np.array([
            np.clip(pos[0], self.raw_min.x, self.raw_max.x),
            np.clip(pos[1], self.raw_min.y, self.raw_max.y),
            np.clip(pos[2], self.raw_min.z, self.raw_max.z)
        ])
    
    def map_position(self, pos: np.ndarray) -> np.ndarray:
        """
        将位置从原始空间映射到目标空间
        
        先裁剪到原始范围，再线性映射到目标范围
        
        Args:
            pos: 原始位置 [x, y, z]
        
        Returns:
            映射后的位置 [x, y, z]
        """
        # 先裁剪
        clipped = self.clip_position(pos)
        
        # 线性映射
        def linear_map(val, src_min, src_max, dst_min, dst_max):
            if src_max == src_min:
                return dst_min
            return dst_min + (val - src_min) / (src_max - src_min) * (dst_max - dst_min)
        
        return np.array([
            linear_map(clipped[0], self.raw_min.x, self.raw_max.x, 
                      self.target_min.x, self.target_max.x),
            linear_map(clipped[1], self.raw_min.y, self.raw_max.y,
                      self.target_min.y, self.target_max.y),
            linear_map(clipped[2], self.raw_min.z, self.raw_max.z,
                      self.target_min.z, self.target_max.z)
        ])
    
    def map_position_with_gripper(self, pos: np.ndarray, base_angle: float, 
                                   gripper: float) -> List[float]:
        """
        映射位置并附加底座角度和夹爪值
        
        Args:
            pos: 末端位置 [x, y, z]
            base_angle: 底座旋转角度（度）
            gripper: 夹爪开合度 [0, 1]
            
        Returns:
            List[x, y, z, base, gripper]: 映射后的完整状态
        """
        mapped = self.map_position(pos)
        return [mapped[0], mapped[1], mapped[2], base_angle, gripper]
    
    def calculate_shoulder_pan(self, pos: np.ndarray) -> float:
        """
        计算肩部转角（shoulder_pan）
        
        末端在XY平面投影相对于X轴的角度
        
        Args:
            pos: 位置 [x, y, z]
        
        Returns:
            角度（弧度）
        """
        return np.arctan2(pos[1], pos[0])


if __name__ == "__main__":
    # 测试运动学计算
    print("=== 运动学计算测试 ===\n")
    
    kin = Kinematics()
    
    # 测试数据
    euler1 = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    euler2 = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    
    end_pos, link1, link2 = kin.calculate_end_effector(euler1, euler2)
    mapped = kin.map_position(end_pos)
    shoulder = kin.calculate_shoulder_pan(end_pos)
    
    print(f"杆1长度: {kin.L1 * 1000:.0f} mm")
    print(f"杆2长度: {kin.L2 * 1000:.0f} mm")
    print(f"\n输入欧拉角:")
    print(f"  IMU1: Roll={euler1['roll']:.1f}° Pitch={euler1['pitch']:.1f}° Yaw={euler1['yaw']:.1f}°")
    print(f"  IMU2: Roll={euler2['roll']:.1f}° Pitch={euler2['pitch']:.1f}° Yaw={euler2['yaw']:.1f}°")
    print(f"\n计算结果:")
    print(f"  杆1末端: [{link1[0]:.3f}, {link1[1]:.3f}, {link1[2]:.3f}] m")
    print(f"  杆2末端: [{link2[0]:.3f}, {link2[1]:.3f}, {link2[2]:.3f}] m")
    print(f"  末端位置: [{end_pos[0]:.3f}, {end_pos[1]:.3f}, {end_pos[2]:.3f}] m")
    print(f"  映射位置: [{mapped[0]:.3f}, {mapped[1]:.3f}, {mapped[2]:.3f}] m")
    print(f"  肩部转角: {np.rad2deg(shoulder):.2f}°")
