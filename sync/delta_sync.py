"""
增量同步服务 - 支持按需拉取和版本管理
"""
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta

from cache.redis_client import redis_client
from cache.target_cache import target_cache

logger = logging.getLogger(__name__)


class DeltaSyncService:
    """增量同步服务"""

    def __init__(self):
        self.redis = redis_client

    def _make_sync_session_key(self, session_id: str) -> str:
        """构建同步会话key"""
        return self.redis._make_key("sync", "session", session_id)

    def create_sync_session(self, client_id: str,
                            target_ids: Optional[List[str]] = None) -> str:
        """
        创建同步会话

        Args:
            client_id: 客户端标识
            target_ids: 关注的目标列表（None表示全部）

        Returns:
            session_id
        """
        import uuid
        session_id = f"sync_{client_id}_{uuid.uuid4().hex[:8]}"

        session_data = {
            "session_id": session_id,
            "client_id": client_id,
            "created_at": datetime.now().isoformat(),
            "last_sync_at": datetime.now().isoformat(),
            "target_ids": target_ids or [],  # 空列表表示订阅全部
            "versions": {},  # 每个目标的最后同步版本
            "is_active": True
        }

        key = self._make_sync_session_key(session_id)
        self.redis.set(key, session_data, ttl=3600)  # 1小时过期

        logger.info(f"创建同步会话 [{session_id}]")
        return session_id

    def get_sync_session(self, session_id: str) -> Optional[Dict]:
        """获取同步会话"""
        key = self._make_sync_session_key(session_id)
        return self.redis.get(key)

    def update_sync_session(self, session_id: str,
                            versions: Dict[str, int]) -> bool:
        """更新同步会话的版本记录"""
        try:
            session = self.get_sync_session(session_id)
            if not session:
                return False

            session["versions"].update(versions)
            session["last_sync_at"] = datetime.now().isoformat()

            key = self._make_sync_session_key(session_id)
            self.redis.set(key, session, ttl=3600)  # 刷新TTL

            return True
        except Exception as e:
            logger.error(f"更新同步会话失败 [{session_id}]: {e}")
            return False

    def close_sync_session(self, session_id: str) -> bool:
        """关闭同步会话"""
        key = self._make_sync_session_key(session_id)
        return self.redis.delete(key) > 0

    # ==================== 增量拉取接口 ====================

    def pull_delta(self, session_id: Optional[str] = None,
                   target_ids: Optional[List[str]] = None,
                   since_versions: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """
        拉取增量数据

        Args:
            session_id: 同步会话ID（可选）
            target_ids: 目标ID列表（优先于会话中的配置）
            since_versions: 各目标的版本号（优先于会话中的记录）

        Returns:
            增量数据包
        """
        try:
            # 获取会话信息
            session = None
            if session_id:
                session = self.get_sync_session(session_id)

            # 确定目标列表
            if target_ids is None:
                if session and session.get("target_ids"):
                    target_ids = session["target_ids"]
                else:
                    # 获取所有活跃目标
                    target_ids = target_cache.get_all_active_targets()

            # 确定版本基准
            base_versions = {}
            if since_versions:
                base_versions = since_versions
            elif session:
                base_versions = session.get("versions", {})

            # 收集增量
            delta_package = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "full_sync": len(base_versions) == 0,  # 是否全量同步
                "targets": {},
                "removed_targets": [],
                "metadata": {
                    "total_targets": len(target_ids),
                    "updated_targets": 0
                }
            }

            current_versions = {}

            for tid in target_ids:
                # 获取当前状态
                current_state = target_cache.get_target_state(tid)
                current_version = target_cache.get_target_version(tid)

                if current_state is None:
                    # 目标已删除或不存在
                    if tid in base_versions:
                        delta_package["removed_targets"].append({
                            "target_id": tid,
                            "last_version": base_versions[tid]
                        })
                    continue

                current_versions[tid] = current_version

                # 检查是否需要更新
                base_version = base_versions.get(tid, 0)

                if current_version > base_version:
                    # 获取增量事件
                    delta_events = target_cache.get_delta_since(tid, base_version)

                    # 简化：直接返回当前状态（生产环境可优化为真正增量）
                    delta_package["targets"][tid] = {
                        "current_state": {
                            "position": {
                                "longitude": current_state.position.longitude,
                                "latitude": current_state.position.latitude,
                                "altitude": current_state.position.altitude
                            },
                            "heading": current_state.heading,
                            "speed": current_state.speed,
                            "timestamp": current_state.timestamp.isoformat()
                        },
                        "version": current_version,
                        "base_version": base_version,
                        "delta_events": delta_events[-5:] if delta_events else []  # 最近5个事件
                    }

            delta_package["metadata"]["updated_targets"] = len(delta_package["targets"])
            delta_package["current_versions"] = current_versions

            # 更新会话
            if session_id:
                self.update_sync_session(session_id, current_versions)

            return delta_package

        except Exception as e:
            logger.error(f"拉取增量失败: {e}")
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    def pull_full_state(self, target_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """拉取全量状态（用于首次同步）"""
        try:
            if target_ids is None:
                target_ids = target_cache.get_all_active_targets()

            full_state = {
                "timestamp": datetime.now().isoformat(),
                "sync_type": "FULL",
                "targets": {},
                "versions": {}
            }

            for tid in target_ids:
                state = target_cache.get_target_state(tid)
                version = target_cache.get_target_version(tid)

                if state:
                    full_state["targets"][tid] = {
                        "position": {
                            "longitude": state.position.longitude,
                            "latitude": state.position.latitude,
                            "altitude": state.position.altitude
                        },
                        "heading": state.heading,
                        "speed": state.speed,
                        "timestamp": state.timestamp.isoformat()
                    }
                    full_state["versions"][tid] = version

            return full_state

        except Exception as e:
            logger.error(f"拉取全量状态失败: {e}")
            return {"error": str(e)}

    def compare_and_sync(self, client_states: Dict[str, Dict]) -> Dict[str, Any]:
        """
        客户端上传状态，服务器对比后返回差异

        Args:
            client_states: {target_id: {version, hash, ...}}

        Returns:
            需要更新的目标列表
        """
        try:
            to_update = []
            server_versions = {}

            for tid, client_info in client_states.items():
                server_version = target_cache.get_target_version(tid)
                server_versions[tid] = server_version

                client_version = client_info.get("version", 0)

                if server_version > client_version:
                    to_update.append(tid)

            # 找出服务器有但客户端没有的目标
            all_active = set(target_cache.get_all_active_targets())
            client_has = set(client_states.keys())
            new_targets = list(all_active - client_has)

            return {
                "timestamp": datetime.now().isoformat(),
                "need_update": to_update,
                "new_targets": new_targets,
                "server_versions": server_versions
            }

        except Exception as e:
            logger.error(f"对比同步失败: {e}")
            return {"error": str(e)}


# 全局DeltaSyncService实例
delta_sync = DeltaSyncService()