"""
编队识别引擎 - 主入口，集成规则管理和编队识别
"""
import math
import json
from typing import List, Dict, Tuple, Optional, Callable, Any, Set
from collections import defaultdict
from datetime import datetime, timedelta
from copy import deepcopy

import numpy as np
import pandas as pd
from scipy.sparse import csgraph

from models import (
    PlatformType, RulePriority,
    TargetState, GeoPosition, TargetAttributes,
    Formation, FormationMember, MotionFeatures
)
from rules import RuleContext, RuleResult, CustomRule
from rule_manager import RuleManager
from tracker import TargetTrack


class FormationRecognitionEngine:
    """
    编队识别引擎 - 集成规则管理的完整系统

    主要功能：
    1. 数据预处理和航迹管理
    2. 基于规则的编队识别
    3. 时序一致性分析
    4. 多场景自适应
    5. 结果导出和可视化
    """

    def __init__(self, rule_manager: Optional[RuleManager] = None):
        self.rule_manager = rule_manager or RuleManager()
        self.tracks: Dict[str, TargetTrack] = {}
        self.formations: List[Formation] = []
        self.formation_counter = 0

        # 时序分析参数
        self.time_step = timedelta(seconds=10)  # 时间采样步长
        self.persistence_threshold = 0.6  # 时序持续性阈值
        self.min_formation_duration = timedelta(seconds=30)  # 最小编队持续时间
        self.min_track_points = 3  # 最小编队航迹点数

        # 场景自适应
        self.adaptive_mode = True
        self.current_scene = "default"

        # 处理统计
        self.processing_stats = {
            'total_targets': 0,
            'valid_tracks': 0,
            'formation_candidates': 0,
            'final_formations': 0
        }

    def set_rule_manager(self, manager: RuleManager) -> 'FormationRecognitionEngine':
        """设置规则管理器"""
        self.rule_manager = manager
        return self

    def load_preset(self, preset_type: str) -> 'FormationRecognitionEngine':
        """加载规则预设"""
        self.rule_manager.create_preset(preset_type)
        self.current_scene = preset_type
        return self

    def process_data(self, data_list: List[Dict]) -> 'FormationRecognitionEngine':
        """
        处理输入数据

        输入格式: [
            {
                'id': 'T1',
                '名称': 'F-16A',
                '类型': 'Fighter',
                '时间': '2024-01-15 10:00:00',
                '位置': (116.5, 39.9, 5000),  # (经度, 纬度, 高度米)
                '航向': 90.0,
                '速度': 250.0,
                '国家': 'BLUE',
                '联盟': 'NATO',
                '战区': 'North',
                '机场': 'AB01'
            },
            ...
        ]
        """
        self.tracks.clear()
        self.processing_stats['total_targets'] = 0

        for record in data_list:
            self._process_single_record(record)

        # 完成所有航迹
        for track in self.tracks.values():
            track.finalize()

        self.processing_stats['valid_tracks'] = len(self.tracks)
        return self

    def _process_single_record(self, record: Dict):
        """处理单条记录"""
        tid = record.get('id')
        if not tid:
            return

        # 解析时间
        try:
            timestamp = pd.to_datetime(record.get('时间'))
        except:
            return

        # 解析位置
        pos = record.get('位置', (0, 0, 0))
        if len(pos) != 3:
            return

        # 解析平台类型
        type_str = record.get('类型', 'Unknown')
        try:
            platform_type = PlatformType(type_str)
        except:
            platform_type = PlatformType.UNKNOWN

        # 创建或获取航迹
        if tid not in self.tracks:
            attrs = TargetAttributes(
                target_type=platform_type,
                nation=record.get('国家'),
                alliance=record.get('联盟'),
                theater=record.get('战区'),
                airport=record.get('机场'),
                squadron=record.get('部队番号')
            )
            self.tracks[tid] = TargetTrack(tid, record.get('名称', tid), attrs)
            self.processing_stats['total_targets'] += 1

        # 创建状态
        state = TargetState(
            timestamp=timestamp,
            position=GeoPosition(float(pos[0]), float(pos[1]), float(pos[2])),
            heading=float(record.get('航向', 0)),
            speed=float(record.get('速度', 0))
        )
        self.tracks[tid].add_state(state)

    def recognize(self, time_range: Optional[Tuple[datetime, datetime]] = None) -> List[Formation]:
        """
        执行编队识别（主算法）

        流程：
        1. 确定分析时间范围
        2. 多时间点采样和规则评估
        3. 时序一致性分析
        4. 编队构建和优化
        5. 特征计算和类型推断
        """
        if not self.tracks:
            print("警告: 没有航迹数据")
            return []

        # 步骤1: 确定时间范围
        if time_range is None:
            all_times = []
            for track in self.tracks.values():
                for seg in track.segments:
                    all_times.extend([s.timestamp for s in seg])

            if len(all_times) < 2:
                print("警告: 时间数据不足")
                return []

            start_time, end_time = min(all_times), max(all_times)
        else:
            start_time, end_time = time_range

        print(f"\n{'=' * 70}")
        print("编队识别开始")
        print(f"{'=' * 70}")
        print(f"分析时段: {start_time} 至 {end_time}")
        print(f"目标数量: {len(self.tracks)}")
        print(f"规则配置:")
        self.rule_manager.list_rules()

        # 步骤2: 多时间点规则评估
        time_points = pd.date_range(start=start_time, end=end_time, freq=self.time_step)
        print(f"时间采样点: {len(time_points)}个")

        # 存储每对目标的评估历史
        pair_history = defaultdict(lambda: {
            'evaluations': [],
            'time_points': [],
            'passed_count': 0,
            'total_confidence': 0.0
        })

        for t in time_points:
            # 获取该时刻所有目标的状态
            current_states = {}
            for tid, track in self.tracks.items():
                state = track.interpolate(t)
                if state:
                    current_states[tid] = (track, state)

            if len(current_states) < 2:
                continue

            # 评估所有目标对
            target_ids = list(current_states.keys())
            for i in range(len(target_ids)):
                for j in range(i + 1, len(target_ids)):
                    tid1, tid2 = target_ids[i], target_ids[j]
                    track1, state1 = current_states[tid1]
                    track2, state2 = current_states[tid2]

                    # 使用规则管理器评估
                    context = RuleContext(
                        track1=track1, track2=track2,
                        state1=state1, state2=state2,
                        current_time=t
                    )
                    evaluation = self.rule_manager.evaluate_pair(context)

                    pair = frozenset([tid1, tid2])
                    pair_history[pair]['evaluations'].append(evaluation)
                    pair_history[pair]['time_points'].append(t)

                    if evaluation['passed']:
                        pair_history[pair]['passed_count'] += 1
                        pair_history[pair]['total_confidence'] += evaluation['confidence']

        # 步骤3: 时序一致性筛选
        valid_pairs = []
        for pair, history in pair_history.items():
            if not history['evaluations']:
                continue

            total_evals = len(history['evaluations'])
            persistence = history['passed_count'] / total_evals if total_evals > 0 else 0
            avg_confidence = (history['total_confidence'] / history['passed_count']
                              if history['passed_count'] > 0 else 0)

            # 计算持续时间
            if len(history['time_points']) >= 2:
                duration = (max(history['time_points']) - min(history['time_points'])).total_seconds()
            else:
                duration = 0

            if persistence >= self.persistence_threshold and duration >= self.min_formation_duration.total_seconds():
                valid_pairs.append({
                    'pair': pair,
                    'persistence': persistence,
                    'confidence': avg_confidence,
                    'duration': duration,
                    'history': history
                })

        self.processing_stats['formation_candidates'] = len(valid_pairs)
        print(f"\n有效目标对: {len(valid_pairs)}")

        # 步骤4: 构建编队（基于图连通性）
        formations_data = self._build_formations(valid_pairs, start_time, end_time)

        # 步骤5: 创建Formation对象
        self.formations = []
        for idx, form_data in enumerate(formations_data, 1):
            formation = self._create_formation(idx, form_data, start_time, end_time)
            if formation:
                self.formations.append(formation)

        self.formation_counter = len(self.formations)
        self.processing_stats['final_formations'] = len(self.formations)

        print(f"\n识别完成: {len(self.formations)}个编队")
        return self.formations

    def _build_formations(self, valid_pairs: List[Dict],
                          start_time: datetime, end_time: datetime) -> List[Dict]:
        """基于图连通性构建编队"""
        if not valid_pairs:
            return []

        # 构建图
        graph = defaultdict(set)
        edge_weights = {}

        for vp in valid_pairs:
            t1, t2 = list(vp['pair'])
            graph[t1].add(t2)
            graph[t2].add(t1)
            edge_weights[frozenset([t1, t2])] = vp['confidence']

        # 查找连通分量
        visited = set()
        components = []

        def dfs(node, component):
            visited.add(node)
            component.add(node)
            for neighbor in graph[node]:
                if neighbor not in visited:
                    dfs(neighbor, component)

        for node in graph:
            if node not in visited:
                component = set()
                dfs(node, component)
                if len(component) >= 2:
                    components.append(component)

        # 构建编队数据
        formations = []
        for comp in components:
            member_pairs = [frozenset([m1, m2])
                            for m1 in comp for m2 in comp if m1 < m2]
            avg_confidence = np.mean([
                edge_weights.get(p, 0) for p in member_pairs
            ]) if member_pairs else 0

            formations.append({
                'members': comp,
                'confidence': avg_confidence,
                'member_pairs': member_pairs
            })

        return formations

    def _create_formation(self, form_id: int, form_data: Dict,
                          start_time: datetime, end_time: datetime) -> Optional[Formation]:
        """创建编队对象"""
        members = {}
        all_states = []

        for tid in form_data['members']:
            track = self.tracks[tid]
            states = track.get_states_in_range(start_time, end_time)

            if len(states) < self.min_track_points:
                continue

            member = FormationMember(
                target_id=tid,
                target_name=track.target_name,
                attributes=track.attributes,
                track=states,
                motion_features=[],  # 简化处理
                join_time=states[0].timestamp
            )
            members[tid] = member
            all_states.extend(states)

        if len(members) < 2:
            return None

        # 计算空间特征
        lons = [s.position.longitude for s in all_states]
        lats = [s.position.latitude for s in all_states]
        alts = [s.position.altitude for s in all_states]

        bbox = {
            'min_lon': min(lons), 'max_lon': max(lons),
            'min_lat': min(lats), 'max_lat': max(lats),
            'min_alt': min(alts), 'max_alt': max(alts)
        }

        center = GeoPosition(
            (bbox['min_lon'] + bbox['max_lon']) / 2,
            (bbox['min_lat'] + bbox['max_lat']) / 2,
            (bbox['min_alt'] + bbox['max_alt']) / 2
        )

        # 计算覆盖面积
        width = (bbox['max_lon'] - bbox['min_lon']) * 111320 * math.cos(math.radians(center.latitude))
        height = (bbox['max_lat'] - bbox['min_lat']) * 110540
        coverage = (width * height) / 1e6  # km²

        # 运动特征
        speeds = [s.speed for s in all_states]
        headings = [s.heading for s in all_states]

        avg_speed = np.mean(speeds)
        speed_std = np.std(speeds)

        # 环形平均航向
        sin_sum = sum(math.sin(math.radians(h)) for h in headings)
        cos_sum = sum(math.cos(math.radians(h)) for h in headings)
        avg_heading = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

        # 环形标准差
        R = math.sqrt(sin_sum ** 2 + cos_sum ** 2) / len(headings)
        heading_std = math.degrees(math.sqrt(-2 * math.log(max(R, 1e-10))))

        # 高度层
        avg_alt = np.mean(alts)
        alt_layer = self._classify_altitude_layer(avg_alt)

        # 编队类型
        form_type = self._classify_formation_type(members)

        # 收集应用的规则
        applied_rules = [r.name for r in self.rule_manager.rules if r.enabled]
        rule_confidences = {
            r.name: r.stats['passed'] / max(r.stats['evaluations'], 1)
            for r in self.rule_manager.rules if r.stats['evaluations'] > 0
        }

        return Formation(
            formation_id=form_id,
            formation_type=form_type,
            confidence=form_data['confidence'],
            members=members,
            time_range=(start_time, end_time),
            create_time=datetime.now(),
            center_position=center,
            bounding_box=bbox,
            coverage_area=coverage,
            average_speed=avg_speed,
            speed_std=speed_std,
            average_heading=avg_heading,
            heading_std=heading_std,
            altitude_layer=alt_layer,
            coordination_graph={},
            applied_rules=applied_rules,
            rule_confidences=rule_confidences
        )

    def _classify_altitude_layer(self, altitude: float) -> str:
        """分类高度层"""
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

    def _classify_formation_type(self, members: Dict[str, FormationMember]) -> str:
        """推断编队类型"""
        types = [m.attributes.target_type for m in members.values() if m.attributes.target_type]

        if PlatformType.AWACS in types and len(types) > 1:
            return "AEW-Controlled Group"
        elif PlatformType.TANKER in types:
            return "Refueling Cell"
        elif PlatformType.EW in types:
            return "Strike Package with EW"
        elif all(t in [PlatformType.FIGHTER, PlatformType.UAV] for t in types):
            return "Fighter Section"
        elif PlatformType.BOMBER in types:
            if any(t in [PlatformType.FIGHTER] for t in types):
                return "Escorted Strike Package"
            return "Bomber Cell"
        elif PlatformType.TRANSPORT in types:
            return "Transport Formation"

        return "Mixed Formation"

    def adapt_to_scene(self, scene_type: str) -> 'FormationRecognitionEngine':
        """
        根据场景自适应调整规则

        支持场景:
        - air_superiority: 空优场景（密集战斗机编队）
        - strike: 打击场景（混合编队）
        - patrol: 巡逻场景（松散编队）
        - ew: 电子战场景（EW支援）
        """
        if scene_type == "air_superiority":
            self.load_preset("tight_fighter")
        elif scene_type == "strike":
            self.load_preset("strike_package")
        elif scene_type == "patrol":
            self.load_preset("loose_bomber")
        elif scene_type == "ew":
            self.rule_manager.clear()
            self.rule_manager.add_rules([
                AttributeRule("Alliance", True, True, RulePriority.CRITICAL),
                DistanceRule("EWSupport", 10000, 50000, RulePriority.CRITICAL),
                PlatformTypeRule("EWMix",
                                 allowed_pairs=[("EW", "Fighter"), ("EW", "Bomber")],
                                 priority=RulePriority.HIGH)
            ])
        else:
            print(f"未知场景类型: {scene_type}")
            return self

        self.current_scene = scene_type
        print(f"\n已适应场景: {scene_type}")
        return self

    def add_custom_rule(self, name: str, evaluator: Callable,
                        priority: RulePriority = RulePriority.MEDIUM) -> 'FormationRecognitionEngine':
        """添加自定义规则"""
        rule = CustomRule(name, evaluator, priority)
        self.rule_manager.add_rule(rule, "custom")
        return self

    def get_formations(self) -> List[Formation]:
        """获取识别结果"""
        return self.formations

    def get_results(self) -> List[Dict]:
        """获取结果字典列表"""
        return [f.to_dict() for f in self.formations]

    def export_results(self, filepath: str, include_tracks: bool = True):
        """导出结果到JSON"""
        results = {
            'metadata': {
                'export_time': datetime.now().isoformat(),
                'scene_type': self.current_scene,
                'processing_stats': self.processing_stats,
                'rules_applied': [r.to_dict() for r in self.rule_manager.rules]
            },
            'formations': [f.to_dict(include_full_track=include_tracks)
                           for f in self.formations]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"结果已导出: {filepath}")

    def print_summary(self):
        """打印识别摘要"""
        print(f"\n{'=' * 70}")
        print("编队识别摘要")
        print(f"{'=' * 70}")
        print(f"场景类型: {self.current_scene}")
        print(f"处理统计:")
        for key, value in self.processing_stats.items():
            print(f"  {key}: {value}")

        print(f"\n识别到 {len(self.formations)} 个编队:")
        for f in self.formations:
            print(f"\n  编队{f.formation_id}: {f.formation_type}")
            print(f"    置信度: {f.confidence:.3f}")
            print(f"    成员: {list(f.members.keys())}")
            print(f"    中心: ({f.center_position.longitude:.4f}, {f.center_position.latitude:.4f})")
            print(f"    高度层: {f.altitude_layer}")
            print(f"    平均速度: {f.average_speed:.1f}m/s")