"""
航迹管理 - 目标航迹的存储、分段和插值
"""
import math
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import deque

from models import TargetState, GeoPosition, MotionFeatures, TargetAttributes


class TargetTrack:
    """目标航迹（支持自动分段和平滑）"""

    SEGMENT_GAP_THRESHOLD = timedelta(minutes=2)  # 分段阈值

    def __init__(self, target_id: str, target_name: str, attributes: TargetAttributes):
        self.target_id = target_id
        self.target_name = target_name
        self.attributes = attributes
        self.segments: List[List[TargetState]] = []  # 分段航迹
        self.current_segment: List[TargetState] = []  # 当前正在构建的段
        self.motion_features: List[MotionFeatures] = []  # 运动特征序列

    def add_state(self, state: TargetState):
        """
        添加状态点，自动处理时间分段

        如果时间间隔超过阈值，自动创建新段
        """
        if not self.current_segment:
            self.current_segment.append(state)
            return

        last_state = self.current_segment[-1]
        time_gap = state.timestamp - last_state.timestamp

        if time_gap > self.SEGMENT_GAP_THRESHOLD:
            # 时间间隔过大，保存当前段并开始新段
            if len(self.current_segment) > 1:
                self.segments.append(self.current_segment.copy())
                self._compute_segment_features(self.current_segment)
            self.current_segment = [state]
        else:
            self.current_segment.append(state)

    def finalize(self):
        """完成航迹构建"""
        if len(self.current_segment) > 1:
            self.segments.append(self.current_segment.copy())
            self._compute_segment_features(self.current_segment)
        self.current_segment = []

    def _compute_segment_features(self, segment: List[TargetState]):
        """计算航段的运动特征"""
        for i in range(len(segment)):
            mf = MotionFeatures()

            # 需要前后点才能计算动态特征
            if i > 0 and i < len(segment) - 1:
                prev, curr, next_s = segment[i - 1], segment[i], segment[i + 1]

                dt1 = (curr.timestamp - prev.timestamp).total_seconds()
                dt2 = (next_s.timestamp - curr.timestamp).total_seconds()

                if dt1 > 0 and dt2 > 0:
                    # 计算速度
                    speed1 = curr.position.distance_to(prev) / dt1
                    speed2 = next_s.position.distance_to(curr) / dt2

                    # 加速度
                    mf.acceleration = (speed2 - speed1) / ((dt1 + dt2) / 2)

                    # 转弯率
                    heading1 = math.atan2(curr.position.y - prev.position.y,
                                          curr.position.x - prev.position.x)
                    heading2 = math.atan2(next_s.position.y - curr.position.y,
                                          next_s.position.x - curr.position.x)
                    heading_change = math.degrees(heading2 - heading1)
                    heading_change = (heading_change + 180) % 360 - 180
                    mf.turn_rate = heading_change / ((dt1 + dt2) / 2)

                    # 爬升率
                    mf.climb_rate = (next_s.position.altitude - curr.position.altitude) / dt2

                    # 机动检测
                    mf.is_maneuvering = abs(mf.turn_rate) > 5 or abs(mf.acceleration) > 2

            self.motion_features.append(mf)

    def interpolate(self, target_time: datetime) -> Optional[TargetState]:
        """
        线性插值获取指定时刻的状态

        如果目标时刻在航迹范围外，返回None
        """
        # 收集所有状态点
        all_states = []
        for seg in self.segments:
            all_states.extend(seg)

        if not all_states:
            return None

        # 查找前后最近点
        before = None
        after = None

        for state in all_states:
            if state.timestamp <= target_time:
                if before is None or state.timestamp > before.timestamp:
                    before = state
            if state.timestamp >= target_time:
                if after is None or state.timestamp < after.timestamp:
                    after = state

        # 边界情况
        if before is None:
            return after
        if after is None:
            return before
        if before == after:
            return before

        # 线性插值
        total_dt = (after.timestamp - before.timestamp).total_seconds()
        elapsed = (target_time - before.timestamp).total_seconds()
        ratio = elapsed / total_dt if total_dt > 0 else 0

        # 位置插值
        lon = before.position.longitude + (after.position.longitude - before.position.longitude) * ratio
        lat = before.position.latitude + (after.position.latitude - before.position.latitude) * ratio
        alt = before.position.altitude + (after.position.altitude - before.position.altitude) * ratio

        # 航向插值（处理0/360环绕）
        heading_diff = (after.heading - before.heading + 180) % 360 - 180
        heading = (before.heading + heading_diff * ratio) % 360

        # 速度插值
        speed = before.speed + (after.speed - before.speed) * ratio

        return TargetState(
            timestamp=target_time,
            position=GeoPosition(lon, lat, alt),
            heading=heading,
            speed=speed
        )

    def get_states_in_range(self, start: datetime, end: datetime) -> List[TargetState]:
        """获取指定时间范围内的所有状态"""
        result = []
        for seg in self.segments:
            for s in seg:
                if start <= s.timestamp <= end:
                    result.append(s)
        return result

    def get_duration(self) -> float:
        """获取航迹总持续时间（秒）"""
        total = 0.0
        for seg in self.segments:
            if len(seg) >= 2:
                total += (seg[-1].timestamp - seg[0].timestamp).total_seconds()
        return total

    def get_state_count(self) -> int:
        """获取状态点总数"""
        return sum(len(seg) for seg in self.segments)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'target_id': self.target_id,
            'target_name': self.target_name,
            'attributes': self.attributes.to_dict(),
            'segment_count': len(self.segments),
            'total_states': self.get_state_count(),
            'duration_seconds': self.get_duration(),
            'segments': [
                {
                    'start': seg[0].timestamp.isoformat(),
                    'end': seg[-1].timestamp.isoformat(),
                    'state_count': len(seg)
                }
                for seg in self.segments
            ]
        }