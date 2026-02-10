"""
数据模型定义 - 编队识别系统的核心数据结构
"""
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime
from enum import Enum


class PlatformType(Enum):
    """平台类型"""
    FIGHTER = "Fighter"
    BOMBER = "Bomber"
    AWACS = "AWACS"
    EW = "EW"
    TANKER = "Tanker"
    TRANSPORT = "Transport"
    UAV = "UAV"
    HELICOPTER = "Helicopter"
    UNKNOWN = "Unknown"


class MissionType(Enum):
    """任务类型"""
    STRIKE = "Strike"
    ESCORT = "Escort"
    EW_SUPPORT = "EWSupport"
    AEW = "AEW"
    REFUEL = "Refuel"
    RECON = "Recon"
    CAP = "CAP"
    UNKNOWN = "Unknown"


class RulePriority(Enum):
    """规则优先级"""
    CRITICAL = 0  # 关键规则（不满足直接排除）
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    OPTIONAL = 4


@dataclass
class GeoPosition:
    """地理坐标（支持本地笛卡尔转换）"""
    longitude: float  # 经度（度）
    latitude: float  # 纬度（度）
    altitude: float  # 高度（米）

    _x: float = field(default=None, repr=False)  # 东向坐标（米）
    _y: float = field(default=None, repr=False)  # 北向坐标（米）

    @property
    def x(self) -> float:
        """东向坐标（米）"""
        if self._x is None:
            self._x = self.longitude * 111320 * math.cos(math.radians(self.latitude))
        return self._x

    @property
    def y(self) -> float:
        """北向坐标（米）"""
        if self._y is None:
            self._y = self.latitude * 110540
        return self._y

    def distance_to(self, other: 'GeoPosition') -> float:
        """计算水平距离（米）"""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def vertical_distance_to(self, other: 'GeoPosition') -> float:
        """计算垂直距离（米）"""
        return abs(self.altitude - other.altitude)

    def to_dict(self) -> Dict[str, float]:
        return {
            'longitude': round(self.longitude, 6),
            'latitude': round(self.latitude, 6),
            'altitude': round(self.altitude, 1)
        }


@dataclass
class TargetState:
    """目标状态快照"""
    timestamp: datetime
    position: GeoPosition
    heading: float  # 航向（度，0-360）
    speed: float  # 速度（m/s）
    pitch: float = 0.0  # 俯仰角（度）
    roll: float = 0.0  # 横滚角（度）

    def to_dict(self) -> Dict[str, Any]:
        return {
            'time': self.timestamp.isoformat(),
            'position': self.position.to_dict(),
            'heading': round(self.heading, 2),
            'speed': round(self.speed, 2),
            'pitch': round(self.pitch, 2),
            'roll': round(self.roll, 2)
        }


@dataclass
class TargetAttributes:
    """目标属性信息"""
    target_type: Optional[PlatformType] = None
    nation: Optional[str] = None
    alliance: Optional[str] = None
    theater: Optional[str] = None
    airport: Optional[str] = None
    squadron: Optional[str] = None
    mission: Optional[MissionType] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.target_type.value if self.target_type else None,
            'nation': self.nation,
            'alliance': self.alliance,
            'theater': self.theater,
            'airport': self.airport,
            'squadron': self.squadron,
            'mission': self.mission.value if self.mission else None
        }


@dataclass
class MotionFeatures:
    """运动特征（用于高级分析）"""
    acceleration: float = 0.0  # 加速度（m/s²）
    turn_rate: float = 0.0  # 转弯率（度/s）
    climb_rate: float = 0.0  # 爬升率（m/s）
    speed_stability: float = 1.0  # 速度稳定性[0,1]
    heading_stability: float = 1.0  # 航向稳定性[0,1]
    is_maneuvering: bool = False  # 是否正在机动


@dataclass
class FormationMember:
    """编队成员信息"""
    target_id: str
    target_name: str
    attributes: TargetAttributes
    track: List[TargetState]  # 完整历史航迹
    motion_features: List[MotionFeatures]
    join_time: datetime
    leave_time: Optional[datetime] = None

    def get_track_segment(self, start: datetime, end: datetime) -> List[TargetState]:
        """获取指定时间段的航迹"""
        return [s for s in self.track if start <= s.timestamp <= end]


@dataclass
class Formation:
    """编队识别结果"""
    formation_id: int
    formation_type: str  # 编队类型（自动推断）
    confidence: float  # 置信度[0,1]
    members: Dict[str, FormationMember]  # 成员字典

    time_range: Tuple[datetime, datetime]  # 编队时间范围
    create_time: datetime  # 识别创建时间
    dissolve_time: Optional[datetime] = None  # 解散时间

    # 空间特征
    center_position: GeoPosition  # 几何中心
    bounding_box: Dict[str, float]  # 3D包围盒
    coverage_area: float  # 覆盖面积（km²）

    # 运动特征
    average_speed: float
    speed_std: float
    average_heading: float
    heading_std: float
    altitude_layer: str  # 高度层分类

    # 协同关系网络
    coordination_graph: Dict[str, List[Dict]]

    # 规则应用记录（用于追溯）
    applied_rules: List[str] = field(default_factory=list)
    rule_confidences: Dict[str, float] = field(default_factory=dict)

    def to_dict(self, include_full_track: bool = True) -> Dict[str, Any]:
        """转换为字典格式（用于JSON序列化）"""
        result = {
            'formation_id': self.formation_id,
            'formation_type': self.formation_type,
            'confidence': round(self.confidence, 3),
            'status': 'active' if self.dissolve_time is None else 'dissolved',

            'time': {
                'create': self.create_time.isoformat(),
                'start': self.time_range[0].isoformat(),
                'end': self.time_range[1].isoformat(),
                'duration_seconds': (self.time_range[1] - self.time_range[0]).total_seconds()
            },

            'members': {
                tid: {
                    'name': m.target_name,
                    'attributes': m.attributes.to_dict(),
                    'join_time': m.join_time.isoformat(),
                    'track_points': len(m.track),
                    'track_duration': (m.track[-1].timestamp - m.track[0]).total_seconds() if m.track else 0
                }
                for tid, m in self.members.items()
            },

            'spatial': {
                'center': self.center_position.to_dict(),
                'bounding_box': self.bounding_box,
                'coverage_area_km2': round(self.coverage_area, 2)
            },

            'motion': {
                'average_speed': round(self.average_speed, 1),
                'speed_std': round(self.speed_std, 1),
                'average_heading': round(self.average_heading, 1),
                'heading_std': round(self.heading_std, 1),
                'altitude_layer': self.altitude_layer,
                'cohesion': round(1 - self.heading_std / 180, 3)
            },

            'coordination': self.coordination_graph,
            'rules_applied': self.applied_rules,
            'rule_confidences': {k: round(v, 3) for k, v in self.rule_confidences.items()}
        }

        if include_full_track:
            result['full_tracks'] = {
                tid: [s.to_dict() for s in m.track]
                for tid, m in self.members.items()
            }

        return result