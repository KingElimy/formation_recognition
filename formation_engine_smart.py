"""
智能编队识别引擎 - 基于缓存增量触发识别
"""
import logging
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from formation_engine import FormationRecognitionEngine
from cache.target_cache import target_cache
from cache.formation_store import formation_store
from models import TargetState, GeoPosition, TargetAttributes

logger = logging.getLogger(__name__)


class SmartFormationEngine(FormationRecognitionEngine):
    """
    智能编队识别引擎

    特性：
    1. 增量识别 - 只处理有变化的目标
    2. 缓存感知 - 自动从Redis获取最新状态
    3. 智能触发 - 基于变化率动态调整识别频率
    """

    def __init__(self, rule_manager=None):
        super().__init__(rule_manager)

        # 增量识别配置
        self.min_recognition_interval = timedelta(seconds=5)  # 最小编队识别间隔
        self.last_recognition_time: Optional[datetime] = None
        self.changed_targets: Set[str] = set()  # 自上次识别后变化的目标

        # 缓存集成
        self.use_cache = True
        self.cache_priority = True  # 优先使用缓存中的最新状态

    def process_data_with_cache(self, data_list: List[Dict],
                                force_full: bool = False) -> 'SmartFormationEngine':
        """
        处理输入数据（集成缓存）

        Args:
            data_list: 输入数据
            force_full: 强制全量处理（忽略增量优化）
        """
        if not self.use_cache or force_full:
            # 回退到父类方法
            return super().process_data(data_list)

        # 跟踪变化的目标
        changed_targets = []

        for record in data_list:
            tid = record.get('id')
            if not tid:
                continue

            # 处理单条记录（会触发Tracker缓存）
            self._process_single_record(record)

            # 检查是否变化（通过缓存版本）
            try:
                # 从缓存获取版本信息
                cached_state = target_cache.get_target_state(tid)
                if cached_state:
                    # 对比时间戳判断是否为新数据
                    record_time = self._parse_time(record.get('时间'))
                    if record_time and cached_state.timestamp == record_time:
                        # 数据已同步到缓存，标记为变化
                        self.changed_targets.add(tid)
                        changed_targets.append(tid)
            except Exception as e:
                logger.warning(f"缓存检查失败 [{tid}]: {e}")

        logger.info(f"数据处理完成: {len(data_list)}条记录, "
                    f"{len(changed_targets)}个目标变化")

        return self

    def recognize_incremental(self,
                              time_range: Optional[Tuple[datetime, datetime]] = None,
                              force: bool = False) -> List[Dict]:
        """
        执行增量编队识别

        只有满足以下条件之一才执行识别：
        1. 距离上次识别超过最小间隔
        2. 有目标发生变化（self.changed_targets非空）
        3. force=True 强制识别
        """
        now = datetime.now()

        # 检查识别条件
        should_recognize = force

        if not should_recognize and self.last_recognition_time:
            elapsed = now - self.last_recognition_time
            if elapsed >= self.min_recognition_interval:
                should_recognize = True
                logger.debug(f"超过识别间隔 ({elapsed.total_seconds():.1f}s)，触发识别")

        if not should_recognize and self.changed_targets:
            should_recognize = True
            logger.debug(f"{len(self.changed_targets)}个目标变化，触发识别")

        if not should_recognize:
            logger.debug("跳过识别（无变化且未达间隔）")
            return []

        # 执行识别前，从缓存刷新目标状态（获取最新）
        if self.use_cache and self.cache_priority:
            self._refresh_from_cache()

        # 执行识别
        formations = self.recognize(time_range)

        # 更新状态
        self.last_recognition_time = now
        self.changed_targets.clear()

        # 存储结果
        if formations:
            stored_ids = formation_store.store_formations_batch(formations)
            logger.info(f"识别完成: {len(formations)}个编队，"
                        f"存储ID: {stored_ids}")

        return [f.to_dict() for f in formations]

    def _refresh_from_cache(self):
        """从Redis缓存刷新目标状态"""
        if not self.tracks:
            return

        refreshed = 0
        for tid, track in list(self.tracks.items()):
            try:
                cached_state = target_cache.get_target_state(tid)
                if cached_state:
                    # 检查缓存是否比本地更新
                    latest_local = None
                    if track.current_segment:
                        latest_local = track.current_segment[-1]
                    elif track.segments:
                        latest_local = track.segments[-1][-1]

                    if (not latest_local or
                            cached_state.timestamp > latest_local.timestamp):
                        # 添加缓存状态（不触发再次缓存）
                        track.add_state(cached_state, sync_to_cache=False)
                        refreshed += 1

            except Exception as e:
                logger.warning(f"刷新缓存失败 [{tid}]: {e}")

        if refreshed > 0:
            logger.debug(f"从缓存刷新了 {refreshed} 个目标状态")

    def _parse_time(self, time_str) -> Optional[datetime]:
        """解析时间字符串"""
        if not time_str:
            return None
        try:
            import pandas as pd
            return pd.to_datetime(time_str)
        except:
            return None

    def get_cache_status(self) -> Dict:
        """获取缓存状态"""
        return {
            'use_cache': self.use_cache,
            'cache_priority': self.cache_priority,
            'changed_targets_pending': len(self.changed_targets),
            'last_recognition': self.last_recognition_time.isoformat() if self.last_recognition_time else None,
            'min_interval_seconds': self.min_recognition_interval.total_seconds()
        }