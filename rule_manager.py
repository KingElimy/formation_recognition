"""
规则管理器 - 规则的注册、管理和批量执行
"""
import json
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict

from models import RulePriority
from rules import (
    BaseRule, RuleContext, RuleResult,
    DistanceRule, AltitudeRule, SpeedRule, HeadingRule,
    AttributeRule, PlatformTypeRule, CustomRule
)


class RuleManager:
    """规则管理器"""

    # 规则类型注册表
    RULE_TYPES = {
        'DistanceRule': DistanceRule,
        'AltitudeRule': AltitudeRule,
        'SpeedRule': SpeedRule,
        'HeadingRule': HeadingRule,
        'AttributeRule': AttributeRule,
        'PlatformTypeRule': PlatformTypeRule,
        'CustomRule': CustomRule
    }

    def __init__(self):
        self.rules: List[BaseRule] = []
        self.rule_groups: Dict[str, List[BaseRule]] = defaultdict(list)
        self.presets: Dict[str, List[Dict]] = {}
        self.evaluation_history: List[Dict] = []

    def register_rule_type(self, name: str, rule_class: type):
        """注册新的规则类型"""
        if not issubclass(rule_class, BaseRule):
            raise ValueError(f"规则类必须继承BaseRule: {rule_class}")
        self.RULE_TYPES[name] = rule_class
        return self

    def add_rule(self, rule: BaseRule, group: str = "default") -> 'RuleManager':
        """添加规则"""
        self.rules.append(rule)
        self.rule_groups[group].append(rule)
        return self

    def add_rules(self, rules: List[BaseRule], group: str = "default") -> 'RuleManager':
        """批量添加规则"""
        for rule in rules:
            self.add_rule(rule, group)
        return self

    def remove_rule(self, name: str) -> 'RuleManager':
        """移除规则"""
        self.rules = [r for r in self.rules if r.name != name]
        for group in self.rule_groups.values():
            group[:] = [r for r in group if r.name != name]
        return self

    def get_rule(self, name: str) -> Optional[BaseRule]:
        """获取规则"""
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def get_group(self, group: str) -> List[BaseRule]:
        """获取规则组"""
        return self.rule_groups.get(group, [])

    def enable_group(self, group: str) -> 'RuleManager':
        """启用规则组"""
        for rule in self.get_group(group):
            rule.enable()
        return self

    def disable_group(self, group: str) -> 'RuleManager':
        """禁用规则组"""
        for rule in self.get_group(group):
            rule.disable()
        return self

    def clear(self) -> 'RuleManager':
        """清空所有规则"""
        self.rules.clear()
        self.rule_groups.clear()
        return self

    def evaluate_pair(self, context: RuleContext) -> Dict[str, Any]:
        """
        评估目标对 - 执行所有规则

        返回: 综合评估结果
        """
        results = []
        critical_passed = True
        total_confidence = 0.0
        total_weight = 0

        # 按优先级排序
        sorted_rules = sorted(self.rules, key=lambda r: r.priority.value)

        for rule in sorted_rules:
            if not rule.enabled:
                continue

            result = rule.evaluate(context)
            rule.update_stats(result.passed)

            results.append({
                'rule_name': rule.name,
                'rule_type': rule.__class__.__name__,
                'priority': rule.priority.name,
                'passed': result.passed,
                'confidence': result.confidence,
                'message': result.message,
                'details': result.details
            })

            # 关键规则失败直接返回
            if result.priority == RulePriority.CRITICAL and not result.passed:
                critical_passed = False
                break

            if result.passed:
                total_confidence += result.confidence * rule.priority.value
                total_weight += rule.priority.value

        # 计算综合置信度
        if not critical_passed:
            overall_confidence = 0.0
        else:
            overall_confidence = (total_confidence / max(total_weight, 1)) if total_weight > 0 else 0.0

        evaluation = {
            'passed': critical_passed and all(r['passed'] for r in results),
            'confidence': overall_confidence,
            'results': results,
            'summary': {
                'total': len(results),
                'passed': sum(1 for r in results if r['passed']),
                'failed': sum(1 for r in results if not r['passed']),
                'critical_failed': not critical_passed
            }
        }

        self.evaluation_history.append(evaluation)
        return evaluation

    def save_preset(self, name: str) -> 'RuleManager':
        """保存当前规则为预设"""
        self.presets[name] = [rule.to_dict() for rule in self.rules]
        return self

    def load_preset(self, name: str) -> 'RuleManager':
        """加载预设"""
        if name not in self.presets:
            raise ValueError(f"未知预设: {name}")

        self.clear()
        for rule_data in self.presets[name]:
            rule_type = rule_data.get('type')
            if rule_type in self.RULE_TYPES:
                # 简化版反序列化
                cls = self.RULE_TYPES[rule_type]
                if rule_type == 'DistanceRule':
                    p = rule_data.get('params', {})
                    rule = cls(rule_data['name'], p.get('min_distance', 0),
                               p.get('max_distance', 5000),
                               RulePriority[rule_data.get('priority', 'CRITICAL')])
                    rule.enabled = rule_data.get('enabled', True)
                    rule.weight = rule_data.get('weight', 1.0)
                    self.add_rule(rule)

        return self

    def create_preset(self, preset_type: str) -> 'RuleManager':
        """创建预设规则集"""
        self.clear()

        if preset_type == "tight_fighter":
            # 密集战斗机编队
            self.add_rules([
                AttributeRule("HostileCheck", True, True, RulePriority.CRITICAL),
                DistanceRule("TightDist", 0, 3000, RulePriority.CRITICAL),
                AltitudeRule("TightAlt", 300, True, RulePriority.HIGH),
                SpeedRule("TightSpeed", 20, 1.1, RulePriority.HIGH),
                HeadingRule("TightHeading", 15, False, RulePriority.HIGH),
            ], "tight_fighter")

        elif preset_type == "loose_bomber":
            # 松散轰炸机编队
            self.add_rules([
                AttributeRule("AllianceCheck", True, True, RulePriority.CRITICAL),
                DistanceRule("LooseDist", 3000, 10000, RulePriority.CRITICAL),
                AltitudeRule("LooseAlt", 1000, True, RulePriority.HIGH),
                SpeedRule("LooseSpeed", 30, 1.2, RulePriority.HIGH),
                HeadingRule("LooseHeading", 20, False, RulePriority.HIGH),
            ], "loose_bomber")

        elif preset_type == "strike_package":
            # 混合打击群
            self.add_rules([
                AttributeRule("CoalitionCheck", True, True, RulePriority.CRITICAL),
                DistanceRule("PackageDist", 5000, 20000, RulePriority.CRITICAL),
                AltitudeRule("PackageAlt", 2000, False, RulePriority.MEDIUM),
                SpeedRule("PackageSpeed", 100, 2.0, RulePriority.MEDIUM),
                HeadingRule("PackageHeading", 60, True, RulePriority.MEDIUM),
                PlatformTypeRule("MixedTypes",
                                 allowed_pairs=[("Fighter", "Bomber"), ("Fighter", "EW"), ("AWACS", "Fighter")],
                                 priority=RulePriority.MEDIUM)
            ], "strike_package")

        elif preset_type == "awacs_control":
            # 预警机指挥
            self.add_rules([
                AttributeRule("AllianceCheck", True, True, RulePriority.CRITICAL),
                DistanceRule("AWACSDist", 50000, 150000, RulePriority.CRITICAL),
                AltitudeRule("AWACSAlt", 3000, False, RulePriority.HIGH),
            ], "awacs_control")

        return self

    def export_to_json(self, filepath: str):
        """导出规则到JSON"""
        data = {
            'rules': [rule.to_dict() for rule in self.rules],
            'presets': self.presets
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def import_from_json(self, filepath: str) -> 'RuleManager':
        """从JSON导入规则"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.clear()

        for rule_data in data.get('rules', []):
            rule_type = rule_data.get('type')
            if rule_type in self.RULE_TYPES:
                cls = self.RULE_TYPES[rule_type]
                try:
                    # 简化版反序列化
                    if rule_type == 'DistanceRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('min_distance', 0),
                                   p.get('max_distance', 5000),
                                   RulePriority[rule_data.get('priority', 'CRITICAL')])
                    elif rule_type == 'AltitudeRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('max_diff', 500),
                                   p.get('same_layer_preferred', True),
                                   RulePriority[rule_data.get('priority', 'HIGH')])
                    elif rule_type == 'SpeedRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('max_diff', 30),
                                   p.get('max_ratio', 1.3),
                                   RulePriority[rule_data.get('priority', 'HIGH')])
                    elif rule_type == 'HeadingRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('max_diff', 30),
                                   p.get('allow_reciprocal', False),
                                   RulePriority[rule_data.get('priority', 'HIGH')])
                    elif rule_type == 'AttributeRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('hostile_check', True),
                                   p.get('same_alliance', True),
                                   RulePriority[rule_data.get('priority', 'CRITICAL')])
                    elif rule_type == 'PlatformTypeRule':
                        p = rule_data.get('params', {})
                        rule = cls(rule_data['name'], p.get('allowed_pairs', []),
                                   p.get('forbidden_pairs', []),
                                   RulePriority[rule_data.get('priority', 'MEDIUM')])
                    else:
                        continue

                    rule.enabled = rule_data.get('enabled', True)
                    rule.weight = rule_data.get('weight', 1.0)
                    self.add_rule(rule)

                except Exception as e:
                    print(f"导入规则失败 {rule_type}: {e}")

        self.presets = data.get('presets', {})
        return self

    def list_rules(self) -> None:
        """列出所有规则"""
        print(f"\n{'=' * 70}")
        print("当前规则列表:")
        print(f"{'=' * 70}")

        by_priority = defaultdict(list)
        for rule in self.rules:
            by_priority[rule.priority.name].append(rule)

        for priority in sorted(by_priority.keys(),
                               key=lambda p: RulePriority[p].value):
            print(f"\n[{priority}]")
            for rule in by_priority[priority]:
                status = "✓" if rule.enabled else "✗"
                stats = f"({rule.stats['passed']}/{rule.stats['evaluations']})" if rule.stats['evaluations'] > 0 else ""
                print(f"  {status} {rule.name:20s} ({rule.__class__.__name__:15s}) "
                      f"w={rule.weight:.2f} {stats}")
        print()