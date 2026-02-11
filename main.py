"""
编队识别RESTful API服务 - 完整版（集成Redis缓存和增量同步）
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Body, Path, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import logging
import os

# 导入业务模块
from database import db_manager
from api_models import (
    TargetData, FormationResult, RecognitionRequest, RecognitionResponse,
    HealthCheck, ApiResponse
)
from formation_service import formation_service
from api_rules import router as rules_router
from api_cache import router as cache_router  # 新增缓存路由
from scheduler.cleanup import cleanup_scheduler  # 新增清理调度器
from sync.websocket_manager import websocket_manager  # WebSocket管理器

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("服务启动中...")

    # 初始化数据库
    db_manager.init_database()

    # 初始化编队服务（含Redis缓存）
    formation_service.initialize()

    # 启动定时清理任务
    cleanup_scheduler.start()

    logger.info("服务启动完成，Redis缓存已启用")
    yield

    # 关闭时
    logger.info("服务关闭中...")
    cleanup_scheduler.shutdown()
    formation_service.cleanup()
    logger.info("服务已关闭")


# 创建FastAPI应用
app = FastAPI(
    title="编队识别服务 API",
    description="""
    基于规则的空中作战编队识别RESTful API服务（集成Redis缓存）。

    ## 主要功能

    * **编队识别**: 基于多维度规则识别空中目标编队
    * **Redis缓存**: TargetState实时缓存，支持增量同步
    * **增量识别**: 只处理变化的目标，提升性能
    * **7天滚动存储**: 编队结果自动过期清理
    * **WebSocket推送**: 实时推送目标更新和编队识别结果

    ## 核心接口

    * `/recognize` - 执行编队识别（自动缓存）
    * `/cache/targets/batch_update` - 纯缓存更新（不识别）
    * `/cache/sync/pull` - 增量数据同步
    * `/cache/ws/{client_id}` - WebSocket实时推送
    * `/cache/formations/recent` - 查询最近编队结果

    ## 技术特点

    * 三层规则体系: 编队规则、协同规则、属性规则
    * Redis Hash存储TargetState，Stream存储增量事件
    * 智能增量识别，减少重复计算
    * 完整的7天数据生命周期管理
    """,
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ==================== 前端路由 ====================

@app.get("/", response_class=HTMLResponse, tags=["前端"])
async def index():
    """Web管理界面入口"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>编队识别规则管理系统</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; }
            .card { margin-bottom: 20px; }
            .status-online { color: green; }
            .status-offline { color: red; }
        </style>
    </head>
    <body>
        <div id="app" class="container">
            <h1>编队识别服务管理面板</h1>

            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">服务状态</div>
                        <div class="card-body">
                            <p>Redis缓存: <span :class="cacheStatus.redis_connected ? 'status-online' : 'status-offline'">
                                {{ cacheStatus.redis_connected ? '在线' : '离线' }}
                            </span></p>
                            <p>活跃目标数: {{ cacheStatus.active_targets }}</p>
                            <p>WebSocket连接: {{ wsStatus.active_connections }}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">快捷操作</div>
                        <div class="card-body">
                            <a href="/docs" class="btn btn-primary">API文档</a>
                            <a href="/cache/formations/recent" class="btn btn-info">最近编队</a>
                            <a href="/cache/admin/status" class="btn btn-secondary">缓存状态</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            const { createApp } = Vue;
            createApp({
                data() {
                    return {
                        cacheStatus: { redis_connected: false, active_targets: 0 },
                        wsStatus: { active_connections: 0 }
                    }
                },
                async mounted() {
                    // 获取状态
                    const res = await fetch('/cache/health');
                    this.cacheStatus = await res.json();

                    const wsRes = await fetch('/ws/status');
                    this.wsStatus = await wsRes.json();
                }
            }).mount('#app');
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/docs", tags=["文档"])
async def custom_swagger_ui():
    """自定义Swagger UI"""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="编队识别 API 文档",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )


# ==================== 健康检查接口 ====================

@app.get("/health", tags=["健康检查"], response_model=HealthCheck)
async def health_check():
    """健康检查"""
    cache_status = formation_service.get_cache_status()

    return HealthCheck(
        status="healthy",
        service="formation-recognition-api",
        version="3.0.0",
        timestamp=datetime.now(),
        details={
            "database": "connected",
            "redis": "connected" if cache_status.get("redis_connected") else "disconnected",
            "rules_loaded": len(formation_service.get_available_presets()),
            "active_formations": formation_service.get_active_formation_count(),
            "cached_targets": cache_status.get("active_targets_in_cache", 0)
        }
    )


# ==================== 编队识别核心接口（优化版） ====================

@app.post("/recognize",
          tags=["编队识别"],
          response_model=RecognitionResponse,
          summary="执行编队识别（集成缓存）")
async def recognize(request: RecognitionRequest):
    """
    执行编队识别（自动缓存目标状态，支持增量识别）

    - 目标状态自动写入Redis缓存
    - 支持增量识别模式（只处理变化的目标）
    - 识别结果自动存储7天
    """
    try:
        logger.info(f"收到识别请求: {len(request.targets)}个目标")

        # 使用优化后的识别方法
        result = formation_service.recognize(
            targets=[t.dict() for t in request.targets],
            preset=request.preset,
            scene_type=request.scene_type,
            time_range=request.time_range,
            use_cache=True,  # 启用缓存
            incremental=False,  # 可根据需要改为True
            emit_events=True  # 发送WebSocket事件
        )

        logger.info(f"识别完成: {result['formation_count']}个编队，"
                    f"已缓存: {result.get('stored_formation_ids', [])}")

        return RecognitionResponse(**result)

    except Exception as e:
        logger.error(f"识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recognize/incremental",
          tags=["编队识别"],
          summary="增量编队识别")
async def recognize_incremental(request: RecognitionRequest):
    """
    增量编队识别（只处理有变化的目标）

    适用于高频数据流场景，减少重复计算
    """
    try:
        result = formation_service.recognize(
            targets=[t.dict() for t in request.targets],
            preset=request.preset,
            scene_type=request.scene_type,
            time_range=request.time_range,
            use_cache=True,
            incremental=True,  # 启用增量模式
            emit_events=True
        )

        return RecognitionResponse(**result)

    except Exception as e:
        logger.error(f"增量识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 纯缓存接口（不触发识别） ====================

@app.post("/cache-only",
          tags=["缓存"],
          summary="仅缓存目标状态（不识别）")
async def cache_only(targets: List[Dict] = Body(...)):
    """
    批量缓存目标状态，不执行编队识别

    用于外部系统同步数据到缓存，供后续查询或识别使用
    """
    try:
        result = formation_service.cache_targets_only(targets)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WebSocket状态监控 ====================

@app.get("/ws/status", tags=["监控"])
async def websocket_status():
    """WebSocket连接状态"""
    return {
        "active_connections": len(websocket_manager.active_connections),
        "subscribed_targets": len(websocket_manager.target_subscriptions),
        "client_subscriptions": {
            cid: len(targets)
            for cid, targets in websocket_manager.client_subscriptions.items()
        }
    }


# ==================== 注册路由 ====================

app.include_router(rules_router)
app.include_router(cache_router)  # 注册缓存路由

# 启动入口
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )