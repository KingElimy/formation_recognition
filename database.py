"""
数据库模块 - SQLAlchemy模型和数据库操作
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from datetime import datetime
from typing import List, Dict, Optional, Any
import json
import uuid

# 数据库配置
DATABASE_URL = "sqlite:///./rules.db"  # 开发使用SQLite，生产可改为PostgreSQL
# DATABASE_URL = "postgresql://user:password@localhost/formation_db"

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ==================== 数据库模型 ====================

class RulePresetDB(Base):
    """规则预设表"""
    __tablename__ = "rule_presets"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    category = Column(String(50), default="custom")  # system/custom
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # 元数据
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    created_by = Column(String(50), default="system")

    # 关系
    rules = relationship("RuleDB", back_populates="preset", cascade="all, delete-orphan")

    def to_dict(self, include_rules: bool = False) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "rule_count": len(self.rules) if self.rules else 0
        }

        if include_rules:
            result["rules"] = [r.to_dict() for r in self.rules]

        return result


class RuleDB(Base):
    """规则表"""
    __tablename__ = "rules"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    preset_id = Column(String(50), ForeignKey("rule_presets.id"), nullable=False)

    # 规则基本信息
    name = Column(String(100), nullable=False)
    rule_type = Column(String(50), nullable=False)  # DistanceRule/AltitudeRule等
    priority = Column(String(20), default="MEDIUM")  # CRITICAL/HIGH/MEDIUM/LOW/OPTIONAL

    # 规则状态
    enabled = Column(Boolean, default=True)
    weight = Column(Float, default=1.0)
    order = Column(Integer, default=0)  # 执行顺序

    # 规则参数（JSON存储）
    params = Column(JSON, default=dict)

    # 元数据
    description = Column(Text)
    tags = Column(JSON, default=list)  # 标签列表
    metadata = Column(JSON, default=dict)  # 额外元数据

    # 统计信息
    evaluation_count = Column(Integer, default=0)
    pass_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    last_evaluated = Column(DateTime)

    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    preset = relationship("RulePresetDB", back_populates="rules")
    history = relationship("RuleHistoryDB", back_populates="rule", cascade="all, delete-orphan")

    def to_dict(self, include_history: bool = False) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "preset_id": self.preset_id,
            "name": self.name,
            "rule_type": self.rule_type,
            "priority": self.priority,
            "enabled": self.enabled,
            "weight": self.weight,
            "order": self.order,
            "params": self.params or {},
            "description": self.description,
            "tags": self.tags or [],
            "metadata": self.metadata or {},
            "statistics": {
                "evaluation_count": self.evaluation_count,
                "pass_count": self.pass_count,
                "fail_count": self.fail_count,
                "pass_rate": self.pass_count / max(self.evaluation_count, 1),
                "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

        if include_history and self.history:
            result["history"] = [h.to_dict() for h in self.history[:10]]  # 最近10条

        return result


class RuleHistoryDB(Base):
    """规则修改历史"""
    __tablename__ = "rule_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(50), ForeignKey("rules.id"), nullable=False)

    action = Column(String(20), nullable=False)  # CREATE/UPDATE/DELETE/ENABLE/DISABLE
    changes = Column(JSON)  # 变更内容
    performed_by = Column(String(50), default="system")
    performed_at = Column(DateTime, default=datetime.now)
    comment = Column(Text)

    # 关系
    rule = relationship("RuleDB", back_populates="history")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "action": self.action,
            "changes": self.changes,
            "performed_by": self.performed_by,
            "performed_at": self.performed_at.isoformat() if self.performed_at else None,
            "comment": self.comment
        }


class SceneConfigDB(Base):
    """场景配置表"""
    __tablename__ = "scene_configs"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    # 场景参数
    parameters = Column(JSON, default=dict)  # 自适应参数
    default_preset_id = Column(String(50), ForeignKey("rule_presets.id"))

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {},
            "default_preset_id": self.default_preset_id,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# ==================== 数据库操作类 ====================

class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.engine = engine
        self.SessionLocal = SessionLocal

    def init_database(self):
        """初始化数据库"""
        Base.metadata.create_all(bind=self.engine)
        self._seed_default_data()

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    def _seed_default_data(self):
        """填充默认数据"""
        session = self.get_session()
        try:
            # 检查是否已有数据
            if session.query(RulePresetDB).first():
                return

            # 创建默认预设
            presets = [
                {
                    "name": "tight_fighter",
                    "description": "密集战斗机编队规则 - 适用于空优作战",
                    "category": "system",
                    "is_default": True,
                    "rules": [
                        {"name": "HostileCheck", "type": "AttributeRule", "priority": "CRITICAL",
                         "params": {"hostile_check": True, "same_alliance": True}},
                        {"name": "TightDistance", "type": "DistanceRule", "priority": "CRITICAL",
                         "params": {"min_distance": 0, "max_distance": 3000}},
                        {"name": "TightAltitude", "type": "AltitudeRule", "priority": "HIGH",
                         "params": {"max_diff": 300, "same_layer_preferred": True}},
                        {"name": "TightSpeed", "type": "SpeedRule", "priority": "HIGH",
                         "params": {"max_diff": 20, "max_ratio": 1.1}},
                        {"name": "TightHeading", "type": "HeadingRule", "priority": "HIGH",
                         "params": {"max_diff": 15, "allow_reciprocal": False}}
                    ]
                },
                {
                    "name": "loose_bomber",
                    "description": "松散轰炸机编队规则 - 适用于远程打击",
                    "category": "system",
                    "rules": [
                        {"name": "AllianceCheck", "type": "AttributeRule", "priority": "CRITICAL",
                         "params": {"hostile_check": True, "same_alliance": True}},
                        {"name": "LooseDistance", "type": "DistanceRule", "priority": "CRITICAL",
                         "params": {"min_distance": 3000, "max_distance": 10000}},
                        {"name": "LooseAltitude", "type": "AltitudeRule", "priority": "HIGH",
                         "params": {"max_diff": 1000, "same_layer_preferred": True}},
                        {"name": "LooseSpeed", "type": "SpeedRule", "priority": "HIGH",
                         "params": {"max_diff": 30, "max_ratio": 1.2}},
                        {"name": "LooseHeading", "type": "HeadingRule", "priority": "HIGH",
                         "params": {"max_diff": 20, "allow_reciprocal": False}}
                    ]
                },
                {
                    "name": "strike_package",
                    "description": "混合打击群规则 - 适用于多机种协同",
                    "category": "system",
                    "rules": [
                        {"name": "CoalitionCheck", "type": "AttributeRule", "priority": "CRITICAL",
                         "params": {"hostile_check": True, "same_alliance": True, "same_theater": True}},
                        {"name": "PackageDistance", "type": "DistanceRule", "priority": "CRITICAL",
                         "params": {"min_distance": 5000, "max_distance": 20000}},
                        {"name": "PackageAltitude", "type": "AltitudeRule", "priority": "MEDIUM",
                         "params": {"max_diff": 2000, "same_layer_preferred": False}},
                        {"name": "PackageSpeed", "type": "SpeedRule", "priority": "MEDIUM",
                         "params": {"max_diff": 100, "max_ratio": 2.0}},
                        {"name": "PackageHeading", "type": "HeadingRule", "priority": "MEDIUM",
                         "params": {"max_diff": 60, "allow_reciprocal": True}},
                        {"name": "MixedTypes", "type": "PlatformTypeRule", "priority": "MEDIUM",
                         "params": {"allowed_pairs": [["Fighter", "Bomber"], ["Fighter", "EW"]],
                                    "forbidden_pairs": []}}
                    ]
                }
            ]

            for preset_data in presets:
                rules_data = preset_data.pop("rules", [])

                preset = RulePresetDB(**preset_data)
                session.add(preset)
                session.flush()  # 获取ID

                for idx, rule_data in enumerate(rules_data):
                    rule = RuleDB(
                        preset_id=preset.id,
                        name=rule_data["name"],
                        rule_type=rule_data["type"],
                        priority=rule_data["priority"],
                        params=rule_data.get("params", {}),
                        order=idx
                    )
                    session.add(rule)

            # 创建场景配置
            scenes = [
                {"name": "air_superiority", "description": "空中优势场景", "default_preset_id": None},
                {"name": "strike", "description": "对地打击场景", "default_preset_id": None},
                {"name": "patrol", "description": "巡逻警戒场景", "default_preset_id": None},
                {"name": "ew", "description": "电子战场景", "default_preset_id": None}
            ]

            for scene_data in scenes:
                scene = SceneConfigDB(**scene_data)
                session.add(scene)

            session.commit()
            print("数据库初始化完成，已填充默认数据")

        except Exception as e:
            session.rollback()
            print(f"数据库初始化失败: {e}")
        finally:
            session.close()

    # ==================== 预设操作 ====================

    def get_presets(self, session: Session, category: Optional[str] = None,
                    include_rules: bool = False) -> List[Dict]:
        """获取预设列表"""
        query = session.query(RulePresetDB).filter(RulePresetDB.is_active == True)

        if category:
            query = query.filter(RulePresetDB.category == category)

        presets = query.order_by(RulePresetDB.created_at.desc()).all()
        return [p.to_dict(include_rules=include_rules) for p in presets]

    def get_preset_by_id(self, session: Session, preset_id: str) -> Optional[RulePresetDB]:
        """通过ID获取预设"""
        return session.query(RulePresetDB).filter(
            RulePresetDB.id == preset_id,
            RulePresetDB.is_active == True
        ).first()

    def get_preset_by_name(self, session: Session, name: str) -> Optional[RulePresetDB]:
        """通过名称获取预设"""
        return session.query(RulePresetDB).filter(
            RulePresetDB.name == name,
            RulePresetDB.is_active == True
        ).first()

    def create_preset(self, session: Session, data: Dict) -> RulePresetDB:
        """创建预设"""
        preset = RulePresetDB(**data)
        session.add(preset)
        session.commit()
        session.refresh(preset)
        return preset

    def update_preset(self, session: Session, preset_id: str, data: Dict) -> Optional[RulePresetDB]:
        """更新预设"""
        preset = self.get_preset_by_id(session, preset_id)
        if not preset:
            return None

        for key, value in data.items():
            if hasattr(preset, key) and key != "id":
                setattr(preset, key, value)

        preset.updated_at = datetime.now()
        session.commit()
        session.refresh(preset)
        return preset

    def delete_preset(self, session: Session, preset_id: str, soft: bool = True) -> bool:
        """删除预设"""
        preset = self.get_preset_by_id(session, preset_id)
        if not preset:
            return False

        if soft:
            preset.is_active = False
            session.commit()
        else:
            session.delete(preset)
            session.commit()

        return True

    # ==================== 规则操作 ====================

    def get_rules(self, session: Session, preset_id: Optional[str] = None,
                  enabled_only: bool = False) -> List[Dict]:
        """获取规则列表"""
        query = session.query(RuleDB)

        if preset_id:
            query = query.filter(RuleDB.preset_id == preset_id)

        if enabled_only:
            query = query.filter(RuleDB.enabled == True)

        rules = query.order_by(RuleDB.order, RuleDB.created_at).all()
        return [r.to_dict() for r in rules]

    def get_rule_by_id(self, session: Session, rule_id: str) -> Optional[RuleDB]:
        """通过ID获取规则"""
        return session.query(RuleDB).filter(RuleDB.id == rule_id).first()

    def create_rule(self, session: Session, data: Dict) -> RuleDB:
        """创建规则"""
        # 自动计算order
        if "order" not in data:
            max_order = session.query(RuleDB).filter(
                RuleDB.preset_id == data.get("preset_id")
            ).count()
            data["order"] = max_order

        rule = RuleDB(**data)
        session.add(rule)
        session.commit()
        session.refresh(rule)

        # 记录历史
        self._add_history(session, rule.id, "CREATE", data)

        return rule

    def update_rule(self, session: Session, rule_id: str, data: Dict,
                    performed_by: str = "system", comment: str = None) -> Optional[RuleDB]:
        """更新规则"""
        rule = self.get_rule_by_id(session, rule_id)
        if not rule:
            return None

        # 记录变更
        changes = {}
        for key, value in data.items():
            if hasattr(rule, key) and key != "id":
                old_value = getattr(rule, key)
                if old_value != value:
                    changes[key] = {"old": old_value, "new": value}
                    setattr(rule, key, value)

        if changes:
            rule.updated_at = datetime.now()
            session.commit()
            session.refresh(rule)

            # 记录历史
            self._add_history(session, rule.id, "UPDATE", changes,
                              performed_by, comment)

        return rule

    def delete_rule(self, session: Session, rule_id: str,
                    performed_by: str = "system") -> bool:
        """删除规则"""
        rule = self.get_rule_by_id(session, rule_id)
        if not rule:
            return False

        # 记录历史
        self._add_history(session, rule_id, "DELETE",
                          {"rule_data": rule.to_dict()},
                          performed_by)

        session.delete(rule)
        session.commit()
        return True

    def toggle_rule(self, session: Session, rule_id: str, enabled: bool,
                    performed_by: str = "system") -> Optional[RuleDB]:
        """启用/禁用规则"""
        rule = self.get_rule_by_id(session, rule_id)
        if not rule:
            return None

        rule.enabled = enabled
        rule.updated_at = datetime.now()
        session.commit()

        action = "ENABLE" if enabled else "DISABLE"
        self._add_history(session, rule_id, action, {"enabled": enabled},
                          performed_by)

        return rule

    def reorder_rules(self, session: Session, preset_id: str,
                      rule_orders: List[Dict]) -> bool:
        """重新排序规则"""
        for item in rule_orders:
            rule = self.get_rule_by_id(session, item["rule_id"])
            if rule and rule.preset_id == preset_id:
                rule.order = item["order"]

        session.commit()
        return True

    def _add_history(self, session: Session, rule_id: str, action: str,
                     changes: Dict, performed_by: str = "system",
                     comment: str = None):
        """添加历史记录"""
        history = RuleHistoryDB(
            rule_id=rule_id,
            action=action,
            changes=changes,
            performed_by=performed_by,
            comment=comment
        )
        session.add(history)
        session.commit()

    # ==================== 场景配置操作 ====================

    def get_scenes(self, session: Session) -> List[Dict]:
        """获取场景配置"""
        scenes = session.query(SceneConfigDB).filter(
            SceneConfigDB.is_active == True
        ).all()
        return [s.to_dict() for s in scenes]

    def update_scene(self, session: Session, scene_id: str,
                     data: Dict) -> Optional[SceneConfigDB]:
        """更新场景配置"""
        scene = session.query(SceneConfigDB).filter(
            SceneConfigDB.id == scene_id
        ).first()

        if not scene:
            return None

        for key, value in data.items():
            if hasattr(scene, key):
                setattr(scene, key, value)

        scene.updated_at = datetime.now()
        session.commit()
        session.refresh(scene)
        return scene

    # ==================== 统计操作 ====================

    def get_statistics(self, session: Session) -> Dict:
        """获取统计信息"""
        total_presets = session.query(RulePresetDB).filter(
            RulePresetDB.is_active == True
        ).count()

        total_rules = session.query(RuleDB).count()
        enabled_rules = session.query(RuleDB).filter(RuleDB.enabled == True).count()

        # 规则类型分布
        type_distribution = {}
        for rule_type in session.query(RuleDB.rule_type).distinct():
            count = session.query(RuleDB).filter(
                RuleDB.rule_type == rule_type[0]
            ).count()
            type_distribution[rule_type[0]] = count

        # 最近修改
        recent_changes = session.query(RuleHistoryDB).order_by(
            RuleHistoryDB.performed_at.desc()
        ).limit(10).all()

        return {
            "overview": {
                "total_presets": total_presets,
                "total_rules": total_rules,
                "enabled_rules": enabled_rules,
                "disabled_rules": total_rules - enabled_rules
            },
            "type_distribution": type_distribution,
            "recent_changes": [h.to_dict() for h in recent_changes]
        }


# 全局数据库管理器实例
db_manager = DatabaseManager()


def get_db() -> Session:
    """获取数据库会话（用于FastAPI依赖）"""
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()