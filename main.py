"""
编队识别RESTful API服务 - 完整版（含规则管理和前端）
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
from formation_service import FormationService
from api_rules import router as rules_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局服务实例
formation_service = FormationService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("服务启动中...")

    # 初始化数据库
    db_manager.init_database()

    # 初始化编队服务
    formation_service.initialize()

    logger.info("服务启动完成")
    yield

    # 关闭时
    logger.info("服务关闭中...")
    formation_service.cleanup()
    logger.info("服务已关闭")


# 创建FastAPI应用
app = FastAPI(
    title="编队识别服务 API",
    description="""
    基于规则的空中作战编队识别RESTful API服务。

    ## 主要功能

    * **编队识别**: 基于多维度规则识别空中目标编队
    * **规则管理**: 动态配置和调整识别规则（支持持久化）
    * **场景适配**: 支持多种作战场景的自适应识别
    * **Web管理**: 提供可视化规则管理界面

    ## 技术特点

    * 三层规则体系: 编队规则、协同规则、属性规则
    * 数据库持久化（SQLite/PostgreSQL）
    * 完整的规则版本历史和审计
    * RESTful接口 + Web管理界面
    """,
    version="2.0.0",
    docs_url=None,  # 禁用默认docs，使用自定义
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

# 挂载静态文件（前端）
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ==================== 前端路由 ====================

@app.get("/", response_class=HTMLResponse, tags=["前端"])
async def index():
    """Web管理界面入口"""
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>编队识别规则管理系统</title>
        <link rel="stylesheet" href="/static/css/style.css">
        <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    </head>
    <body>
        <div id="app"></div>
        <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
        <script src="https://unpkg.com/vue-router@4/dist/vue-router.global.js"></script>
        <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
        <script src="/static/js/app.js"></script>
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
    return HealthCheck(
        status="healthy",
        service="formation-recognition-api",
        version="2.0.0",
        timestamp=datetime.now(),
        details={
            "database": "connected",
            "rules_loaded": len(formation_service.get_available_presets()),
            "active_formations": formation_service.get_active_formation_count()
        }
    )


# ==================== 编队识别核心接口 ====================

@app.post("/recognize",
          tags=["编队识别"],
          response_model=RecognitionResponse,
          summary="执行编队识别")
async def recognize(request: RecognitionRequest):
    """执行编队识别"""
    try:
        logger.info(f"收到识别请求: {len(request.targets)}个目标")

        result = formation_service.recognize(
            targets=[t.dict() for t in request.targets],
            preset=request.preset,
            scene_type=request.scene_type,
            time_range=request.time_range
        )

        logger.info(f"识别完成: {len(result.get('formations', []))}个编队")
        return RecognitionResponse(**result)

    except Exception as e:
        logger.error(f"识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 注册路由 ====================

app.include_router(rules_router)

# 启动入口
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )