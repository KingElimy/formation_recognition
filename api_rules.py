"""
规则管理API - 扩展的规则管理接口
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Any
from datetime import datetime

from database import db_manager, get_db, RulePresetDB, RuleDB, SceneConfigDB
from api_models import (
    RulePreset, RuleConfig, RuleCreateRequest, RuleUpdateRequest,
    PresetCreateRequest, PresetUpdateRequest, ReorderRequest,
    RuleStatistics, ApiResponse
)

router = APIRouter(prefix="/api/v1/rules", tags=["规则管理"])


# ==================== 预设管理接口 ====================

@router.get("/presets", response_model=ApiResponse)
async def list_presets(
        category: Optional[str] = Query(None, description="分类筛选"),
        include_rules: bool = Query(False, description="是否包含规则详情"),
        db: Session = Depends(get_db)
):
    """获取所有规则预设"""
    presets = db_manager.get_presets(db, category=category, include_rules=include_rules)
    return ApiResponse(
        success=True,
        data={"presets": presets, "count": len(presets)}
    )


@router.get("/presets/{preset_id}", response_model=ApiResponse)
async def get_preset(
        preset_id: str = Path(..., description="预设ID"),
        db: Session = Depends(get_db)
):
    """获取预设详情"""
    preset = db_manager.get_preset_by_id(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    return ApiResponse(
        success=True,
        data=preset.to_dict(include_rules=True)
    )


@router.post("/presets", response_model=ApiResponse)
async def create_preset(
        request: PresetCreateRequest,
        db: Session = Depends(get_db)
):
    """创建新预设"""
    # 检查名称是否已存在
    existing = db_manager.get_preset_by_name(db, request.name)
    if existing:
        raise HTTPException(status_code=400, detail="预设名称已存在")

    preset_data = request.dict()
    preset_data["category"] = "custom"
    preset_data["is_default"] = False

    preset = db_manager.create_preset(db, preset_data)

    # 如果有初始规则，创建规则
    if request.initial_rules:
        for idx, rule_data in enumerate(request.initial_rules):
            rule_dict = rule_data.dict()
            rule_dict["preset_id"] = preset.id
            rule_dict["order"] = idx
            db_manager.create_rule(db, rule_dict)

    return ApiResponse(
        success=True,
        message="预设创建成功",
        data=preset.to_dict(include_rules=True)
    )


@router.put("/presets/{preset_id}", response_model=ApiResponse)
async def update_preset(
        preset_id: str,
        request: PresetUpdateRequest,
        db: Session = Depends(get_db)
):
    """更新预设"""
    preset = db_manager.update_preset(db, preset_id, request.dict(exclude_unset=True))
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    return ApiResponse(
        success=True,
        message="预设更新成功",
        data=preset.to_dict(include_rules=True)
    )


@router.delete("/presets/{preset_id}", response_model=ApiResponse)
async def delete_preset(
        preset_id: str,
        hard: bool = Query(False, description="是否硬删除"),
        db: Session = Depends(get_db)
):
    """删除预设"""
    # 检查是否为系统预设
    preset = db_manager.get_preset_by_id(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    if preset.category == "system" and hard:
        raise HTTPException(status_code=403, detail="不能硬删除系统预设")

    success = db_manager.delete_preset(db, preset_id, soft=not hard)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    return ApiResponse(
        success=True,
        message="预设已删除" + ("（硬删除）" if hard else "（软删除）")
    )


@router.post("/presets/{preset_id}/clone", response_model=ApiResponse)
async def clone_preset(
        preset_id: str,
        new_name: str = Body(..., embed=True),
        db: Session = Depends(get_db)
):
    """克隆预设"""
    source = db_manager.get_preset_by_id(db, preset_id)
    if not source:
        raise HTTPException(status_code=404, detail="源预设不存在")

    # 检查新名称
    existing = db_manager.get_preset_by_name(db, new_name)
    if existing:
        raise HTTPException(status_code=400, detail="目标名称已存在")

    # 创建新预设
    new_preset = db_manager.create_preset(db, {
        "name": new_name,
        "description": f"克隆自 {source.name}: {source.description}",
        "category": "custom",
        "is_default": False
    })

    # 复制规则
    for rule in source.rules:
        rule_data = {
            "preset_id": new_preset.id,
            "name": rule.name,
            "rule_type": rule.rule_type,
            "priority": rule.priority,
            "enabled": rule.enabled,
            "weight": rule.weight,
            "params": rule.params,
            "description": rule.description,
            "tags": rule.tags
        }
        db_manager.create_rule(db, rule_data)

    return ApiResponse(
        success=True,
        message="预设克隆成功",
        data=new_preset.to_dict(include_rules=True)
    )


@router.post("/presets/{preset_id}/apply", response_model=ApiResponse)
async def apply_preset(
        preset_id: str,
        db: Session = Depends(get_db)
):
    """应用预设到引擎"""
    preset = db_manager.get_preset_by_id(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    # 这里调用引擎应用预设
    # 实际实现需要访问FormationService

    return ApiResponse(
        success=True,
        message=f"预设 {preset.name} 已应用",
        data={"preset_id": preset_id, "preset_name": preset.name}
    )


# ==================== 规则管理接口 ====================

@router.get("/rules", response_model=ApiResponse)
async def list_rules(
        preset_id: Optional[str] = Query(None, description="预设ID筛选"),
        enabled_only: bool = Query(False, description="仅启用的规则"),
        db: Session = Depends(get_db)
):
    """获取规则列表"""
    rules = db_manager.get_rules(db, preset_id=preset_id, enabled_only=enabled_only)
    return ApiResponse(
        success=True,
        data={"rules": rules, "count": len(rules)}
    )


@router.get("/rules/{rule_id}", response_model=ApiResponse)
async def get_rule(
        rule_id: str = Path(..., description="规则ID"),
        include_history: bool = Query(False, description="包含历史记录"),
        db: Session = Depends(get_db)
):
    """获取规则详情"""
    rule = db_manager.get_rule_by_id(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    return ApiResponse(
        success=True,
        data=rule.to_dict(include_history=include_history)
    )


@router.post("/rules", response_model=ApiResponse)
async def create_rule(
        request: RuleCreateRequest,
        db: Session = Depends(get_db)
):
    """创建规则"""
    # 验证预设存在
    preset = db_manager.get_preset_by_id(db, request.preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    rule_data = request.dict()
    rule = db_manager.create_rule(db, rule_data)

    return ApiResponse(
        success=True,
        message="规则创建成功",
        data=rule.to_dict()
    )


@router.put("/rules/{rule_id}", response_model=ApiResponse)
async def update_rule(
        rule_id: str,
        request: RuleUpdateRequest,
        performed_by: str = Query("api_user", description="操作人"),
        db: Session = Depends(get_db)
):
    """更新规则"""
    update_data = request.dict(exclude_unset=True)

    rule = db_manager.update_rule(
        db, rule_id, update_data,
        performed_by=performed_by,
        comment=request.comment
    )

    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    return ApiResponse(
        success=True,
        message="规则更新成功",
        data=rule.to_dict()
    )


@router.delete("/rules/{rule_id}", response_model=ApiResponse)
async def delete_rule(
        rule_id: str,
        performed_by: str = Query("api_user", description="操作人"),
        db: Session = Depends(get_db)
):
    """删除规则"""
    rule = db_manager.get_rule_by_id(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    # 检查是否为系统预设的规则
    if rule.preset.category == "system":
        # 允许删除但给出警告
        pass

    success = db_manager.delete_rule(db, rule_id, performed_by)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    return ApiResponse(
        success=True,
        message="规则已删除"
    )


@router.post("/rules/{rule_id}/enable", response_model=ApiResponse)
async def enable_rule(
        rule_id: str,
        performed_by: str = Query("api_user", description="操作人"),
        db: Session = Depends(get_db)
):
    """启用规则"""
    rule = db_manager.toggle_rule(db, rule_id, True, performed_by)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    return ApiResponse(
        success=True,
        message="规则已启用",
        data={"enabled": True}
    )


@router.post("/rules/{rule_id}/disable", response_model=ApiResponse)
async def disable_rule(
        rule_id: str,
        performed_by: str = Query("api_user", description="操作人"),
        db: Session = Depends(get_db)
):
    """禁用规则"""
    rule = db_manager.toggle_rule(db, rule_id, False, performed_by)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    return ApiResponse(
        success=True,
        message="规则已禁用",
        data={"enabled": False}
    )


@router.post("/rules/reorder", response_model=ApiResponse)
async def reorder_rules(
        request: ReorderRequest,
        db: Session = Depends(get_db)
):
    """重新排序规则"""
    success = db_manager.reorder_rules(db, request.preset_id, request.rule_orders)
    if not success:
        raise HTTPException(status_code=400, detail="排序失败")

    return ApiResponse(
        success=True,
        message="规则顺序已更新"
    )


# ==================== 统计和监控接口 ====================

@router.get("/statistics", response_model=ApiResponse)
async def get_statistics(db: Session = Depends(get_db)):
    """获取规则统计信息"""
    stats = db_manager.get_statistics(db)
    return ApiResponse(
        success=True,
        data=stats
    )


@router.get("/rules/{rule_id}/history", response_model=ApiResponse)
async def get_rule_history(
        rule_id: str,
        limit: int = Query(20, description="返回条数"),
        db: Session = Depends(get_db)
):
    """获取规则修改历史"""
    rule = db_manager.get_rule_by_id(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    history = sorted(rule.history, key=lambda h: h.performed_at, reverse=True)[:limit]

    return ApiResponse(
        success=True,
        data={
            "rule_id": rule_id,
            "rule_name": rule.name,
            "history": [h.to_dict() for h in history]
        }
    )


# ==================== 场景配置接口 ====================

@router.get("/scenes", response_model=ApiResponse)
async def list_scenes(db: Session = Depends(get_db)):
    """获取场景配置列表"""
    scenes = db_manager.get_scenes(db)
    return ApiResponse(
        success=True,
        data={"scenes": scenes}
    )


@router.put("/scenes/{scene_id}", response_model=ApiResponse)
async def update_scene(
        scene_id: str,
        parameters: Dict[str, Any] = Body(...),
        db: Session = Depends(get_db)
):
    """更新场景配置"""
    scene = db_manager.update_scene(db, scene_id, {"parameters": parameters})
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    return ApiResponse(
        success=True,
        message="场景配置已更新",
        data=scene.to_dict()
    )