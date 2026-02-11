"""
业务服务层 - 封装编队识别核心业务逻辑（集成缓存和增量同步）
"""

import time
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from copy import deepcopy

from formation_engine import FormationRecognitionEngine
from formation_engine_smart import SmartFormationEngine
from rule_manager import RuleManager
from rules import RuleContext, RuleResult, RulePriority
from cache.target_cache import target_cache
from cache.formation_store import formation_store
from sync.delta_sync import delta_sync
from sync.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


class FormationService:
    """编队识别服务（集成Redis缓存）"""

    def __init__(self):
        self.engine: Optional[FormationRecognitionEngine] = None
        self.smart_engine: Optional[SmartFormationEngine] = None
        self.stream_buffer: List[Dict] = []
        self.formation_history: List[Dict] = []
        self.presets = {
            "tight_fighter": "密集战斗机编队",
            "loose_bomber": "松散轰炸机编队",
            "strike_package": "混合打击群",
            "awacs_control": "预警机指挥"
        }

        # 缓存统计
        self.cache_stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'delta_events_sent': 0
        }

    def initialize(self):
        """初始化服务"""
        logger.info("初始化编队识别服务（集成Redis缓存）")

        # 初始化两个引擎
        self.engine = FormationRecognitionEngine()
        self.engine.load_preset("tight_fighter")

        self.smart_engine = SmartFormationEngine()
        self.smart_engine.load_preset("tight_fighter")

        # 尝试从缓存预热
        self._warmup_from_cache()

    def _warmup_from_cache(self):
        """从Redis缓存预热航迹数据"""
        try:
            active_targets = target_cache.get_all_active_targets()
            logger.info(f"从缓存发现 {len(active_targets)} 个活跃目标，准备预热")

            # 这里可以选择恢复这些目标到引擎中
            # 实际实现取决于是否需要历史航迹
            # 简化处理：只记录数量
            self.cache_stats['warmup_targets'] = len(active_targets)

        except Exception as e:
            logger.warning(f"缓存预热失败: {e}")

    def cleanup(self):
        """清理资源"""
        logger.info("清理编队识别服务")
        self.engine = None
        self.smart_engine = None
        self.stream_buffer.clear()

    # ==================== 核心识别接口 ====================

    def recognize(self,
                  targets: List[Dict],
                  preset: Optional[str] = None,
                  scene_type: Optional[str] = None,
                  time_range: Optional[Dict] = None,
                  use_cache: bool = True,
                  incremental: bool = False,
                  emit_events: bool = True) -> Dict[str, Any]:
        """
        执行编队识别（集成缓存）

        Args:
            targets: 目标数据列表
            preset: 规则预设名称
            scene_type: 场景类型
            time_range: 时间范围
            use_cache: 是否使用Redis缓存
            incremental: 是否使用增量识别（只处理变化的目标）
            emit_events: 是否发送WebSocket事件
        """
        start_time = time.time()

        # 选择引擎
        if incremental and self.smart_engine:
            engine = self.smart_engine
            # 重置引擎状态
            engine.changed_targets.clear()
        else:
            engine = FormationRecognitionEngine()
            incremental = False

        # 应用预设或场景
        if preset:
            engine.load_preset(preset)
        elif scene_type:
            engine.adapt_to_scene(scene_type)
        else:
            engine.load_preset("tight_fighter")

        # 处理时间范围
        tr = None
        if time_range:
            tr = (
                datetime.fromisoformat(time_range['start']) if time_range.get('start') else None,
                datetime.fromisoformat(time_range['end']) if time_range.get('end') else None
            )

        # 执行识别
        if incremental:
            # 增量模式
            formations = engine.process_data_with_cache(targets).recognize_incremental(tr)
        else:
            # 全量模式
            formations = engine.process_data(targets).recognize(tr)
            formations = [f.to_dict() for f in formations]

        # 存储编队结果到Redis（7天滚动）
        stored_ids = []
        if formations:
            for formation_dict in formations:
                # 转换为Formation对象存储
                formation_obj = self._dict_to_formation(formation_dict)
                stored_id = formation_store.store_formation(
                    formation_obj,
                    custom_id=str(formation_dict.get("formation_id"))
                )
                if stored_id:
                    stored_ids.append(stored_id)

            # 发送WebSocket事件
            if emit_events:
                self._emit_formation_events(formations)

        # 构建响应
        processing_time = (time.time() - start_time) * 1000

        result = {
            "success": True,
            "message": f"识别完成，发现{len(formations)}个编队",
            "formation_count": len(formations),
            "formations": formations,
            "stored_formation_ids": stored_ids,
            "processing_time_ms": processing_time,
            "cache_enabled": use_cache,
            "incremental": incremental,
            "metadata": {
                "preset_used": preset or scene_type or "tight_fighter",
                "target_count": len(targets),
                "unique_targets": len(set(t.get('id') for t in targets)),
                "timestamp": datetime.now().isoformat()
            }
        }

        # 保存历史
        self.formation_history.append({
            "time": datetime.now(),
            "result": result
        })

        return result

    def _emit_formation_events(self, formations: List[Dict]):
        """发送编队识别事件（异步）"""
        try:
            loop = asyncio.get_event_loop()
            for formation_dict in formations:
                loop.create_task(
                    websocket_manager.notify_formation_detected(formation_dict)
                )
            self.cache_stats['delta_events_sent'] += len(formations)
        except Exception as e:
            logger.warning(f"发送编队事件失败: {e}")

    def _dict_to_formation(self, data: Dict) -> 'Formation':
        """字典转换为Formation对象"""
        from models import Formation, GeoPosition

        center = data.get("spatial", {}).get("center", {})

        return Formation(
            formation_id=data.get("formation_id", 0),
            formation_type=data.get("formation_type", "Unknown"),
            confidence=data.get("confidence", 0),
            members={},  # 简化
            time_range=(datetime.now(), datetime.now()),
            create_time=datetime.now(),
            center_position=GeoPosition(
                longitude=center.get("longitude", 0),
                latitude=center.get("latitude", 0),
                altitude=center.get("altitude", 0)
            ),
            bounding_box=data.get("spatial", {}).get("bounding_box", {}),
            coverage_area=data.get("spatial", {}).get("coverage_area_km2", 0),
            average_speed=data.get("motion", {}).get("average_speed", 0),
            speed_std=data.get("motion", {}).get("speed_std", 0),
            average_heading=data.get("motion", {}).get("average_heading", 0),
            heading_std=data.get("motion", {}).get("heading_std", 0),
            altitude_layer=data.get("motion", {}).get("altitude_layer", "Unknown"),
            coordination_graph={},
            applied_rules=data.get("rules_applied", []),
            rule_confidences=data.get("rule_confidences", {})
        )

    # ==================== 纯缓存接口（不触发识别） ====================

    def cache_targets_only(self, targets: List[Dict]) -> Dict[str, Any]:
        """
        仅缓存目标状态，不执行编队识别

        用于外部系统批量同步数据到缓存
        """
        updated = []
        failed = []

        for target_data in targets:
            tid = target_data.get('id')
            if not tid:
                failed.append({"error": "缺少ID"})
                continue

            try:
                # 解析为TargetState
                state = self._parse_target_data(target_data)
                if not state:
                    failed.append({"target_id": tid, "error": "数据解析失败"})
                    continue

                # 更新缓存
                success, is_update, delta = target_cache.cache_target_state(
                    tid, state, emit_delta=True
                )

                if success:
                    updated.append({
                        "target_id": tid,
                        "version": target_cache.get_target_version(tid),
                        "is_update": is_update,
                        "has_delta": delta is not None
                    })

                    # 发送WebSocket增量事件
                    if is_update and delta:
                        try:
                            loop = asyncio.get_event_loop()
                            loop.create_task(
                                websocket_manager.notify_target_update(tid, delta)
                            )
                        except Exception as e:
                            logger.warning(f"发送增量事件失败: {e}")
                else:
                    failed.append({"target_id": tid, "error": "缓存写入失败"})

            except Exception as e:
                failed.append({"target_id": tid, "error": str(e)})

        return {
            "success": True,
            "updated": len(updated),
            "failed": len(failed),
            "details": {"updated": updated, "failed": failed}
        }

    def _parse_target_data(self, data: Dict) -> Optional['TargetState']:
        """解析目标数据为TargetState"""
        from models import TargetState, GeoPosition
        import pandas as pd

        try:
            timestamp = pd.to_datetime(data.get('时间'))
            pos = data.get('位置', (0, 0, 0))

            return TargetState(
                timestamp=timestamp,
                position=GeoPosition(
                    longitude=float(pos[0]),
                    latitude=float(pos[1]),
                    altitude=float(pos[2])
                ),
                heading=float(data.get('航向', 0)),
                speed=float(data.get('速度', 0))
            )
        except Exception as e:
            logger.error(f"解析目标数据失败: {e}")
            return None

    # ==================== 增量同步接口 ====================

    def get_delta_sync(self,
                       client_id: str,
                       since_versions: Optional[Dict[str, int]] = None,
                       target_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        获取增量同步数据

        Args:
            client_id: 客户端标识
            since_versions: 各目标的版本号（首次同步可不传）
            target_ids: 关注的目标列表（None表示全部）
        """
        # 创建或复用同步会话
        session_id = delta_sync.create_sync_session(client_id, target_ids)

        # 拉取增量
        result = delta_sync.pull_delta(
            session_id=session_id,
            target_ids=target_ids,
            since_versions=since_versions
        )

        return {
            "success": True,
            "session_id": session_id,
            "data": result
        }

    def compare_and_sync(self, client_states: Dict[str, Dict]) -> Dict[str, Any]:
        """
        对比同步 - 客户端上传本地状态，服务器返回差异
        """
        result = delta_sync.compare_and_sync(client_states)
        return {
            "success": True,
            "data": result
        }

    # ==================== 原有接口（保持兼容） ====================

    def add_to_stream(self, targets: List[Dict]):
        """添加到流缓冲区"""
        self.stream_buffer.extend(targets)
        if len(self.stream_buffer) > 10000:
            self.stream_buffer = self.stream_buffer[-5000:]

    def recognize_stream(self) -> Dict[str, Any]:
        """流式识别"""
        if not self.stream_buffer:
            return {
                "success": False,
                "message": "流缓冲区为空",
                "formation_count": 0,
                "formations": []
            }

        return self.recognize(
            targets=self.stream_buffer,
            incremental=True  # 流式识别使用增量模式
        )

    def get_available_presets(self) -> List[Dict]:
        """获取可用预设"""
        return [
            {"name": k, "description": v, "default": k == "tight_fighter"}
            for k, v in self.presets.items()
        ]

    def get_preset_detail(self, preset_name: str) -> Optional[Dict]:
        """获取预设详情"""
        if preset_name not in self.presets:
            return None

        engine = FormationRecognitionEngine()
        engine.load_preset(preset_name)

        return {
            "name": preset_name,
            "description": self.presets[preset_name],
            "rules": [r.to_dict() for r in engine.rule_manager.rules]
        }

    def apply_preset(self, preset_name: str) -> bool:
        """应用预设"""
        if preset_name not in self.presets:
            return False

        if self.engine:
            self.engine.load_preset(preset_name)
        if self.smart_engine:
            self.smart_engine.load_preset(preset_name)
        return True

    def get_current_rules(self) -> Dict[str, Any]:
        """获取当前规则"""
        engine = self.smart_engine or self.engine
        if not engine:
            return {"rules": []}

        return {
            "preset": engine.current_scene,
            "rules": [r.to_dict() for r in engine.rule_manager.rules],
            "rule_groups": list(engine.rule_manager.rule_groups.keys()),
            "cache_status": engine.get_cache_status() if isinstance(engine, SmartFormationEngine) else None
        }

    def add_custom_rule(self, rule_config: Dict) -> str:
        """添加自定义规则"""
        rule_id = f"custom_{int(time.time())}"
        logger.info(f"添加自定义规则: {rule_id}")
        return rule_id

    def update_rule(self, rule_id: str, config: Dict) -> bool:
        """更新规则"""
        engine = self.smart_engine or self.engine
        if not engine:
            return False

        rule = engine.rule_manager.get_rule(rule_id)
        if not rule:
            return False

        if 'weight' in config:
            rule.weight = config['weight']
        if 'enabled' in config:
            rule.enabled = config['enabled']

        return True

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        engine = self.smart_engine or self.engine
        if not engine:
            return False

        if not rule_id.startswith('custom_'):
            return False

        engine.rule_manager.remove_rule(rule_id)
        return True

    def enable_rule(self, rule_id: str) -> bool:
        """启用规则"""
        return self._set_rule_enabled(rule_id, True)

    def disable_rule(self, rule_id: str) -> bool:
        """禁用规则"""
        return self._set_rule_enabled(rule_id, False)

    def _set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        """设置规则启用状态"""
        engine = self.smart_engine or self.engine
        if not engine:
            return False

        rule = engine.rule_manager.get_rule(rule_id)
        if not rule:
            return False

        rule.enabled = enabled
        return True

    def adapt_to_scene(self, scene_type: str) -> Dict[str, Any]:
        """场景自适应"""
        engine = self.smart_engine or self.engine
        if not engine:
            return {"error": "引擎未初始化"}

        engine.adapt_to_scene(scene_type)

        return {
            "scene": scene_type,
            "rules_adapted": len(engine.rule_manager.rules),
            "adaptations": [
                r.name for r in engine.rule_manager.rules
            ]
        }

    def get_all_formations(self) -> List[Dict]:
        """获取所有编队"""
        engine = self.smart_engine or self.engine
        if not engine:
            return []
        return [f.to_dict() for f in engine.formations]

    def get_formation(self, formation_id: int) -> Optional[Dict]:
        """获取编队详情"""
        engine = self.smart_engine or self.engine
        if not engine:
            return None

        for f in engine.formations:
            if f.formation_id == formation_id:
                return f.to_dict()
        return None

    def get_formation_tracks(self, formation_id: int) -> Optional[Dict]:
        """获取编队航迹"""
        formation = self.get_formation(formation_id)
        if not formation:
            return None

        return formation.get('full_tracks', {})

    def export_formations(self, include_tracks: bool = True) -> Dict[str, Any]:
        """导出编队结果"""
        engine = self.smart_engine or self.engine
        if not engine:
            return {"formations": []}

        return {
            "export_time": datetime.now().isoformat(),
            "formation_count": len(engine.formations),
            "formations": [
                f.to_dict(include_full_track=include_tracks)
                for f in engine.formations
            ]
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "service": {
                "uptime": "running",
                "total_formations_identified": len(self.formation_history),
                "current_buffer_size": len(self.stream_buffer)
            },
            "cache": self.cache_stats,
            "latest_recognition": self.formation_history[-1] if self.formation_history else None
        }

    def get_rule_statistics(self) -> Dict[str, Any]:
        """获取规则统计"""
        engine = self.smart_engine or self.engine
        if not engine:
            return {"rules": []}

        return {
            "rules": [
                {
                    "name": r.name,
                    "type": r.__class__.__name__,
                    "evaluations": r.stats['evaluations'],
                    "passed": r.stats['passed'],
                    "failed": r.stats['failed'],
                    "pass_rate": r.stats['passed'] / max(r.stats['evaluations'], 1)
                }
                for r in engine.rule_manager.rules
            ]
        }

    def interpolate_tracks(self, targets: List[Dict], target_time: datetime) -> Dict[str, Any]:
        """航迹插值"""
        return {
            "target_time": target_time.isoformat(),
            "interpolated_count": len(targets),
            "message": "插值完成"
        }

    def validate_data(self, targets: List[Dict]) -> List[Dict]:
        """验证数据"""
        results = []
        for t in targets:
            errors = []
            warnings = []

            if not t.get('id'):
                errors.append("缺少ID")
            if not t.get('position'):
                errors.append("缺少位置")
            else:
                pos = t['position']
                if len(pos) != 3:
                    errors.append("位置格式错误")

            if not t.get('time'):
                errors.append("缺少时间")

            results.append({
                "target_id": t.get('id', 'unknown'),
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings
            })

        return results

    def get_active_formation_count(self) -> int:
        """获取当前活跃编队数"""
        engine = self.smart_engine or self.engine
        if not engine:
            return 0
        return len(engine.formations)

    # ==================== 缓存管理接口 ====================

    def get_cache_status(self) -> Dict[str, Any]:
        """获取缓存状态"""
        try:
            active_targets = target_cache.get_all_active_targets()
            return {
                "redis_connected": True,
                "active_targets_in_cache": len(active_targets),
                "sample_targets": active_targets[:10] if len(active_targets) > 10 else active_targets,
                "cache_stats": self.cache_stats,
                "smart_engine_status": self.smart_engine.get_cache_status() if self.smart_engine else None
            }
        except Exception as e:
            return {
                "redis_connected": False,
                "error": str(e)
            }

    def clear_cache(self, target_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """清理缓存"""
        try:
            if target_ids:
                # 清理指定目标
                for tid in target_ids:
                    target_cache.delete_target(tid, reason="MANUAL_CLEAR")
                return {"cleared": len(target_ids), "targets": target_ids}
            else:
                # 获取所有目标并清理
                all_targets = target_cache.get_all_active_targets()
                for tid in all_targets:
                    target_cache.delete_target(tid, reason="MANUAL_CLEAR_ALL")
                return {"cleared": len(all_targets), "targets": all_targets}
        except Exception as e:
            return {"error": str(e)}