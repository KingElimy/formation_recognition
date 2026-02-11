"""
数据流服务 - 持续接收数据，自动触发增量识别
"""
import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from collections import deque
import threading

from formation_engine_smart import SmartFormationEngine
from cache.target_cache import target_cache
from cache.formation_store import formation_store
from sync.websocket_manager import websocket_manager
from models import TargetState, GeoPosition

logger = logging.getLogger(__name__)


class DataStreamService:
    """
    数据流服务

    特性：
    - 持续接收目标数据流
    - 自动缓存到 Redis
    - 智能触发增量识别
    - 结果自动存储并推送
    """

    def __init__(self):
        self.engine: Optional[SmartFormationEngine] = None
        self.is_running = False
        self.buffer: deque = deque(maxlen=10000)  # 数据缓冲区
        self.pending_targets: Set[str] = set()  # 待处理目标

        # 自动识别配置
        self.auto_recognize = True
        self.recognize_interval = 5.0  # 秒，定时识别间隔
        self.min_change_threshold = 0.1  # 最小变化阈值（10%目标变化）
        self.max_wait_time = 10.0  # 秒，最大等待时间

        # 统计
        self.stats = {
            'total_received': 0,
            'total_recognized': 0,
            'last_recognize_time': None,
            'buffer_high_watermark': 0
        }

        # 后台任务
        self._recognize_task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()

    def initialize(self, preset: str = "tight_fighter"):
        """初始化服务"""
        logger.info("初始化数据流服务...")

        self.engine = SmartFormationEngine()
        self.engine.load_preset(preset)
        self.is_running = True

        # 启动后台识别任务
        asyncio.create_task(self._auto_recognize_loop())

        logger.info("数据流服务已启动")

    def shutdown(self):
        """关闭服务"""
        logger.info("关闭数据流服务...")
        self.is_running = False

        if self._recognize_task:
            self._recognize_task.cancel()

        # 最后一次识别
        if self.pending_targets:
            asyncio.create_task(self._do_recognize())

        logger.info("数据流服务已关闭")

    async def push_data(self, targets: List[Dict],
                        source: str = "unknown") -> Dict[str, Any]:
        """
        推送数据到流服务

        Args:
            targets: 目标数据列表
            source: 数据源标识

        Returns:
            接收状态
        """
        if not self.is_running:
            return {"error": "服务未运行"}

        received_count = len(targets)
        self.stats['total_received'] += received_count

        # 更新缓冲区水位
        current_buffer = len(self.buffer)
        if current_buffer > self.stats['buffer_high_watermark']:
            self.stats['buffer_high_watermark'] = current_buffer

        # 处理每个目标
        changed_targets = []

        for target_data in targets:
            tid = target_data.get('id')
            if not tid:
                continue

            # 解析并缓存
            state = self._parse_to_state(target_data)
            if not state:
                continue

            # 更新 Redis 缓存
            try:
                success, is_update, delta = target_cache.cache_target_state(
                    tid, state, emit_delta=True
                )

                if success:
                    # 加入缓冲区
                    self.buffer.append({
                        'target_id': tid,
                        'data': target_data,
                        'state': state,
                        'received_at': datetime.now(),
                        'source': source,
                        'is_update': is_update,
                        'delta': delta
                    })

                    # 记录变化
                    if is_update:
                        changed_targets.append(tid)
                        with self._lock:
                            self.pending_targets.add(tid)

                    # 实时推送增量（可选）
                    if is_update and delta:
                        await self._notify_delta(tid, delta)

            except Exception as e:
                logger.error(f"处理目标失败 [{tid}]: {e}")

        # 检查是否触发识别
        should_recognize = self._should_trigger_recognize(len(changed_targets), received_count)

        return {
            "success": True,
            "received": received_count,
            "changed": len(changed_targets),
            "buffer_size": len(self.buffer),
            "trigger_recognize": should_recognize,
            "pending_targets": len(self.pending_targets)
        }

    async def _auto_recognize_loop(self):
        """后台自动识别循环"""
        while self.is_running:
            try:
                await asyncio.sleep(self.recognize_interval)

                if not self.pending_targets:
                    continue

                # 检查是否超过最大等待时间
                last_recognize = self.stats['last_recognize_time']
                if last_recognize:
                    elapsed = (datetime.now() - last_recognize).total_seconds()
                    if elapsed < self.recognize_interval:
                        continue

                # 执行识别
                await self._do_recognize()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动识别循环错误: {e}")

    async def _do_recognize(self) -> Optional[List[Dict]]:
        """执行增量识别"""
        with self._lock:
            if not self.pending_targets:
                return None

            targets_to_recognize = list(self.pending_targets)
            self.pending_targets.clear()

        try:
            logger.info(f"开始增量识别，目标数: {len(targets_to_recognize)}")

            # 从缓存获取最新状态
            target_states = []
            for tid in targets_to_recognize:
                state = target_cache.get_target_state(tid)
                if state:
                    target_states.append(self._state_to_dict(state, tid))

            if len(target_states) < 2:
                logger.debug("目标数不足，跳过识别")
                return None

            # 执行识别
            start_time = datetime.now()

            formations = self.engine.process_data_with_cache(target_states).recognize_incremental()

            # 存储结果
            stored_formations = []
            if formations:
                for formation_dict in formations:
                    # 转换为 Formation 对象存储
                    from formation_service import formation_service
                    formation_obj = formation_service._dict_to_formation(formation_dict)
                    stored_id = formation_store.store_formation(formation_obj)

                    if stored_id:
                        formation_dict['_stored_id'] = stored_id
                        stored_formations.append(formation_dict)

                        # 推送新编队事件
                        await websocket_manager.notify_formation_detected(formation_dict)

            # 更新统计
            self.stats['total_recognized'] += len(stored_formations)
            self.stats['last_recognize_time'] = datetime.now()

            elapsed = (datetime.now() - start_time).total_seconds() * 1000

            logger.info(f"增量识别完成: {len(stored_formations)}个编队, 耗时{elapsed:.1f}ms")

            return stored_formations

        except Exception as e:
            logger.error(f"增量识别失败: {e}")
            # 失败的目标放回待处理队列
            with self._lock:
                self.pending_targets.update(targets_to_recognize)
            return None

    def _should_trigger_recognize(self, changed_count: int, total_count: int) -> bool:
        """判断是否触发识别"""
        if not self.auto_recognize:
            return False

        # 变化率超过阈值
        if total_count > 0 and changed_count / total_count >= self.min_change_threshold:
            return True

        # 待处理目标数足够多
        if len(self.pending_targets) >= 10:
            return True

        return False

    async def _notify_delta(self, target_id: str, delta: dict):
        """通知目标增量更新"""
        try:
            await websocket_manager.notify_target_update(target_id, delta)
        except Exception as e:
            logger.warning(f"推送增量失败 [{target_id}]: {e}")

    def _parse_to_state(self, data: Dict) -> Optional[TargetState]:
        """解析数据为 TargetState"""
        try:
            import pandas as pd

            timestamp = pd.to_datetime(data.get('时间') or data.get('timestamp'))
            pos = data.get('位置') or data.get('position', [0, 0, 0])

            return TargetState(
                timestamp=timestamp,
                position=GeoPosition(
                    longitude=float(pos[0]),
                    latitude=float(pos[1]),
                    altitude=float(pos[2])
                ),
                heading=float(data.get('航向') or data.get('heading', 0)),
                speed=float(data.get('速度') or data.get('speed', 0))
            )
        except Exception as e:
            logger.error(f"解析失败: {e}, 数据: {data}")
            return None

    def _state_to_dict(self, state: TargetState, target_id: str) -> Dict:
        """State 转 Dict"""
        return {
            'id': target_id,
            '时间': state.timestamp.isoformat(),
            '位置': [state.position.longitude, state.position.latitude, state.position.altitude],
            '航向': state.heading,
            '速度': state.speed
        }

    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return {
            "is_running": self.is_running,
            "auto_recognize": self.auto_recognize,
            "recognize_interval": self.recognize_interval,
            "buffer_size": len(self.buffer),
            "pending_targets": len(self.pending_targets),
            "stats": {
                **self.stats,
                'last_recognize_time': self.stats['last_recognize_time'].isoformat()
                if self.stats['last_recognize_time'] else None
            },
            "engine_status": self.engine.get_cache_status() if self.engine else None
        }

    def get_recent_formations(self, count: int = 10) -> List[Dict]:
        """获取最近识别的编队"""
        return formation_store.get_latest_formations(count)

    def force_recognize(self) -> Dict[str, Any]:
        """强制立即执行识别"""
        if not self.pending_targets:
            return {"message": "没有待处理目标"}

        # 异步执行
        asyncio.create_task(self._do_recognize())

        return {
            "message": "识别已触发",
            "pending_targets": len(self.pending_targets)
        }


# 全局数据流服务实例
stream_service = DataStreamService()