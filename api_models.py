"""
API数据模型 - Pydantic模型定义
用于请求/响应数据验证和Swagger文档生成
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
from enum import Enum


class PlatformType(str, Enum):
    """平台类型枚举"""
    FIGHTER = "Fighter"
    BOMBER = "Bomber"
    AWACS = "AWACS"
    EW = "EW"
    TANKER = "Tanker"
    TRANSPORT = "Transport"
    UAV = "UAV"
    HELICOPTER = "Helicopter"
    UNKNOWN = "Unknown"


class SceneType(str, Enum):
    """场景类型枚举"""
    AIR_SUPERIORITY = "air_superiority"
    STRIKE = "strike"
    PATROL = "patrol"
    EW = "ew"
    DEFAULT = "default"


class RulePriority(str, Enum):
    """规则优先级枚举"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    OPTIONAL = "OPTIONAL"


class Position(BaseModel):
    """位置模型"""
    longitude: float = Field(..., description="经度(度)", ge=-180, le=180)
    latitude: float = Field(..., description="纬度(度)", ge=-90, le=90)
    altitude: float = Field(..., description="高度(米)", ge=0, le=30000)

    class Config:
        json_schema_extra = {
            "example": {"longitude": 116.5, "latitude": 39.9, "altitude": 5000}
        }


class TargetData(BaseModel):
    """目标数据模型"""
    id: str = Field(..., description="目标唯一标识", min_length=1, max_length=50)
    name: Optional[str] = Field(None, description="目标名称")
    type: PlatformType = Field(default=PlatformType.UNKNOWN, description="平台类型")
    time: datetime = Field(..., description="时间戳")
    position: Position = Field(..., description="位置信息")
    heading: float = Field(default=0.0, description="航向(度)", ge=0, le=360)
    speed: float = Field(default=0.0, description="速度(m/s)", ge=0, le=1000)
    nation: Optional[str] = Field(None, description="国家")
    alliance: Optional[str] = Field(None, description="联盟")
    theater: Optional[str] = Field(None, description="战区")
    airport: Optional[str] = Field(None, description="机场")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "F16-001",
                "name": "F-16A",
                "type": "Fighter",
                "time": "2024-01-15T10:00:00Z",
                "position": {"longitude": 116.5, "latitude": 39.9, "altitude": 5000},
                "heading": 90.0,
                "speed": 250.0,
                "nation": "BLUE",
                "alliance": "NATO",
                "theater": "North",
                "airport": "AB01"
            }
        }


class RuleConfig(BaseModel):
    """规则配置模型"""
    name: str = Field(..., description="规则名称")
    rule_type: str = Field(..., description="规则类型",
                           enum=["DistanceRule", "AltitudeRule", "SpeedRule",
                                 "HeadingRule", "AttributeRule", "PlatformTypeRule", "CustomRule"])
    priority: RulePriority = Field(default=RulePriority.MEDIUM, description="优先级")
    enabled: bool = Field(default=True, description="是否启用")
    weight: float = Field(default=1.0, description="权重", ge=0, le=2)
    params: Dict[str, Any] = Field(default_factory=dict, description="规则参数")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "CustomDistance",
                "rule_type": "DistanceRule",
                "priority": "CRITICAL",
                "enabled": True,
                "weight": 1.0,
                "params": {
                    "min_distance": 0,
                    "max_distance": 5000
                }
            }
        }


class RulePreset(BaseModel):
    """规则预设模型"""
    name: str = Field(..., description="预设名称")
    description: str = Field(..., description="预设描述")
    rules: List[RuleConfig] = Field(..., description="规则列表")
    default: bool = Field(default=False, description="是否为默认预设")


class TimeRange(BaseModel):
    """时间范围模型"""
    start: Optional[datetime] = Field(None, description="开始时间")
    end: Optional[datetime] = Field(None, description="结束时间")


class RecognitionRequest(BaseModel):
    """识别请求模型"""
    targets: List[TargetData] = Field(..., description="目标数据列表", min_items=2)
    preset: Optional[str] = Field("tight_fighter", description="规则预设名称")
    scene_type: Optional[SceneType] = Field(None, description="场景类型（用于自适应）")
    time_range: Optional[TimeRange] = Field(None, description="分析时间范围")

    class Config:
        json_schema_extra = {
            "example": {
                "targets": [
                    {
                        "id": "F16-001",
                        "name": "F-16A",
                        "type": "Fighter",
                        "time": "2024-01-15T10:00:00Z",
                        "position": {"longitude": 116.5, "latitude": 39.9, "altitude": 5000},
                        "heading": 90.0,
                        "speed": 250.0,
                        "nation": "BLUE",
                        "alliance": "NATO"
                    },
                    {
                        "id": "F16-002",
                        "name": "F-16B",
                        "type": "Fighter",
                        "time": "2024-01-15T10:00:00Z",
                        "position": {"longitude": 116.51, "latitude": 39.91, "altitude": 5100},
                        "heading": 92.0,
                        "speed": 255.0,
                        "nation": "BLUE",
                        "alliance": "NATO"
                    }
                ],
                "preset": "tight_fighter",
                "scene_type": "air_superiority"
            }
        }


class FormationMemberInfo(BaseModel):
    """编队成员信息模型"""
    target_id: str = Field(..., description="目标ID")
    name: str = Field(..., description="目标名称")
    join_time: datetime = Field(..., description="加入编队时间")
    track_points: int = Field(..., description="航迹点数")
    track_duration: float = Field(..., description="航迹持续时间(秒)")


class SpatialInfo(BaseModel):
    """空间信息模型"""
    center: Position = Field(..., description="编队中心")
    bounding_box: Dict[str, float] = Field(..., description="包围盒")
    coverage_area_km2: float = Field(..., description="覆盖面积(km²)")


class MotionInfo(BaseModel):
    """运动信息模型"""
    average_speed: float = Field(..., description="平均速度(m/s)")
    speed_std: float = Field(..., description="速度标准差")
    average_heading: float = Field(..., description="平均航向(度)")
    heading_std: float = Field(..., description="航向标准差")
    altitude_layer: str = Field(..., description="高度层")
    cohesion: float = Field(..., description="编队凝聚力(0-1)")


class FormationResult(BaseModel):
    """编队结果模型"""
    formation_id: int = Field(..., description="编队ID")
    formation_type: str = Field(..., description="编队类型")
    confidence: float = Field(..., description="置信度(0-1)")
    status: str = Field(..., description="状态(active/dissolved)")

    time: Dict[str, Any] = Field(..., description="时间信息")
    members: Dict[str, FormationMemberInfo] = Field(..., description="成员信息")
    spatial: SpatialInfo = Field(..., description="空间信息")
    motion: MotionInfo = Field(..., description="运动信息")

    coordination: List[Dict] = Field(default_factory=list, description="协同关系")
    rules_applied: List[str] = Field(default_factory=list, description="应用的规则")
    rule_confidences: Dict[str, float] = Field(default_factory=dict, description="规则置信度")

    full_tracks: Optional[Dict[str, List[Dict]]] = Field(None, description="完整航迹")


class RecognitionResponse(BaseModel):
    """识别响应模型"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    formation_count: int = Field(..., description="编队数量")
    formations: List[FormationResult] = Field(default_factory=list, description="编队列表")
    processing_time_ms: float = Field(..., description="处理时间(毫秒)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class HealthCheck(BaseModel):
    """健康检查模型"""
    status: str = Field(..., description="状态")
    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="版本")
    timestamp: datetime = Field(..., description="时间戳")
    details: Optional[Dict[str, Any]] = Field(None, description="详细信息")


class ValidationResult(BaseModel):
    """验证结果模型"""
    target_id: str = Field(..., description="目标ID")
    valid: bool = Field(..., description="是否有效")
    errors: List[str] = Field(default_factory=list, description="错误信息")
    warnings: List[str] = Field(default_factory=list, description="警告信息")

"""
API数据模型补充 - 规则管理相关
"""
class ApiResponse(BaseModel):
    """通用API响应"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None


class PresetCreateRequest(BaseModel):
    """创建预设请求"""
    name: str = Field(..., min_length=1, max_length=100, description="预设名称")
    description: Optional[str] = Field(None, description="预设描述")
    initial_rules: Optional[List['RuleCreateRequest']] = Field(None, description="初始规则列表")


class PresetUpdateRequest(BaseModel):
    """更新预设请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RuleCreateRequest(BaseModel):
    """创建规则请求"""
    preset_id: str = Field(..., description="所属预设ID")
    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    rule_type: str = Field(..., description="规则类型")
    priority: str = Field(default="MEDIUM", description="优先级")
    enabled: bool = Field(default=True, description="是否启用")
    weight: float = Field(default=1.0, ge=0, le=2, description="权重")
    params: Dict[str, Any] = Field(default_factory=dict, description="规则参数")
    description: Optional[str] = Field(None, description="规则描述")
    tags: Optional[List[str]] = Field(None, description="标签")


class RuleUpdateRequest(BaseModel):
    """更新规则请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    rule_type: Optional[str] = None
    priority: Optional[str] = None
    enabled: Optional[bool] = None
    weight: Optional[float] = Field(None, ge=0, le=2)
    params: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    comment: Optional[str] = Field(None, description="修改备注")


class ReorderRequest(BaseModel):
    """重新排序请求"""
    preset_id: str = Field(..., description="预设ID")
    rule_orders: List[Dict[str, Any]] = Field(..., description="规则顺序列表")


class RuleStatistics(BaseModel):
    """规则统计"""
    total_evaluations: int
    pass_count: int
    fail_count: int
    pass_rate: float