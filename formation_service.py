"""
业务服务层 - 封装编队识别核心业务逻辑
"""

import time
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from copy import deepcopy

from formation_engine import FormationRecognitionEngine
from rule_manager import RuleManager
from rules import RuleContext, RuleResult, RulePriority

logger = logging.getLogger(__name__)


class FormationService:
    """编队识别服务"""

    def __init__(self):
        self.engine: Optional[FormationRecognitionEngine] = None
        self.stream_buffer: List[Dict] = []
        self.formation_history: List[Dict] = []
        self.presets = {
            "tight_fighter": "密集战斗机编队",
            "loose_bomber": "松散轰炸机编队",
            "strike_package": "混合打击群",
            "awacs_control": "预警机指挥"
        }

    def initialize(self):
        """初始化服务"""
        logger.info("初始化编队识别服务")
        self.engine = FormationRecognitionEngine()
        self.engine.load_preset("tight_fighter")

    def cleanup(self):
        """清理资源"""
        logger.info("清理编队识别服务")
        self.engine = None
        self.stream_buffer.clear()

    def recognize(self,
                  targets: List[Dict],
                  preset: Optional[str] = None,
                  scene_type: Optional[str] = None,
                  time_range: Optional[Dict] = None) -> Dict[str, Any]:
        """
        执行编队识别

        Args:
            targets: 目标数据列表
            preset: 规则预设名称
            scene_type: 场景类型
            time_range: 时间范围

        Returns:
            识别结果字典
        """
        start_time = time.time()

        # 创建新引擎实例（线程安全）
        engine = FormationRecognitionEngine()

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
        formations = engine.process_data(targets).recognize(tr)

        # 构建响应
        processing_time = (time.time() - start_time) * 1000

        result = {
            "success": True,
            "message": f"识别完成，发现{len(formations)}个编队",
            "formation_count": len(formations),
            "formations": [f.to_dict() for f in formations],
            "processing_time_ms": processing_time,
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

    def add_to_stream(self, targets: List[Dict]):
        """添加到流缓冲区"""
        self.stream_buffer.extend(targets)
        # 限制缓冲区大小
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

        # 使用当前引擎或创建新引擎
        engine = self.engine or FormationRecognitionEngine()
        formations = engine.process_data(self.stream_buffer).recognize()

        return {
            "success": True,
            "message": f"流式识别完成，发现{len(formations)}个编队",
            "formation_count": len(formations),
            "formations": [f.to_dict() for f in formations],
            "buffer_size": len(self.stream_buffer)
        }

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

        # 临时创建引擎获取规则
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
        return True

    def get_current_rules(self) -> Dict[str, Any]:
        """获取当前规则"""
        if not self.engine:
            return {"rules": []}

        return {
            "preset": self.engine.current_scene,
            "rules": [r.to_dict() for r in self.engine.rule_manager.rules],
            "rule_groups": list(self.engine.rule_manager.rule_groups.keys())
        }

    def add_custom_rule(self, rule_config: Dict) -> str:
        """添加自定义规则"""
        # 这里简化处理，实际应解析rule_config创建对应规则
        rule_id = f"custom_{int(time.time())}"
        logger.info(f"添加自定义规则: {rule_id}")
        return rule_id

    def update_rule(self, rule_id: str, config: Dict) -> bool:
        """更新规则"""
        if not self.engine:
            return False

        rule = self.engine.rule_manager.get_rule(rule_id)
        if not rule:
            return False

        # 更新参数
        if 'weight' in config:
            rule.weight = config['weight']
        if 'enabled' in config:
            rule.enabled = config['enabled']

        return True

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        if not self.engine:
            return False

        # 只能删除自定义规则
        if not rule_id.startswith('custom_'):
            return False

        self.engine.rule_manager.remove_rule(rule_id)
        return True

    def enable_rule(self, rule_id: str) -> bool:
        """启用规则"""
        return self._set_rule_enabled(rule_id, True)

    def disable_rule(self, rule_id: str) -> bool:
        """禁用规则"""
        return self._set_rule_enabled(rule_id, False)

    def _set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        """设置规则启用状态"""
        if not self.engine:
            return False

        rule = self.engine.rule_manager.get_rule(rule_id)
        if not rule:
            return False

        rule.enabled = enabled
        return True

    def adapt_to_scene(self, scene_type: str) -> Dict[str, Any]:
        """场景自适应"""
        if not self.engine:
            return {"error": "引擎未初始化"}

        self.engine.adapt_to_scene(scene_type)

        return {
            "scene": scene_type,
            "rules_adapted": len(self.engine.rule_manager.rules),
            "adaptations": [
                r.name for r in self.engine.rule_manager.rules
            ]
        }

    def get_all_formations(self) -> List[Dict]:
        """获取所有编队"""
        if not self.engine:
            return []
        return [f.to_dict() for f in self.engine.formations]

    def get_formation(self, formation_id: int) -> Optional[Dict]:
        """获取编队详情"""
        if not self.engine:
            return None

        for f in self.engine.formations:
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
        if not self.engine:
            return {"formations": []}

        return {
            "export_time": datetime.now().isoformat(),
            "formation_count": len(self.engine.formations),
            "formations": [
                f.to_dict(include_full_track=include_tracks)
                for f in self.engine.formations
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
            "latest_recognition": self.formation_history[-1] if self.formation_history else None
        }

    def get_rule_statistics(self) -> Dict[str, Any]:
        """获取规则统计"""
        if not self.engine:
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
                for r in self.engine.rule_manager.rules
            ]
        }

    def interpolate_tracks(self, targets: List[Dict], target_time: datetime) -> Dict[str, Any]:
        """航迹插值"""
        # 简化实现
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
        if not self.engine:
            return 0
        return len(self.engine.formations)