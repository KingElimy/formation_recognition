"""
缓存相关API接口 - 增量同步、编队查询、纯缓存操作
"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException, Body
from fastapi.responses import JSONResponse

from cache.target_cache import target_cache
from cache.formation_store import formation_store
from sync.delta_sync import delta_sync
from sync.websocket_manager import websocket_manager
from formation_service import formation_service  # 导入服务实例

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cache", tags=["缓存与同步"])


# ==================== 纯缓存操作接口（不触发识别） ====================

@router.post("/targets/batch_update")
async def batch_update_targets(
        targets: List[Dict] = Body(..., description="目标数据列表"),
        emit_events: bool = Body(True, description="是否发送WebSocket事件")
):
    """
    批量更新目标状态（仅缓存，不执行编队识别）

    用于外部系统同步数据到缓存，供后续增量查询或识别使用
    """
    # 临时关闭事件发送，手动控制
    result = formation_service.cache_targets_only(targets)

    # 手动发送WebSocket事件
    if emit_events:
        for update in result.get("details", {}).get("updated", []):
            if update.get("has_delta"):
                tid = update["target_id"]
                # 获取增量事件发送
                try:
                    import asyncio
                    events = target_cache.get_delta_since(tid, update["version"] - 1)
                    if events:
                        asyncio.create_task(
                            websocket_manager.notify_target_update(tid, events[-1])
                        )
                except Exception as e:
                    logger.warning(f"发送事件失败: {e}")

    return result


@router.get("/targets/{target_id}/delta")
async def get_target_delta(
        target_id: str,
        since_version: int = Query(..., description="起始版本号"),
        limit: int = Query(100, ge=1, le=1000)
):
    """获取单个目标的增量历史"""
    events = target_cache.get_delta_since(target_id, since_version)

    # 限制数量
    events = events[:limit]

    return {
        "success": True,
        "target_id": target_id,
        "since_version": since_version,
        "events_count": len(events),
        "events": events
    }


@router.get("/targets/{target_id}/history")
async def get_target_history(
        target_id: str,
        start: datetime = Query(..., description="开始时间"),
        end: datetime = Query(..., description="结束时间")
):
    """获取目标在指定时间范围内的历史增量"""
    events = target_cache.get_delta_in_range(target_id, start, end)

    return {
        "success": True,
        "target_id": target_id,
        "time_range": {
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        "events_count": len(events),
        "events": events
    }


# ==================== 增量同步接口 ====================

@router.post("/sync/session")
async def create_sync_session(
        client_id: str = Body(..., description="客户端唯一标识"),
        target_ids: Optional[List[str]] = Body(None, description="关注的目标列表（空表示全部）")
):
    """创建同步会话"""
    session_id = delta_sync.create_sync_session(client_id, target_ids)
    return {
        "success": True,
        "session_id": session_id,
        "expires_in": 3600,
        "client_id": client_id,
        "subscribed_targets": target_ids or "all"
    }


@router.post("/sync/pull")
async def pull_delta(
        session_id: Optional[str] = Body(None, description="同步会话ID"),
        since_versions: Optional[dict] = Body(None, description="各目标版本号"),
        target_ids: Optional[List[str]] = Body(None, description="目标列表")
):
    """
    拉取增量数据

    - 首次同步：不传入 since_versions，返回全量数据
    - 增量同步：传入上次同步的版本号，返回差异
    """
    result = delta_sync.pull_delta(
        session_id=session_id,
        target_ids=target_ids,
        since_versions=since_versions
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "success": True,
        "is_full_sync": result.get("full_sync", False),
        "updated_targets": result.get("metadata", {}).get("updated_targets", 0),
        "data": result
    }


@router.post("/sync/compare")
async def compare_and_sync(client_states: dict = Body(...)):
    """
    对比同步 - 客户端上传本地状态，服务器返回差异

    Request Body:
    {
        "target_id_1": {"version": 123, "hash": "abc..."},
        "target_id_2": {"version": 456, "hash": "def..."}
    }
    """
    result = delta_sync.compare_and_sync(client_states)
    return {
        "success": True,
        "data": result
    }


# ==================== WebSocket实时推送 ====================

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket实时数据推送"""
    await websocket_manager.connect(websocket, client_id)

    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()

            msg_type = data.get("type")

            if msg_type == "SUBSCRIBE":
                # 订阅目标更新
                target_ids = data.get("target_ids", [])
                await websocket_manager.subscribe_targets(client_id, target_ids)

                # 立即发送当前状态（全量）
                if target_ids:
                    full_state = delta_sync.pull_full_state(target_ids)
                    await websocket_manager.send_personal_message(client_id, {
                        "type": "INITIAL_STATE",
                        "data": full_state
                    })

            elif msg_type == "UNSUBSCRIBE":
                # 取消订阅
                target_ids = data.get("target_ids", [])
                await websocket_manager.unsubscribe_targets(client_id, target_ids)

            elif msg_type == "PING":
                # 心跳响应
                await websocket_manager.send_personal_message(client_id, {
                    "type": "PONG",
                    "timestamp": datetime.now().isoformat()
                })

            elif msg_type == "GET_DELTA":
                # 客户端请求增量
                since_versions = data.get("since_versions", {})
                result = delta_sync.pull_delta(since_versions=since_versions)
                await websocket_manager.send_personal_message(client_id, {
                    "type": "DELTA_RESPONSE",
                    "data": result
                })

            else:
                await websocket_manager.send_personal_message(client_id, {
                    "type": "ERROR",
                    "message": f"未知消息类型: {msg_type}"
                })

    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket错误 [{client_id}]: {e}")
        websocket_manager.disconnect(client_id)


# ==================== 编队结果查询接口 ====================

@router.get("/formations/recent")
async def get_recent_formations(
        count: int = Query(10, ge=1, le=100, description="返回数量"),
        include_tracks: bool = Query(False, description="是否包含完整航迹")
):
    """获取最近的编队识别结果"""
    formations = formation_store.get_latest_formations(count)

    if not include_tracks:
        for f in formations:
            f.pop("full_tracks", None)

    return {
        "success": True,
        "count": len(formations),
        "formations": formations
    }


@router.get("/formations/range")
async def get_formations_by_time_range(
        start: datetime = Query(..., description="开始时间 (ISO格式)"),
        end: datetime = Query(..., description="结束时间 (ISO格式)"),
        limit: int = Query(100, ge=1, le=1000)
):
    """按时间范围查询编队"""
    formations = formation_store.get_formations_by_time_range(start, end, limit)

    return {
        "success": True,
        "count": len(formations),
        "time_range": {
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        "formations": formations
    }


@router.get("/formations/date/{date_str}")
async def get_formations_by_date(
        date_str: str,
        limit: int = Query(1000, ge=1, le=5000)
):
    """按日期查询编队（格式: YYYYMMDD）"""
    try:
        date = datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，应为YYYYMMDD")

    formations = formation_store.get_formations_by_date(date, limit)

    return {
        "success": True,
        "date": date_str,
        "count": len(formations),
        "formations": formations
    }


@router.get("/formations/{formation_id}")
async def get_formation_detail(formation_id: str):
    """获取编队详情"""
    formation = formation_store.get_formation(formation_id)

    if not formation:
        raise HTTPException(status_code=404, detail="编队不存在或已过期")

    return {
        "success": True,
        "formation": formation
    }


@router.get("/formations/statistics/overview")
async def get_formation_statistics(
        days: int = Query(7, ge=1, le=30, description="统计天数")
):
    """获取编队统计信息"""
    stats = formation_store.get_formation_statistics(days)

    return {
        "success": True,
        "statistics": stats
    }


# ==================== 目标状态查询接口 ====================

@router.get("/targets/active")
async def get_active_targets():
    """获取所有活跃目标"""
    target_ids = target_cache.get_all_active_targets()

    return {
        "success": True,
        "count": len(target_ids),
        "target_ids": target_ids
    }


@router.post("/targets/batch_query")
async def batch_query_targets(target_ids: List[str] = Body(...)):
    """批量查询目标当前状态"""
    states = target_cache.get_targets_batch(target_ids)

    result = {}
    for tid, state in states.items():
        result[tid] = {
            "position": {
                "longitude": state.position.longitude,
                "latitude": state.position.latitude,
                "altitude": state.position.altitude
            },
            "heading": state.heading,
            "speed": state.speed,
            "timestamp": state.timestamp.isoformat()
        }

    return {
        "success": True,
        "found": len(result),
        "not_found": list(set(target_ids) - set(result.keys())),
        "states": result
    }


@router.get("/targets/{target_id}/state")
async def get_target_state(target_id: str):
    """获取目标当前状态"""
    state = target_cache.get_target_state(target_id)

    if not state:
        raise HTTPException(status_code=404, detail="目标不存在或已过期")

    return {
        "success": True,
        "target_id": target_id,
        "state": {
            "position": {
                "longitude": state.position.longitude,
                "latitude": state.position.latitude,
                "altitude": state.position.altitude
            },
            "heading": state.heading,
            "speed": state.speed,
            "timestamp": state.timestamp.isoformat()
        },
        "version": target_cache.get_target_version(target_id)
    }


# ==================== 管理接口 ====================

@router.post("/admin/cleanup")
async def trigger_cleanup():
    """手动触发数据清理"""
    stats = formation_store.cleanup_expired_data()

    return {
        "success": True,
        "message": "清理完成",
        "stats": stats
    }


@router.get("/admin/status")
async def get_admin_status():
    """获取缓存管理状态"""
    return {
        "success": True,
        "redis": {
            "connected": formation_service.get_cache_status().get("redis_connected", False),
            "active_targets": len(target_cache.get_all_active_targets())
        },
        "service": formation_service.get_statistics(),
        "cache_stats": formation_service.cache_stats
    }


@router.post("/admin/clear")
async def clear_cache(
        target_ids: Optional[List[str]] = Body(None, description="指定目标（空表示全部）")
):
    """清理缓存"""
    result = formation_service.clear_cache(target_ids)
    return result


@router.get("/health")
async def cache_health():
    """缓存健康检查"""
    from cache.redis_client import redis_client

    redis_ok = redis_client.ping()

    return {
        "success": True,
        "redis_connected": redis_ok,
        "active_targets": len(target_cache.get_all_active_targets()),
        "timestamp": datetime.now().isoformat()
    }