"""
编队识别结果存储 - 7天滚动存储，支持时间序列查询
"""
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import asdict

from cache.redis_client import redis_client, RedisConfig
from models import Formation

logger = logging.getLogger(__name__)


class FormationStore:
    """编队结果存储管理器"""

    def __init__(self):
        self.redis = redis_client
        self.RETENTION_DAYS = 7

    def _make_formation_key(self, formation_id: str) -> str:
        """构建编队数据key"""
        return self.redis._make_key("formation", formation_id)

    def _make_timeline_key(self) -> str:
        """构建时间线索引key"""
        return self.redis._make_key("formations", "timeline")

    def _make_daily_key(self, date_str: str) -> str:
        """构建日索引key"""
        return self.redis._make_key("formations", "daily", date_str)

    def _formation_to_dict(self, formation: Formation) -> Dict[str, Any]:
        """编队对象转换为字典"""
        # 使用Formation自带的to_dict方法，并添加元数据
        data = formation.to_dict(include_full_track=True)
        data["_stored_at"] = datetime.now().isoformat()
        data["_expires_at"] = (datetime.now() + timedelta(days=self.RETENTION_DAYS)).isoformat()
        return data

    def _generate_formation_id(self, timestamp: datetime) -> str:
        """生成编队ID"""
        ts = int(timestamp.timestamp() * 1000)
        import uuid
        return f"F{ts}_{uuid.uuid4().hex[:8]}"

    # ==================== 核心存储操作 ====================

    def store_formation(self, formation: Formation,
                        custom_id: Optional[str] = None) -> Optional[str]:
        """
        存储编队识别结果

        Returns:
            存储的编队ID
        """
        try:
            # 生成或使用自定义ID
            formation_id = custom_id or self._generate_formation_id(formation.create_time)

            # 转换数据
            data = self._formation_to_dict(formation)
            data["formation_id"] = formation_id  # 确保ID一致

            # 存储编队详情（Hash）
            formation_key = self._make_formation_key(formation_id)

            pipe = self.redis.pipeline()

            # 使用Hash存储，便于字段查询
            for field, value in data.items():
                serialized = self.redis._serialize(value)
                pipe.hset(formation_key, field, serialized)

            # 设置7天过期
            pipe.expire(formation_key, RedisConfig.FORMATION_TTL)

            # 添加到时间线索引（Sorted Set，按创建时间排序）
            timeline_key = self._make_timeline_key()
            score = formation.create_time.timestamp()
            pipe.zadd(timeline_key, {formation_id: score})

            # 添加到日索引
            date_str = formation.create_time.strftime("%Y%m%d")
            daily_key = self._make_daily_key(date_str)
            pipe.zadd(daily_key, {formation_id: score})
            # 日索引也设置7天过期
            pipe.expire(daily_key, RedisConfig.FORMATION_TTL)

            pipe.execute()

            logger.info(f"编队结果已存储 [{formation_id}]: {formation.formation_type}")
            return formation_id

        except Exception as e:
            logger.error(f"存储编队结果失败: {e}")
            return None

    def store_formations_batch(self, formations: List[Formation]) -> List[str]:
        """批量存储编队结果"""
        ids = []
        for formation in formations:
            fid = self.store_formation(formation)
            if fid:
                ids.append(fid)
        return ids

    def get_formation(self, formation_id: str) -> Optional[Dict[str, Any]]:
        """获取编队详情"""
        try:
            key = self._make_formation_key(formation_id)
            data = self.redis.hgetall(key)

            if not data:
                return None

            return data
        except Exception as e:
            logger.error(f"获取编队失败 [{formation_id}]: {e}")
            return None

    def delete_formation(self, formation_id: str) -> bool:
        """删除编队记录"""
        try:
            key = self._make_formation_key(formation_id)

            # 从索引中移除
            timeline_key = self._make_timeline_key()
            self.redis.client.zrem(timeline_key, formation_id)

            # 获取创建时间以确定日索引
            data = self.get_formation(formation_id)
            if data and "create_time" in data:
                create_time = datetime.fromisoformat(data["create_time"])
                date_str = create_time.strftime("%Y%m%d")
                daily_key = self._make_daily_key(date_str)
                self.redis.client.zrem(daily_key, formation_id)

            # 删除数据
            self.redis.delete(key)

            return True
        except Exception as e:
            logger.error(f"删除编队失败 [{formation_id}]: {e}")
            return False

    # ==================== 时间序列查询 ====================

    def get_formations_by_time_range(self, start: datetime, end: datetime,
                                     limit: int = 100) -> List[Dict[str, Any]]:
        """
        按时间范围查询编队

        Args:
            start: 开始时间
            end: 结束时间
            limit: 最大返回数量
        """
        try:
            timeline_key = self._make_timeline_key()

            # 使用Sorted Set按分数范围查询
            start_score = start.timestamp()
            end_score = end.timestamp()

            formation_ids = self.redis.zrangebyscore(
                timeline_key,
                start_score,
                end_score
            )

            # 限制数量
            formation_ids = formation_ids[:limit]

            # 批量获取详情
            results = []
            for fid in formation_ids:
                data = self.get_formation(fid)
                if data:
                    results.append(data)

            return results

        except Exception as e:
            logger.error(f"时间范围查询失败: {e}")
            return []

    def get_formations_by_date(self, date: datetime,
                               limit: int = 1000) -> List[Dict[str, Any]]:
        """获取某一天的编队"""
        try:
            date_str = date.strftime("%Y%m%d")
            daily_key = self._make_daily_key(date_str)

            formation_ids = self.redis.client.zrange(daily_key, 0, limit - 1, desc=True)
            formation_ids = [fid.decode() if isinstance(fid, bytes) else fid
                             for fid in formation_ids]

            results = []
            for fid in formation_ids:
                data = self.get_formation(fid)
                if data:
                    results.append(data)

            return results

        except Exception as e:
            logger.error(f"按日期查询失败 [{date_str}]: {e}")
            return []

    def get_latest_formations(self, count: int = 10) -> List[Dict[str, Any]]:
        """获取最新的编队"""
        try:
            timeline_key = self._make_timeline_key()

            # 获取最新的N个
            formation_ids = self.redis.client.zrevrange(
                timeline_key,
                0,
                count - 1
            )
            formation_ids = [fid.decode() if isinstance(fid, bytes) else fid
                             for fid in formation_ids]

            results = []
            for fid in formation_ids:
                data = self.get_formation(fid)
                if data:
                    results.append(data)

            return results

        except Exception as e:
            logger.error(f"获取最新编队失败: {e}")
            return []

    def get_formation_statistics(self, days: int = 7) -> Dict[str, Any]:
        """获取编队统计信息"""
        try:
            stats = {
                "total_count": 0,
                "daily_counts": {},
                "type_distribution": {},
                "avg_confidence": 0.0
            }

            total_confidence = 0.0
            confidence_count = 0

            for i in range(days):
                date = datetime.now() - timedelta(days=i)
                date_str = date.strftime("%Y%m%d")

                daily_key = self._make_daily_key(date_str)
                count = self.redis.zcard(daily_key)

                stats["daily_counts"][date_str] = count
                stats["total_count"] += count

                # 获取类型分布
                formations = self.get_formations_by_date(date, limit=1000)
                for f in formations:
                    f_type = f.get("formation_type", "Unknown")
                    stats["type_distribution"][f_type] = \
                        stats["type_distribution"].get(f_type, 0) + 1

                    conf = f.get("confidence", 0)
                    total_confidence += conf
                    confidence_count += 1

            if confidence_count > 0:
                stats["avg_confidence"] = round(total_confidence / confidence_count, 3)

            return stats

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    # ==================== 数据清理 ====================

    def cleanup_expired_data(self) -> Dict[str, int]:
        """
        清理过期数据（Redis TTL自动处理，此方法用于补偿清理）

        Returns:
            清理统计
        """
        try:
            stats = {"formations_removed": 0, "orphan_indexes_cleaned": 0}

            # 清理时间线中指向已删除数据的索引
            timeline_key = self._make_timeline_key()

            # 获取所有ID（这里可能需要分批处理，如果数据量很大）
            all_ids = self.redis.zrangebyscore(
                timeline_key,
                0,
                datetime.now().timestamp()
            )

            to_remove = []
            for fid in all_ids:
                fid_str = fid.decode() if isinstance(fid, bytes) else fid
                if not self.redis.exists(self._make_formation_key(fid_str)):
                    to_remove.append(fid_str)

            if to_remove:
                self.redis.client.zrem(timeline_key, *to_remove)
                stats["orphan_indexes_cleaned"] = len(to_remove)

            # 清理旧的日索引（超过7天）
            cutoff_date = datetime.now() - timedelta(days=self.RETENTION_DAYS)
            for i in range(30):  # 检查最近30天的索引
                check_date = datetime.now() - timedelta(days=i)
                date_str = check_date.strftime("%Y%m%d")
                daily_key = self._make_daily_key(date_str)

                if check_date < cutoff_date:
                    # 删除旧索引
                    count = self.redis.zcard(daily_key)
                    if count > 0:
                        self.redis.delete(daily_key)
                        stats["formations_removed"] += count

            logger.info(f"数据清理完成: {stats}")
            return stats

        except Exception as e:
            logger.error(f"清理过期数据失败: {e}")
            return {}


# 全局FormationStore实例
formation_store = FormationStore()