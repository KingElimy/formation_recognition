"""
Redis客户端管理 - 连接池、序列化、错误处理
"""
import redis
import msgpack
import orjson
from typing import Any, Optional, Dict, List, Union
from datetime import datetime, timedelta
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RedisConfig:
    """Redis配置"""
    HOST = "localhost"
    PORT = 6379
    DB = 0
    PASSWORD = None

    # 连接池配置
    MAX_CONNECTIONS = 50
    SOCKET_TIMEOUT = 5
    SOCKET_CONNECT_TIMEOUT = 5
    RETRY_ON_TIMEOUT = True
    HEALTH_CHECK_INTERVAL = 30

    # Key前缀
    KEY_PREFIX = "formation:"

    # TTL配置（秒）
    TARGET_TTL = 86400  # 目标状态缓存24小时
    FORMATION_TTL = 604800  # 编队结果保留7天
    DELTA_STREAM_TTL = 604800  # 增量流保留7天
    SYNC_SESSION_TTL = 3600  # 同步会话1小时


class RedisClient:
    """Redis客户端封装"""

    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        """初始化连接池"""
        try:
            self._pool = redis.ConnectionPool(
                host=RedisConfig.HOST,
                port=RedisConfig.PORT,
                db=RedisConfig.DB,
                password=RedisConfig.PASSWORD,
                max_connections=RedisConfig.MAX_CONNECTIONS,
                socket_timeout=RedisConfig.SOCKET_TIMEOUT,
                socket_connect_timeout=RedisConfig.SOCKET_CONNECT_TIMEOUT,
                retry_on_timeout=RedisConfig.RETRY_ON_TIMEOUT,
                health_check_interval=RedisConfig.HEALTH_CHECK_INTERVAL,
                decode_responses=False  # 保持bytes，手动处理序列化
            )
            self._redis = redis.Redis(connection_pool=self._pool)
            logger.info("Redis连接池初始化成功")
        except Exception as e:
            logger.error(f"Redis连接池初始化失败: {e}")
            raise

    @property
    def client(self) -> redis.Redis:
        """获取Redis客户端"""
        return self._redis

    def ping(self) -> bool:
        """健康检查"""
        try:
            return self._redis.ping()
        except Exception as e:
            logger.error(f"Redis ping失败: {e}")
            return False

    # ==================== Key管理 ====================

    def _make_key(self, *parts: str) -> str:
        """构建带前缀的key"""
        return f"{RedisConfig.KEY_PREFIX}{':'.join(parts)}"

    def _serialize(self, data: Any) -> bytes:
        """序列化数据（使用msgpack，比JSON更快更紧凑）"""
        try:
            return msgpack.packb(data, default=self._default_encoder, use_bin_type=True)
        except Exception as e:
            logger.error(f"序列化失败: {e}")
            raise

    def _deserialize(self, data: bytes) -> Any:
        """反序列化数据"""
        if data is None:
            return None
        try:
            return msgpack.unpackb(data, raw=False)
        except Exception as e:
            logger.error(f"反序列化失败: {e}")
            raise

    def _default_encoder(self, obj):
        """处理特殊类型编码"""
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        if isinstance(obj, set):
            return {"__set__": list(obj)}
        raise TypeError(f"无法序列化类型: {type(obj)}")

    # ==================== 基础操作封装 ====================

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置值"""
        try:
            serialized = self._serialize(value)
            if ttl:
                return self._redis.setex(key, ttl, serialized)
            return self._redis.set(key, serialized)
        except Exception as e:
            logger.error(f"Redis set失败 [{key}]: {e}")
            return False

    def get(self, key: str) -> Optional[Any]:
        """获取值"""
        try:
            data = self._redis.get(key)
            return self._deserialize(data)
        except Exception as e:
            logger.error(f"Redis get失败 [{key}]: {e}")
            return None

    def delete(self, *keys: str) -> int:
        """删除key"""
        try:
            return self._redis.delete(*keys)
        except Exception as e:
            logger.error(f"Redis delete失败: {e}")
            return 0

    def exists(self, key: str) -> bool:
        """检查key是否存在"""
        try:
            return self._redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists失败 [{key}]: {e}")
            return False

    def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间"""
        try:
            return self._redis.expire(key, seconds)
        except Exception as e:
            logger.error(f"Redis expire失败 [{key}]: {e}")
            return False

    def ttl(self, key: str) -> int:
        """获取剩余生存时间"""
        try:
            return self._redis.ttl(key)
        except Exception as e:
            logger.error(f"Redis ttl失败 [{key}]: {e}")
            return -2

    # ==================== Hash操作 ====================

    def hset(self, key: str, field: str, value: Any) -> bool:
        """Hash设置字段"""
        try:
            serialized = self._serialize(value)
            return self._redis.hset(key, field, serialized) == 1
        except Exception as e:
            logger.error(f"Redis hset失败 [{key}.{field}]: {e}")
            return False

    def hget(self, key: str, field: str) -> Optional[Any]:
        """Hash获取字段"""
        try:
            data = self._redis.hget(key, field)
            return self._deserialize(data)
        except Exception as e:
            logger.error(f"Redis hget失败 [{key}.{field}]: {e}")
            return None

    def hmget(self, key: str, fields: List[str]) -> Dict[str, Any]:
        """Hash批量获取"""
        try:
            values = self._redis.hmget(key, fields)
            return {f: self._deserialize(v) for f, v in zip(fields, values) if v is not None}
        except Exception as e:
            logger.error(f"Redis hmget失败 [{key}]: {e}")
            return {}

    def hgetall(self, key: str) -> Dict[str, Any]:
        """Hash获取所有字段"""
        try:
            data = self._redis.hgetall(key)
            return {k.decode(): self._deserialize(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Redis hgetall失败 [{key}]: {e}")
            return {}

    def hdel(self, key: str, *fields: str) -> int:
        """Hash删除字段"""
        try:
            return self._redis.hdel(key, *fields)
        except Exception as e:
            logger.error(f"Redis hdel失败 [{key}]: {e}")
            return 0

    # ==================== Sorted Set操作（时间序列） ====================

    def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        """Sorted Set添加成员"""
        try:
            # mapping: {member: score}
            return self._redis.zadd(key, mapping)
        except Exception as e:
            logger.error(f"Redis zadd失败 [{key}]: {e}")
            return 0

    def zrangebyscore(self, key: str, min_score: float, max_score: float,
                      withscores: bool = False) -> Union[List[str], List[tuple]]:
        """按分数范围获取"""
        try:
            results = self._redis.zrangebyscore(key, min_score, max_score, withscores=withscores)
            if withscores:
                return [(r[0].decode(), r[1]) for r in results]
            return [r.decode() for r in results]
        except Exception as e:
            logger.error(f"Redis zrangebyscore失败 [{key}]: {e}")
            return []

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> int:
        """按分数范围删除"""
        try:
            return self._redis.zremrangebyscore(key, min_score, max_score)
        except Exception as e:
            logger.error(f"Redis zremrangebyscore失败 [{key}]: {e}")
            return 0

    def zcard(self, key: str) -> int:
        """获取Sorted Set成员数"""
        try:
            return self._redis.zcard(key)
        except Exception as e:
            logger.error(f"Redis zcard失败 [{key}]: {e}")
            return 0

    # ==================== Stream操作（增量同步） ====================

    def xadd(self, stream: str, fields: Dict[str, Any], maxlen: Optional[int] = None) -> Optional[str]:
        """Stream添加消息"""
        try:
            # 序列化所有字段
            serialized = {k: self._serialize(v) for k, v in fields.items()}
            return self._redis.xadd(stream, serialized, maxlen=maxlen)
        except Exception as e:
            logger.error(f"Redis xadd失败 [{stream}]: {e}")
            return None

    def xread(self, streams: Dict[str, str], count: Optional[int] = None,
              block: Optional[int] = None) -> List[Any]:
        """Stream读取消息"""
        try:
            results = self._redis.xread(streams, count=count, block=block)
            return results
        except Exception as e:
            logger.error(f"Redis xread失败: {e}")
            return []

    def xrange(self, stream: str, start: str = "-", end: str = "+",
               count: Optional[int] = None) -> List[Any]:
        """Stream范围查询"""
        try:
            return self._redis.xrange(stream, start, end, count=count)
        except Exception as e:
            logger.error(f"Redis xrange失败 [{stream}]: {e}")
            return []

    def xdel(self, stream: str, *ids: str) -> int:
        """Stream删除消息"""
        try:
            return self._redis.xdel(stream, *ids)
        except Exception as e:
            logger.error(f"Redis xdel失败 [{stream}]: {e}")
            return 0

    # ==================== 批量操作 ====================

    def pipeline(self):
        """获取管道（用于批量操作）"""
        return self._redis.pipeline()

    def mget(self, keys: List[str]) -> Dict[str, Any]:
        """批量获取"""
        try:
            values = self._redis.mget(keys)
            return {k: self._deserialize(v) for k, v in zip(keys, values) if v is not None}
        except Exception as e:
            logger.error(f"Redis mget失败: {e}")
            return {}

    def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """批量设置"""
        try:
            pipe = self.pipeline()
            for key, value in mapping.items():
                serialized = self._serialize(value)
                if ttl:
                    pipe.setex(key, ttl, serialized)
                else:
                    pipe.set(key, serialized)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis mset失败: {e}")
            return False


# 全局Redis客户端实例
redis_client = RedisClient()