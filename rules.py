"""
规则引擎 - 支持自定义规则的编队识别规则系统
"""
import math
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional, Any, Tuple
from collections import defaultdict
from datetime import datetime

from models import RulePriority, TargetState, TargetAttributes, PlatformType


@dataclass
class RuleContext:
    """规则评估上下文"""
    track1: Any  # TargetTrack
    track2: Any
    state1: TargetState
    state2: TargetState
    features1: Optional[Any] = None  # MotionFeatures
    features2: Optional[Any] = None
    current_time: Optional[datetime] = None
    global_params: Dict[str, Any] = field(default_factory=dict)
    _cache: Dict[str, Any] = field(default_factory=dict)

    def get_cache(self, key: str) -> Any:
        return self._cache.get(key)

    def set_cache(self, key: str, value: Any):
        self._cache[key] = value


@dataclass
class RuleResult:
    """规则评估结果"""
    passed: bool  # 是否通过
    confidence: float  # 置信度贡献（0-1）
    priority: RulePriority  # 优先级
    message: str  # 评估信息
    details: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self):
        return self.passed


class BaseRule(ABC):
    """规则基类 - 所有具体规则的父类"""

    def __init__(self, name: str, priority: RulePriority = RulePriority.MEDIUM,
                 enabled: bool = True, weight: float = 1.0):
        self.name = name
        self.priority = priority
        self.enabled = enabled
        self.weight = weight
        self.metadata: Dict[str, Any] = {}
        self.stats = {'evaluations': 0, 'passed': 0, 'failed': 0}

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """评估规则 - 子类必须实现"""
        pass

    def enable(self):
        """启用规则"""
        self.enabled = True
        return self

    def disable(self):
        """禁用规则"""
        self.enabled = False
        return self

    def set_weight(self, weight: float):
        """设置权重"""
        self.weight = weight
        return self

    def set_metadata(self, **kwargs):
        """设置元数据"""
        self.metadata.update(kwargs)
        return self

    def update_stats(self, passed: bool):
        """更新统计"""
        self.stats['evaluations'] += 1
        if passed:
            self.stats['passed'] += 1
        else:
            self.stats['failed'] += 1

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            'type': self.__class__.__name__,
            'name': self.name,
            'priority': self.priority.name,
            'enabled': self.enabled,
            'weight': self.weight,
            'metadata': self.metadata,
            'stats': self.stats,
            'params': self._get_params()
        }

    def _get_params(self) -> Dict[str, Any]:
        """获取参数 - 子类重写"""
        return {}

    @classmethod
    def from_dict(cls, data: Dict) -> 'BaseRule':
        """从字典反序列化 - 子类重写"""
        raise NotImplementedError


# ==================== 具体规则实现 ====================

class DistanceRule(BaseRule):
    """距离规则"""

    def __init__(self, name: str = "DistanceRule",
                 min_distance: float = 0.0,
                 max_distance: float = 5000.0,
                 priority: RulePriority = RulePriority.CRITICAL,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.min_distance = min_distance
        self.max_distance = max_distance

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        dist = context.state1.position.distance_to(context.state2.position)

        if dist < self.min_distance:
            return RuleResult(
                False, 0.0, self.priority,
                f"距离过近: {dist:.0f}m < {self.min_distance:.0f}m",
                {'distance': dist, 'violation': 'too_close'}
            )

        if dist > self.max_distance:
            return RuleResult(
                False, 0.0, self.priority,
                f"距离过远: {dist:.0f}m > {self.max_distance:.0f}m",
                {'distance': dist, 'violation': 'too_far'}
            )

        # 计算置信度（距离越接近最优值越高）
        optimal = (self.min_distance + self.max_distance) / 2
        confidence = 1.0 - abs(dist - optimal) / (self.max_distance - self.min_distance)
        confidence = max(0.5, min(1.0, confidence))

        return RuleResult(
            True, confidence * self.weight, self.priority,
            f"距离满足: {dist:.0f}m",
            {'distance': dist, 'optimal_distance': optimal}
        )

    def _get_params(self) -> Dict[str, Any]:
        return {
            'min_distance': self.min_distance,
            'max_distance': self.max_distance
        }


class AltitudeRule(BaseRule):
    """高度规则"""

    def __init__(self, name: str = "AltitudeRule",
                 max_diff: float = 500.0,
                 same_layer_preferred: bool = True,
                 priority: RulePriority = RulePriority.HIGH,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.max_diff = max_diff
        self.same_layer_preferred = same_layer_preferred

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        diff = context.state1.position.vertical_distance_to(context.state2.position)

        if diff > self.max_diff:
            return RuleResult(
                False, 0.0, self.priority,
                f"高度差过大: {diff:.0f}m > {self.max_diff:.0f}m",
                {'altitude_diff': diff}
            )

        confidence = 1.0 - diff / self.max_diff

        # 同高度层额外奖励
        if self.same_layer_preferred:
            layer1 = self._get_altitude_layer(context.state1.position.altitude)
            layer2 = self._get_altitude_layer(context.state2.position.altitude)
            if layer1 == layer2:
                confidence = min(1.0, confidence + 0.1)

        return RuleResult(
            True, confidence * self.weight, self.priority,
            f"高度差满足: {diff:.0f}m",
            {'altitude_diff': diff}
        )

    @staticmethod
    def _get_altitude_layer(altitude: float) -> str:
        """获取高度层"""
        if altitude < 1000:
            return "UltraLow"
        elif altitude < 3000:
            return "Low"
        elif altitude < 7000:
            return "Medium"
        elif altitude < 12000:
            return "High"
        else:
            return "VeryHigh"

    def _get_params(self) -> Dict[str, Any]:
        return {
            'max_diff': self.max_diff,
            'same_layer_preferred': self.same_layer_preferred
        }


class SpeedRule(BaseRule):
    """速度规则"""

    def __init__(self, name: str = "SpeedRule",
                 max_diff: float = 30.0,
                 max_ratio: float = 1.3,
                 priority: RulePriority = RulePriority.HIGH,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.max_diff = max_diff
        self.max_ratio = max_ratio

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        speed1, speed2 = context.state1.speed, context.state2.speed

        # 绝对差值检查
        diff = abs(speed1 - speed2)
        if diff > self.max_diff:
            return RuleResult(
                False, 0.0, self.priority,
                f"速度差过大: {diff:.1f}m/s > {self.max_diff:.1f}m/s",
                {'speed_diff': diff, 'speed1': speed1, 'speed2': speed2}
            )

        # 比值检查
        ratio = max(speed1, speed2) / max(min(speed1, speed2), 1.0)
        if ratio > self.max_ratio:
            return RuleResult(
                False, 0.0, self.priority,
                f"速度比过大: {ratio:.2f} > {self.max_ratio:.2f}",
                {'speed_ratio': ratio}
            )

        confidence = 1.0 - diff / self.max_diff

        return RuleResult(
            True, confidence * self.weight, self.priority,
            f"速度匹配: {speed1:.1f} vs {speed2:.1f} m/s",
            {'speed_diff': diff, 'speed_ratio': ratio}
        )

    def _get_params(self) -> Dict[str, Any]:
        return {
            'max_diff': self.max_diff,
            'max_ratio': self.max_ratio
        }


class HeadingRule(BaseRule):
    """航向规则"""

    def __init__(self, name: str = "HeadingRule",
                 max_diff: float = 30.0,
                 allow_reciprocal: bool = False,
                 priority: RulePriority = RulePriority.HIGH,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.max_diff = max_diff
        self.allow_reciprocal = allow_reciprocal

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        h1, h2 = context.state1.heading, context.state2.heading

        # 计算最小角度差
        diff = abs(h1 - h2)
        diff = min(diff, 360 - diff)

        # 检查相反航向
        reciprocal_diff = abs(diff - 180)

        if diff <= self.max_diff:
            confidence = 1.0 - diff / self.max_diff
            return RuleResult(
                True, confidence * self.weight, self.priority,
                f"航向一致: {diff:.1f}°",
                {'heading_diff': diff, 'type': 'same_direction'}
            )
        elif self.allow_reciprocal and reciprocal_diff <= self.max_diff:
            confidence = 0.7 * (1.0 - reciprocal_diff / self.max_diff)
            return RuleResult(
                True, confidence * self.weight, self.priority,
                f"相反航向: {diff:.1f}° (允许)",
                {'heading_diff': diff, 'type': 'reciprocal'}
            )
        else:
            return RuleResult(
                False, 0.0, self.priority,
                f"航向偏差过大: {diff:.1f}° > {self.max_diff:.1f}°",
                {'heading_diff': diff}
            )

    def _get_params(self) -> Dict[str, Any]:
        return {
            'max_diff': self.max_diff,
            'allow_reciprocal': self.allow_reciprocal
        }


class AttributeRule(BaseRule):
    """属性规则（国家、联盟、战区）"""

    def __init__(self, name: str = "AttributeRule",
                 hostile_check: bool = True,
                 same_alliance: bool = True,
                 same_theater: bool = True,
                 priority: RulePriority = RulePriority.CRITICAL,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.hostile_check = hostile_check
        self.same_alliance = same_alliance
        self.same_theater = same_theater

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        attr1 = context.track1.attributes
        attr2 = context.track2.attributes

        # 敌对检查
        if self.hostile_check and attr1.nation and attr2.nation:
            hostile_pairs = {('RED', 'BLUE'), ('BLUE', 'RED'), ('ENEMY', 'FRIEND')}
            if (attr1.nation, attr2.nation) in hostile_pairs:
                return RuleResult(
                    False, 0.0, RulePriority.CRITICAL,
                    f"敌对关系: {attr1.nation} vs {attr2.nation}",
                    {'nation1': attr1.nation, 'nation2': attr2.nation, 'type': 'hostile'}
                )

        # 联盟检查
        if self.same_alliance and attr1.alliance and attr2.alliance:
            if attr1.alliance != attr2.alliance:
                return RuleResult(
                    False, 0.0, self.priority,
                    f"联盟不同: {attr1.alliance} vs {attr2.alliance}",
                    {'alliance1': attr1.alliance, 'alliance2': attr2.alliance}
                )

        # 战区检查
        if self.same_theater and attr1.theater and attr2.theater:
            if attr1.theater != attr2.theater:
                return RuleResult(
                    False, 0.0, self.priority,
                    f"战区不同: {attr1.theater} vs {attr2.theater}",
                    {'theater1': attr1.theater, 'theater2': attr2.theater}
                )

        return RuleResult(
            True, 1.0 * self.weight, self.priority,
            "属性相容",
            {
                'nation': f"{attr1.nation}-{attr2.nation}",
                'alliance': f"{attr1.alliance}-{attr2.alliance}",
                'theater': f"{attr1.theater}-{attr2.theater}"
            }
        )

    def _get_params(self) -> Dict[str, Any]:
        return {
            'hostile_check': self.hostile_check,
            'same_alliance': self.same_alliance,
            'same_theater': self.same_theater
        }


class PlatformTypeRule(BaseRule):
    """平台类型规则"""

    def __init__(self, name: str = "PlatformTypeRule",
                 allowed_pairs: Optional[List[Tuple[str, str]]] = None,
                 forbidden_pairs: Optional[List[Tuple[str, str]]] = None,
                 priority: RulePriority = RulePriority.MEDIUM,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self.allowed_pairs = allowed_pairs or []
        self.forbidden_pairs = forbidden_pairs or []

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        t1 = context.track1.attributes.target_type
        t2 = context.track2.attributes.target_type

        if not t1 or not t2:
            return RuleResult(True, 0.8, self.priority, "类型未知")

        type_pair = (t1.value, t2.value)
        reverse_pair = (t2.value, t1.value)

        # 检查禁止组合
        for forbidden in self.forbidden_pairs:
            if type_pair == forbidden or reverse_pair == forbidden:
                return RuleResult(
                    False, 0.0, self.priority,
                    f"禁止组合: {type_pair}",
                    {'type_pair': type_pair, 'forbidden': True}
                )

        # 检查推荐组合
        for allowed in self.allowed_pairs:
            if type_pair == allowed or reverse_pair == allowed:
                return RuleResult(
                    True, 1.2 * self.weight, self.priority,
                    f"推荐组合: {type_pair}",
                    {'type_pair': type_pair, 'preferred': True}
                )

        return RuleResult(
            True, 0.9 * self.weight, self.priority,
            f"组合: {type_pair}",
            {'type_pair': type_pair}
        )

    def _get_params(self) -> Dict[str, Any]:
        return {
            'allowed_pairs': self.allowed_pairs,
            'forbidden_pairs': self.forbidden_pairs
        }


class CustomRule(BaseRule):
    """自定义规则（通过函数）"""

    def __init__(self, name: str,
                 evaluator: Callable[[RuleContext], RuleResult],
                 priority: RulePriority = RulePriority.MEDIUM,
                 enabled: bool = True, weight: float = 1.0):
        super().__init__(name, priority, enabled, weight)
        self._evaluator = evaluator

    def evaluate(self, context: RuleContext) -> RuleResult:
        if not self.enabled:
            return RuleResult(True, 1.0, self.priority, "规则已禁用")

        try:
            result = self._evaluator(context)
            result.confidence *= self.weight
            return result
        except Exception as e:
            return RuleResult(
                False, 0.0, self.priority,
                f"规则执行错误: {str(e)}",
                {'error': str(e)}
            )