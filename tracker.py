"""
航迹管理 - 目标航迹的存储、分段和插值（集成Redis缓存）
"""
import math
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import deque

from models import TargetState, GeoPosition, MotionFeatures, TargetAttributes

logger = logging.getLogger(__name__)


class TargetTrack:
    """目标航迹（支持自动分段、平滑和Redis缓存）"""

    SEGMENT_GAP_THRESHOLD = timedelta(minutes=2)  # 分段阈值

    # 缓存同步开关（类级别，可通过配置关闭）
    ENABLE_CACHE_SYNC = True

    def __init__(self, target_id: str, target_name: str, attributes: TargetAttributes):
        self.target_id = target_id
        self.target_name = target_name
        self.attributes = attributes
        self.segments: List[List[TargetState]] = []  # 分段航迹
        self.current_segment: List[TargetState] = []  # 当前正在构建的段
        self.motion_features: List[MotionFeatures] = []  # 运动特征序列

        # 缓存相关
        self._cache_initialized = False
        self._last_cache_version = 0

    def add_state(self, state: TargetState, sync_to_cache: bool = True):
        """
        添加状态点，自动处理时间分段和Redis缓存

        Args:
            state: 目标状态
            sync_to_cache: 是否同步到Redis（默认True）
        """
        # 处理时间分段
        if not self.current_segment:
            self.current_segment.append(state)
        else:
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

        # 同步到Redis缓存（异步，不阻塞主流程）
        if sync_to_cache and self.ENABLE_CACHE_SYNC:
            self._sync_to_cache(state)

    def _sync_to_cache(self, state: TargetState):
        """同步状态到Redis缓存"""
        try:
            # 延迟导入，避免循环依赖
            from cache.target_cache import target_cache

            # 更新缓存，获取增量信息
            success, is_update, delta = target_cache.cache_target_state(
                self.target_id,
                state,
                emit_delta=True
            )

            if success and is_update:
                self._last_cache_version = target_cache.get_target_version(self.target_id)
                logger.debug(f"目标 [{self.target_id}] 缓存同步成功，版本: {self._last_cache_version}")

        except Exception as e:
            # 缓存失败不影响主流程
            logger.warning(f"目标 [{self.target_id}] 缓存同步失败: {e}")

    def finalize(self, sync_to_cache: bool = True):
        """完成航迹构建"""
        if len(self.current_segment) > 1:
            self.segments.append(self.current_segment.copy())
            self._compute_segment_features(self.current_segment)

            # 同步最后状态到缓存
            if sync_to_cache and self.ENABLE_CACHE_SYNC and self.current_segment:
                self._sync_to_cache(self.current_segment[-1])

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
        线性插值获取指定时刻的状态（优先从缓存获取最新）

        如果目标时刻接近当前时间，优先查询Redis缓存
        """
        # 如果查询的是最新时间，尝试从缓存获取
        now = datetime.now()
        if abs((target_time - now).total_seconds()) < 5:  # 5秒内视为当前
            try:
                from cache.target_cache import target_cache
                cached_state = target_cache.get_target_state(self.target_id)
                if cached_state:
                    return cached_state
            except Exception:
                pass  # 缓存失败，继续原有逻辑

        # 原有插值逻辑
        all_states = []
        for seg in self.segments:
            all_states.extend(seg)

        # 包含当前段
        if self.current_segment:
            all_states.extend(self.current_segment)

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

        # 包含当前段
        for s in self.current_segment:
            if start <= s.timestamp <= end:
                result.append(s)

        return result

    def get_duration(self) -> float:
        """获取航迹总持续时间（秒）"""
        total = 0.0
        all_segments = self.segments.copy()
        if self.current_segment:
            all_segments.append(self.current_segment)

        for seg in all_segments:
            if len(seg) >= 2:
                total += (seg[-1].timestamp - seg[0].timestamp).total_seconds()
        return total

    def get_state_count(self) -> int:
        """获取状态点总数"""
        count = sum(len(seg) for seg in self.segments)
        count += len(self.current_segment)
        return count

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'target_id': self.target_id,
            'target_name': self.target_name,
            'attributes': self.attributes.to_dict(),
            'segment_count': len(self.segments) + (1 if self.current_segment else 0),
            'total_states': self.get_state_count(),
            'duration_seconds': self.get_duration(),
            'cache_version': self._last_cache_version,
            'segments': [
                {
                    'start': seg[0].timestamp.isoformat(),
                    'end': seg[-1].timestamp.isoformat(),
                    'state_count': len(seg)
                }
                for seg in self.segments + ([self.current_segment] if self.current_segment else [])
            ]
        }

    @classmethod
    def from_cache(cls, target_id: str) -> Optional['TargetTrack']:
        """
        从Redis缓存恢复航迹（用于服务重启后的缓存预热）

        Returns:
            TargetTrack对象，如果缓存不存在则返回None
        """
        try:
            from cache.target_cache import target_cache

            # 获取当前状态
            state = target_cache.get_target_state(target_id)
            if not state:
                return None

            # 创建航迹对象
            # 注意：这里简化处理，只恢复当前状态
            # 完整恢复需要从Stream读取历史
            track = cls(
                target_id=target_id,
                target_name=target_id,  # 缓存中未存储名称
                attributes=TargetAttributes()  # 简化
            )

            track.add_state(state, sync_to_cache=False)  # 不再同步回缓存
            track._cache_initialized = True

            logger.info(f"从缓存恢复航迹 [{target_id}]")
            return track

        except Exception as e:
            logger.error(f"从缓存恢复航迹失败 [{target_id}]: {e}")
            return None