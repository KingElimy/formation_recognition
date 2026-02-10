"""
编队识别系统使用示例
"""
import json
from datetime import datetime, timedelta
import numpy as np

from formation_engine import FormationRecognitionEngine
from rule_manager import RuleManager
from rules import RuleContext, RuleResult, RulePriority, DistanceRule, AltitudeRule


def generate_test_data():
    """生成测试数据"""
    base_time = datetime(2024, 1, 15, 10, 0, 0)
    data = []

    # 场景1: F-16四机编队（密集编队）
    print("生成F-16四机编队...")
    f16_positions = [(116.4, 39.9), (116.405, 39.902), (116.398, 39.898), (116.402, 39.901)]
    for i, (base_lon, base_lat) in enumerate(f16_positions):
        callsign = f'F16-{i + 1}'
        for t in range(0, 120, 5):  # 2分钟，每5秒一个点
            data.append({
                'id': callsign,
                '名称': f'F-16-{i + 1}',
                '类型': 'Fighter',
                '时间': base_time + timedelta(seconds=t),
                '位置': (
                    base_lon + t * 0.00001,
                    base_lat + t * 0.000005,
                    5000 + i * 30
                ),
                '航向': 90 + np.random.normal(0, 1),
                '速度': 250 + np.random.normal(0, 2),
                '国家': 'BLUE',
                '联盟': 'NATO',
                '战区': 'North',
                '机场': 'AB01'
            })

    # 场景2: B-52双机 + F-16护航（混合编队）
    print("生成B-52轰炸机编队...")
    for i, callsign in enumerate(['B52-A', 'B52-B']):
        base_lon, base_lat = 116.6 + i * 0.008, 40.0
        for t in range(0, 120, 5):
            data.append({
                'id': callsign,
                '名称': f'B-52-{i + 1}',
                '类型': 'Bomber',
                '时间': base_time + timedelta(seconds=t),
                '位置': (base_lon + t * 0.00008, base_lat, 8000),
                '航向': 85 + np.random.normal(0, 0.5),
                '速度': 200 + np.random.normal(0, 1),
                '国家': 'BLUE',
                '联盟': 'NATO',
                '战区': 'North',
                '机场': 'AB01'
            })

    # 护航战斗机
    print("生成护航战斗机...")
    for i, callsign in enumerate(['ESCORT-1', 'ESCORT-2']):
        base_lon, base_lat = 116.65 + i * 0.02, 40.02 + (0.02 if i == 0 else -0.02)
        for t in range(0, 120, 5):
            data.append({
                'id': callsign,
                '名称': f'F-16-Escort-{i + 1}',
                '类型': 'Fighter',
                '时间': base_time + timedelta(seconds=t),
                '位置': (base_lon + t * 0.00008, base_lat, 8200),
                '航向': 85 + np.random.normal(0, 2),
                '速度': 205 + np.random.normal(0, 3),
                '国家': 'BLUE',
                '联盟': 'NATO',
                '战区': 'North',
                '机场': 'AB01'
            })

    # 场景3: 预警机（远距离指挥）
    print("生成E-3预警机...")
    for t in range(0, 120, 5):
        data.append({
            'id': 'E3-SENTRY',
            '名称': 'E-3 Sentry',
            '类型': 'AWACS',
            '时间': base_time + timedelta(seconds=t),
            '位置': (116.3 + t * 0.00005, 40.1, 10000),
            '航向': 90,
            '速度': 180,
            '国家': 'BLUE',
            '联盟': 'NATO',
            '战区': 'North',
            '机场': 'AB01'
        })

    # 场景4: 敌对目标（应被隔离）
    print("生成敌对目标...")
    for t in range(0, 120, 5):
        data.append({
            'id': 'SU27-FLANker',
            '名称': 'Su-27 Flanker',
            '类型': 'Fighter',
            '时间': base_time + timedelta(seconds=t),
            '位置': (116.5 + t * 0.0001, 39.8, 6000),
            '航向': 270,
            '速度': 280,
            '国家': 'RED',
            '联盟': 'Warsaw',
            '战区': 'North',
            '机场': None
        })

    # 场景5: 孤立目标（测试过滤）
    print("生成孤立目标...")
    for t in range(0, 120, 5):
        data.append({
            'id': 'LONE-WOLF',
            '名称': '孤立测试机',
            '类型': 'Fighter',
            '时间': base_time + timedelta(seconds=t),
            '位置': (117.5, 40.5, 5500),
            '航向': 45,
            '速度': 260,
            '国家': 'BLUE',
            '联盟': 'NATO',
            '战区': 'North',
            '机场': 'AB02'
        })

    print(f"共生成 {len(data)} 条记录")
    return data


def example_1_basic_usage():
    """示例1: 基本使用"""
    print("\n" + "=" * 70)
    print("示例1: 基本使用 - 密集战斗机编队识别")
    print("=" * 70)

    # 生成数据
    data = generate_test_data()

    # 创建引擎并加载预设
    engine = FormationRecognitionEngine()
    engine.load_preset("tight_fighter")

    # 处理数据并识别
    formations = engine.process_data(data).recognize()

    # 打印结果
    print(f"\n识别到 {len(formations)} 个编队:")
    for f in formations:
        print(f"\n编队{f.formation_id}: {f.formation_type}")
        print(f"  置信度: {f.confidence:.3f}")
        print(f"  成员: {list(f.members.keys())}")
        print(f"  平均间距: {np.sqrt(f.coverage_area):.1f}km")

    # 导出结果
    engine.export_results("example1_basic.json")

    return engine


def example_2_scene_adaptation():
    """示例2: 场景自适应"""
    print("\n" + "=" * 70)
    print("示例2: 场景自适应 - 切换不同规则集")
    print("=" * 70)

    data = generate_test_data()

    # 测试不同场景
    scenes = ["tight_fighter", "loose_bomber", "strike_package"]

    for scene in scenes:
        print(f"\n--- 场景: {scene} ---")
        engine = FormationRecognitionEngine()
        engine.load_preset(scene)
        formations = engine.process_data(data).recognize()
        print(f"识别到 {len(formations)} 个编队")
        for f in formations:
            print(f"  编队{f.formation_id}: {f.formation_type} "
                  f"({len(f.members)}架)")


def example_3_custom_rules():
    """示例3: 自定义规则"""
    print("\n" + "=" * 70)
    print("示例3: 自定义规则 - 添加特殊业务逻辑")
    print("=" * 70)

    data = generate_test_data()

    # 创建引擎
    engine = FormationRecognitionEngine()
    engine.load_preset("tight_fighter")

    # 添加自定义规则: 雷达散射截面相似性
    def rcs_similarity_rule(context: RuleContext) -> RuleResult:
        """隐身飞机协同规则"""
        from models import PlatformType

        t1 = context.track1.attributes.target_type
        t2 = context.track2.attributes.target_type

        stealth_types = {PlatformType.FIGHTER, PlatformType.UAV}

        is_stealth1 = t1 in stealth_types if t1 else False
        is_stealth2 = t2 in stealth_types if t2 else False

        if is_stealth1 and is_stealth2:
            return RuleResult(
                True, 1.1, RulePriority.LOW,
                "双隐身协同",
                {'stealth_pair': True, 'rcs_match': 0.9}
            )
        return RuleResult(True, 1.0, RulePriority.LOW, "RCS检查通过")

    engine.add_custom_rule("RCS_Similarity", rcs_similarity_rule)

    # 添加自定义规则: 机场相同加分
    def same_airport_bonus(context: RuleContext) -> RuleResult:
        """同机场出发奖励"""
        a1 = context.track1.attributes.airport
        a2 = context.track2.attributes.airport

        if a1 and a2 and a1 == a2:
            return RuleResult(
                True, 1.15, RulePriority.LOW,
                f"同机场: {a1}",
                {'same_airport': a1}
            )
        return RuleResult(True, 1.0, RulePriority.LOW, "机场检查通过")

    engine.add_custom_rule("SameAirport", same_airport_bonus)

    # 执行识别
    formations = engine.process_data(data).recognize()

    # 查看规则统计
    print("\n自定义规则统计:")
    for r in engine.rule_manager.rules:
        if 'custom' in r.name.lower() and r.stats['evaluations'] > 0:
            print(f"  {r.name}: 评估{r.stats['evaluations']}次, "
                  f"通过{r.stats['passed']}次")


def example_4_dynamic_adjustment():
    """示例4: 动态调整规则参数"""
    print("\n" + "=" * 70)
    print("示例4: 动态调整规则参数")
    print("=" * 70)

    data = generate_test_data()

    engine = FormationRecognitionEngine()
    engine.load_preset("tight_fighter")

    print("原始规则:")
    engine.rule_manager.list_rules()

    # 获取并修改距离规则
    dist_rule = engine.rule_manager.get_rule("TightDist")
    if dist_rule:
        print(f"\n修改前最大距离: {dist_rule.max_distance}m")
        dist_rule.max_distance = 5000  # 放宽到5km
        print(f"修改后最大距离: {dist_rule.max_distance}m")

    # 禁用航向规则（允许更大偏差）
    heading_rule = engine.rule_manager.get_rule("TightHeading")
    if heading_rule:
        heading_rule.disable()
        print("已禁用航向规则")

    formations = engine.process_data(data).recognize()
    print(f"\n调整后识别到 {len(formations)} 个编队")


def example_5_rule_serialization():
    """示例5: 规则序列化和反序列化"""
    print("\n" + "=" * 70)
    print("示例5: 规则序列化 - 保存和加载配置")
    print("=" * 70)

    # 创建并配置引擎
    engine = FormationRecognitionEngine()
    engine.load_preset("strike_package")

    # 添加自定义规则
    def my_rule(context: RuleContext) -> RuleResult:
        return RuleResult(True, 1.0, RulePriority.LOW, "自定义规则")

    engine.add_custom_rule("MyCustomRule", my_rule)

    # 导出规则
    engine.rule_manager.export_to_json("my_rules.json")
    print("规则已导出到 my_rules.json")

    # 创建新引擎并导入
    new_engine = FormationRecognitionEngine()
    new_engine.rule_manager.import_from_json("my_rules.json")

    print("\n导入的规则:")
    new_engine.rule_manager.list_rules()


def example_6_batch_processing():
    """示例6: 批量处理和对比分析"""
    print("\n" + "=" * 70)
    print("示例6: 批量处理 - 多规则集对比")
    print("=" * 70)

    data = generate_test_data()

    results = {}

    for preset in ["tight_fighter", "loose_bomber", "strike_package"]:
        engine = FormationRecognitionEngine()
        engine.load_preset(preset)
        formations = engine.process_data(data).recognize()

        results[preset] = {
            'formation_count': len(formations),
            'avg_confidence': np.mean([f.confidence for f in formations]) if formations else 0,
            'total_aircraft': sum(len(f.members) for f in formations),
            'formations': [
                {
                    'id': f.formation_id,
                    'type': f.formation_type,
                    'members': list(f.members.keys()),
                    'confidence': f.confidence
                }
                for f in formations
            ]
        }

    # 打印对比
    print("\n规则集对比:")
    for preset, result in results.items():
        print(f"\n{preset}:")
        print(f"  编队数: {result['formation_count']}")
        print(f"  平均置信度: {result['avg_confidence']:.3f}")
        print(f"  总飞机数: {result['total_aircraft']}")
        for f in result['formations']:
            print(f"    编队{f['id']}: {f['type']} - {f['members']}")


def main():
    """运行所有示例"""
    print("=" * 70)
    print("编队识别系统使用示例")
    print("=" * 70)

    # 运行示例
    example_1_basic_usage()
    example_2_scene_adaptation()
    example_3_custom_rules()
    example_4_dynamic_adjustment()
    example_5_rule_serialization()
    example_6_batch_processing()

    print("\n" + "=" * 70)
    print("所有示例运行完成")
    print("=" * 70)


if __name__ == "__main__":
    main()