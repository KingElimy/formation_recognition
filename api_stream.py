"""
数据流 API - 持续数据输入和结果查询
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Body, HTTPException
from fastapi.responses import JSONResponse

from stream_service import stream_service
from cache.formation_store import formation_store
from sync.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["数据流"])


# ==================== 数据输入接口 ====================

@router.post("/push")
async def push_stream_data(
        targets: List[Dict] = Body(..., description="目标数据列表"),
        source: str = Body("http", description="数据源标识"),
        immediate: bool = Body(False, description="是否立即触发识别")
):
    """
    推送数据到流服务（自动缓存和增量识别）

    数据会自动缓存到 Redis，并根据策略触发增量识别
    """
    if not stream_service.is_running:
        raise HTTPException(status_code=503, detail="数据流服务未运行")

    # 推送数据
    result = await stream_service.push_data(targets, source)

    # 可选：立即触发识别
    if immediate and result.get("pending_targets", 0) > 0:
        formations = await stream_service._do_recognize()
        result["immediate_result"] = {
            "formation_count": len(formations) if formations else 0,
            "formations": formations
        }

    return result


@router.websocket("/ws/push")
async def websocket_push(websocket: WebSocket, source: str = "ws"):
    """
    WebSocket 持续数据推送

    客户端持续发送数据，服务端自动处理和识别
    """
    await websocket.accept()
    client_id = f"stream_{id(websocket)}"

    try:
        while True:
            data = await websocket.receive_json()

            # 支持两种格式：单条或批量
            if isinstance(data, list):
                targets = data
            elif isinstance(data, dict) and "targets" in data:
                targets = data["targets"]
            else:
                targets = [data]

            # 处理数据
            result = await stream_service.push_data(targets, source)

            # 返回确认
            await websocket.send_json({
                "type": "ACK",
                "received": len(targets),
                "status": result
            })

    except WebSocketDisconnect:
        logger.info(f"数据流 WebSocket 断开 [{client_id}]")
    except Exception as e:
        logger.error(f"数据流 WebSocket 错误 [{client_id}]: {e}")
        await websocket.close()


# ==================== 结果查询接口 ====================

@router.get("/formations/latest")
async def get_latest_stream_formations(
        count: int = Query(10, ge=1, le=100),
        include_tracks: bool = Query(False)
):
    """
    获取最近识别的编队（数据流自动识别的结果）
    """
    formations = stream_service.get_recent_formations(count)

    if not include_tracks:
        for f in formations:
            f.pop("full_tracks", None)

    return {
        "success": True,
        "count": len(formations),
        "service_status": stream_service.get_status(),
        "formations": formations
    }


@router.get("/formations/since")
async def get_formations_since(
        since: datetime = Query(..., description="查询此时间之后的编队"),
        limit: int = Query(100, ge=1, le=1000)
):
    """获取指定时间之后识别的编队"""
    formations = formation_store.get_formations_by_time_range(
        start=since,
        end=datetime.now(),
        limit=limit
    )

    return {
        "success": True,
        "since": since.isoformat(),
        "count": len(formations),
        "formations": formations
    }


@router.get("/formations/active")
async def get_active_formations():
    """
    获取当前活跃的编队（正在持续接收数据的编队）

    基于最近识别的编队，结合缓存中的目标状态判断
    """
    # 获取最近 1 小时的编队
    from datetime import timedelta
    since = datetime.now() - timedelta(hours=1)

    recent = formation_store.get_formations_by_time_range(since, datetime.now(), limit=100)

    # 过滤：检查编队成员是否仍在缓存中
    active_formations = []
    for formation in recent:
        members = formation.get("members", {})
        active_members = 0

        for tid in members.keys():
            if target_cache.get_target_state(tid):
                active_members += 1

        # 超过 50% 成员活跃则认为编队活跃
        if len(members) > 0 and active_members / len(members) >= 0.5:
            formation["_active_members"] = active_members
            formation["_total_members"] = len(members)
            active_formations.append(formation)

    return {
        "success": True,
        "active_count": len(active_formations),
        "total_recent": len(recent),
        "formations": active_formations
    }


# ==================== 服务管理接口 ====================

@router.get("/status")
async def get_stream_status():
    """获取数据流服务状态"""
    return stream_service.get_status()


@router.post("/config")
async def update_stream_config(
        auto_recognize: Optional[bool] = Body(None),
        recognize_interval: Optional[float] = Body(None, ge=1.0, le=60.0),
        min_change_threshold: Optional[float] = Body(None, ge=0.0, le=1.0)
):
    """更新数据流服务配置"""
    if auto_recognize is not None:
        stream_service.auto_recognize = auto_recognize
    if recognize_interval is not None:
        stream_service.recognize_interval = recognize_interval
    if min_change_threshold is not None:
        stream_service.min_change_threshold = min_change_threshold

    return {
        "success": True,
        "current_config": {
            "auto_recognize": stream_service.auto_recognize,
            "recognize_interval": stream_service.recognize_interval,
            "min_change_threshold": stream_service.min_change_threshold
        }
    }


@router.post("/recognize/force")
async def force_recognize():
    """强制立即执行识别"""
    result = stream_service.force_recognize()
    return {
        "success": True,
        **result
    }


@router.post("/stop")
async def stop_stream_service():
    """停止数据流服务"""
    stream_service.shutdown()
    return {"success": True, "message": "服务已停止"}


@router.post("/start")
async def start_stream_service(
        preset: str = Body("tight_fighter")
):
    """启动数据流服务"""
    if stream_service.is_running:
        return {"success": False, "message": "服务已在运行"}

    stream_service.initialize(preset)
    return {"success": True, "message": "服务已启动"}


# ==================== WebSocket 结果订阅 ====================

@router.websocket("/ws/results")
async def websocket_results(websocket: WebSocket):
    """
    WebSocket 订阅编队识别结果

    新编队识别时自动推送，无需轮询
    """
    await websocket.accept()
    client_id = f"results_{id(websocket)}"

    # 注册到结果推送（通过全局事件）
    # 这里简化处理，实际可使用专用的事件总线
    await websocket_manager.connect(websocket, client_id)

    try:
        # 发送历史最近 5 个编队作为初始数据
        recent = stream_service.get_recent_formations(5)
        await websocket.send_json({
            "type": "INITIAL",
            "recent_formations": recent
        })

        # 保持连接，等待推送
        while True:
            # 接收心跳或控制命令
            data = await websocket.receive_json()

            if data.get("type") == "PING":
                await websocket.send_json({
                    "type": "PONG",
                    "timestamp": datetime.now().isoformat()
                })
            elif data.get("type") == "GET_LATEST":
                count = data.get("count", 10)
                formations = stream_service.get_recent_formations(count)
                await websocket.send_json({
                    "type": "LATEST_RESPONSE",
                    "formations": formations
                })

    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"结果 WebSocket 错误: {e}")
        websocket_manager.disconnect(client_id)