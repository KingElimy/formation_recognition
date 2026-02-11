"""
WebSocket管理器 - 实时推送增量更新
"""
import json
import logging
from typing import Dict, Set, Optional, List
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from cache.target_cache import target_cache
from sync.delta_sync import delta_sync

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理"""

    def __init__(self):
        # {client_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # {target_id: Set[client_id]} - 目标订阅关系
        self.target_subscriptions: Dict[str, Set[str]] = {}

        # {client_id: Set[target_id]} - 反向索引
        self.client_subscriptions: Dict[str, Set[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """建立连接"""
        try:
            await websocket.accept()
            self.active_connections[client_id] = websocket
            self.client_subscriptions[client_id] = set()

            logger.info(f"WebSocket连接建立 [{client_id}]")
            return True
        except Exception as e:
            logger.error(f"WebSocket连接失败 [{client_id}]: {e}")
            return False

    def disconnect(self, client_id: str):
        """断开连接"""
        # 清理订阅关系
        if client_id in self.client_subscriptions:
            for target_id in self.client_subscriptions[client_id]:
                if target_id in self.target_subscriptions:
                    self.target_subscriptions[target_id].discard(client_id)
            del self.client_subscriptions[client_id]

        # 移除连接
        if client_id in self.active_connections:
            del self.active_connections[client_id]

        logger.info(f"WebSocket连接断开 [{client_id}]")

    async def subscribe_targets(self, client_id: str, target_ids: List[str]):
        """订阅目标更新"""
        if client_id not in self.active_connections:
            return

        for tid in target_ids:
            if tid not in self.target_subscriptions:
                self.target_subscriptions[tid] = set()
            self.target_subscriptions[tid].add(client_id)
            self.client_subscriptions[client_id].add(tid)

        await self.send_personal_message(client_id, {
            "type": "SUBSCRIBE_CONFIRM",
            "subscribed_targets": target_ids,
            "timestamp": datetime.now().isoformat()
        })

    async def unsubscribe_targets(self, client_id: str, target_ids: List[str]):
        """取消订阅"""
        for tid in target_ids:
            if tid in self.target_subscriptions:
                self.target_subscriptions[tid].discard(client_id)
            if client_id in self.client_subscriptions:
                self.client_subscriptions[client_id].discard(tid)

    async def send_personal_message(self, client_id: str, message: dict):
        """发送个人消息"""
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败 [{client_id}]: {e}")

    async def broadcast(self, message: dict):
        """广播消息"""
        disconnected = []
        for client_id, connection in self.active_connections.items():
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(client_id)

        # 清理断开的连接
        for cid in disconnected:
            self.disconnect(cid)

    async def notify_target_update(self, target_id: str, delta: dict):
        """通知目标更新"""
        if target_id not in self.target_subscriptions:
            return

        message = {
            "type": "TARGET_UPDATE",
            "target_id": target_id,
            "delta": delta,
            "timestamp": datetime.now().isoformat()
        }

        # 只通知订阅者
        for client_id in list(self.target_subscriptions[target_id]):
            await self.send_personal_message(client_id, message)

    async def notify_formation_detected(self, formation_data: dict):
        """通知新编队识别"""
        message = {
            "type": "FORMATION_DETECTED",
            "formation": formation_data,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(message)


# 全局连接管理器
websocket_manager = ConnectionManager()