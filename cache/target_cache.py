"""
TargetState缓存管理 - 支持增量检测和版本控制
"""
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import asdict

from cache.redis_client import redis_client, RedisConfig
from models import TargetState, GeoPosition

logger = logging.getLogger(__name__)


class TargetCache:
    """目标状态缓存管理器"""

    def __init__(self):
        self.redis = redis_client

    def _make_target_key(self, target_id: str) -> str:
        """构建目标缓存key"""
        return self.redis._make_key("target", target_id)

    def _make_version_key(self, target_id: str) -> str:
        """构建版本key"""
        return self.redis._make_key("target", target_id, "version")

    def _make_delta_stream_key(self, target_id: str) -> str:
        """构建增量流key"""
        return self.redis._make_key("delta", target_id)

    def _compute_state_hash(self, state: TargetState) -> str:
        """计算状态哈希（用于快速对比）"""
        # 提取关键字段计算哈希
        data = f"{state.position.longitude:.6f}|{state.position.latitude:.6f}|{state.position.altitude:.1f}|{state.heading:.2f}|{state.speed:.2f}|{state.timestamp.isoformat()}"
        return hashlib.md5(data.encode()).hexdigest()

    def _state_to_dict(self, state: TargetState) -> Dict[str, Any]:
        """状态转换为字典（可序列化）"""
        return {
            "timestamp": state.timestamp.isoformat(),
            "position": {
                "longitude": state.position.longitude,
                "latitude": state.position.latitude,
                "altitude": state.position.altitude
            },
            "heading": state.heading,
            "speed": state.speed,
            "pitch": state.pitch,
            "roll": state.roll,
            "_cached_at": datetime.now().isoformat()
        }

    def _dict_to_state(self, data: Dict[str, Any]) -> TargetState:
        """字典转换为状态"""
        pos_data = data["position"]
        return TargetState(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            position=GeoPosition(
                longitude=pos_data["longitude"],
                latitude=pos_data["latitude"],
                altitude=pos_data["altitude"]
            ),
            heading=data["heading"],
            speed=data["speed"],
            pitch=data.get("pitch", 0.0),
            roll=data.get("roll", 0.0)
        )

    # ==================== 核心缓存操作 ====================

    def cache_target_state(self, target_id: str, state: TargetState,
                           emit_delta: bool = True) -> Tuple[bool, bool, Optional[Dict]]:
        """
        缓存目标状态，检测是否为增量更新

        Returns:
            (是否成功, 是否增量更新, 增量数据或None)
        """
        try:
            key = self._make_target_key(target_id)
            version_key = self._make_version_key(target_id)

            # 计算新状态哈希
            new_hash = self._compute_state_hash(state)
            new_version = int(datetime.now().timestamp() * 1000)  # 毫秒时间戳作为版本

            # 获取旧状态和版本
            old_state_data = self.redis.hgetall(key)
            old_version = self.redis.get(version_key) or 0

            is_update = old_state_data is not None and len(old_state_data) > 0

            # 准备存储数据
            state_data = self._state_to_dict(state)
            state_data["_hash"] = new_hash
            state_data["_version"] = new_version

            # 使用Hash存储，便于字段级更新
            pipe = self.redis.pipeline()

            # 存储完整状态
            for field, value in state_data.items():
                pipe.hset(key, field, value)

            # 设置过期时间
            pipe.expire(key, RedisConfig.TARGET_TTL)
            pipe.set(version_key, new_version, ex=RedisConfig.TARGET_TTL)

            pipe.execute()

            # 计算增量
            delta = None
            if is_update and emit_delta:
                delta = self._compute_delta(old_state_data, state_data)
                if delta:
                    # 发布到增量流
                    self._emit_delta_event(target_id, new_version, delta, "UPDATE")

            return True, is_update, delta

        except Exception as e:
            logger.error(f"缓存目标状态失败 [{target_id}]: {e}")
            return False, False, None

    def get_target_state(self, target_id: str) -> Optional[TargetState]:
        """获取目标当前状态"""
        try:
            key = self._make_target_key(target_id)
            data = self.redis.hgetall(key)

            if not data:
                return None

            return self._dict_to_state(data)
        except Exception as e:
            logger.error(f"获取目标状态失败 [{target_id}]: {e}")
            return None

    def get_target_version(self, target_id: str) -> int:
        """获取目标当前版本号"""
        version_key = self._make_version_key(target_id)
        version = self.redis.get(version_key)
        return version or 0

    def get_targets_batch(self, target_ids: List[str]) -> Dict[str, TargetState]:
        """批量获取目标状态"""
        result = {}
        for tid in target_ids:
            state = self.get_target_state(tid)
            if state:
                result[tid] = state
        return result

    def delete_target(self, target_id: str, reason: str = "EXPIRED") -> bool:
        """删除目标缓存（发送删除事件）"""
        try:
            key = self._make_target_key(target_id)
            version_key = self._make_version_key(target_id)

            # 发送删除事件
            version = self.get_target_version(target_id)
            self._emit_delta_event(target_id, version, {}, "DELETE", reason)

            # 删除数据
            self.redis.delete(key, version_key)

            return True
        except Exception as e:
            logger.error(f"删除目标缓存失败 [{target_id}]: {e}")
            return False

    def _compute_delta(self, old_data: Dict, new_data: Dict) -> Optional[Dict]:
        """计算两个状态之间的增量"""
        delta = {}

        # 对比位置变化
        old_pos = old_data.get("position", {})
        new_pos = new_data.get("position", {})

        if old_pos != new_pos:
            delta["position"] = {
                "from": old_pos,
                "to": new_pos,
                "delta": {
                    "d_lon": new_pos["longitude"] - old_pos["longitude"],
                    "d_lat": new_pos["latitude"] - old_pos["latitude"],
                    "d_alt": new_pos["altitude"] - old_pos["altitude"]
                }
            }

        # 对比航向变化
        if old_data.get("heading") != new_data.get("heading"):
            old_h = old_data.get("heading", 0)
            new_h = new_data.get("heading", 0)
            diff = (new_h - old_h + 180) % 360 - 180  # 处理0/360环绕

            delta["heading"] = {
                "from": old_h,
                "to": new_h,
                "delta": diff
            }

        # 对比速度变化
        if old_data.get("speed") != new_data.get("speed"):
            delta["speed"] = {
                "from": old_data.get("speed"),
                "to": new_data.get("speed"),
                "delta": new_data.get("speed") - old_data.get("speed")
            }

        # 添加时间戳
        if delta:
            delta["_changed_at"] = new_data.get("timestamp")
            delta["_fields"] = list(delta.keys())

        return delta if delta else None

    def _emit_delta_event(self, target_id: str, version: int, delta: Dict,
                          event_type: str, reason: str = None):
        """发送增量事件到Redis Stream"""
        try:
            stream_key = self._make_delta_stream_key(target_id)

            event = {
                "target_id": target_id,
                "version": version,
                "event_type": event_type,  # UPDATE/DELETE
                "timestamp": datetime.now().isoformat(),
                "delta": delta
            }

            if reason:
                event["reason"] = reason

            # 使用Stream，保留最近7天的数据
            self.redis.xadd(
                stream_key,
                event,
                maxlen=10000  # 限制单目标最大事件数
            )

            # 设置Stream过期时间（7天）
            self.redis.expire(stream_key, RedisConfig.DELTA_STREAM_TTL)

            logger.debug(f"发送增量事件 [{target_id}]: {event_type}")

        except Exception as e:
            logger.error(f"发送增量事件失败 [{target_id}]: {e}")

    # ==================== 增量查询接口 ====================

    def get_delta_since(self, target_id: str, since_version: int) -> List[Dict]:
        """
        获取指定版本之后的所有增量事件

        Args:
            target_id: 目标ID
            since_version: 起始版本（不包含）

        Returns:
            增量事件列表
        """
        try:
            stream_key = self._make_delta_stream_key(target_id)

            # 读取所有消息
            messages = self.redis.xrange(stream_key)

            events = []
            for msg_id, fields in messages:
                # 反序列化
                event = {k.decode() if isinstance(k, bytes) else k:
                             self.redis._deserialize(v)
                         for k, v in fields.items()}

                # 检查版本
                if event.get("version", 0) > since_version:
                    event["_msg_id"] = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    events.append(event)

            return events

        except Exception as e:
            logger.error(f"获取增量失败 [{target_id}]: {e}")
            return []

    def get_delta_in_range(self, target_id: str, start_time: datetime,
                           end_time: datetime) -> List[Dict]:
        """获取时间范围内的增量事件"""
        try:
            stream_key = self._make_delta_stream_key(target_id)

            # 转换为毫秒时间戳作为ID范围
            start_id = f"{int(start_time.timestamp() * 1000)}-0"
            end_id = f"{int(end_time.timestamp() * 1000)}-0"

            messages = self.redis.xrange(stream_key, start_id, end_id)

            events = []
            for msg_id, fields in messages:
                event = {k.decode() if isinstance(k, bytes) else k:
                             self.redis._deserialize(v)
                         for k, v in fields.items()}
                event["_msg_id"] = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                events.append(event)

            return events

        except Exception as e:
            logger.error(f"获取范围增量失败 [{target_id}]: {e}")
            return []

    def get_all_active_targets(self) -> List[str]:
        """获取所有活跃的目标ID"""
        try:
            # 扫描所有目标key
            pattern = self.redis._make_key("target", "*")
            keys = []
            cursor = 0

            while True:
                cursor, partial_keys = self.redis.client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                keys.extend([k.decode() if isinstance(k, bytes) else k for k in partial_keys])

                if cursor == 0:
                    break

            # 提取target_id
            target_ids = []
            for key in keys:
                parts = key.split(":")
                if len(parts) >= 3 and parts[-1] != "version":
                    target_ids.append(parts[-2])

            return list(set(target_ids))

        except Exception as e:
            logger.error(f"获取活跃目标失败: {e}")
            return []


# 全局TargetCache实例
target_cache = TargetCache()