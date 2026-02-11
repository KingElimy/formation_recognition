"""
定时清理任务 - 维护Redis数据，清理过期索引
"""
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from cache.formation_store import formation_store
from cache.redis_client import redis_client

logger = logging.getLogger(__name__)


class CleanupScheduler:
    """清理调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.is_running = False

    def start(self):
        """启动调度器"""
        if self.is_running:
            return

        # 每天凌晨2点执行清理
        self.scheduler.add_job(
            self._daily_cleanup,
            trigger=CronTrigger(hour=2, minute=0),
            id="daily_cleanup",
            name="每日数据清理",
            replace_existing=True
        )

        # 每小时执行一次轻量清理
        self.scheduler.add_job(
            self._hourly_cleanup,
            trigger=CronTrigger(minute=0),
            id="hourly_cleanup",
            name="每小时索引清理",
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True
        logger.info("清理调度器已启动")

    def shutdown(self):
        """关闭调度器"""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("清理调度器已关闭")

    def _daily_cleanup(self):
        """每日清理任务"""
        logger.info("开始每日数据清理...")

        try:
            # 清理编队存储中的孤儿索引
            stats = formation_store.cleanup_expired_data()
            logger.info(f"每日清理完成: {stats}")

            # 可以在这里添加其他清理逻辑
            # 例如：清理旧的同步会话、统计信息等

        except Exception as e:
            logger.error(f"每日清理失败: {e}")

    def _hourly_cleanup(self):
        """每小时轻量清理"""
        try:
            # 检查Redis内存使用情况（如果配置了maxmemory）
            info = redis_client.client.info("memory")
            used_memory = info.get("used_memory_human", "unknown")
            logger.debug(f"当前Redis内存使用: {used_memory}")

            # 可以在这里添加轻量级清理逻辑

        except Exception as e:
            logger.error(f"每小时清理失败: {e}")


# 全局调度器实例
cleanup_scheduler = CleanupScheduler()