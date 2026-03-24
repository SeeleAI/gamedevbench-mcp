"""
通用定时任务调度器实现

基于 APScheduler AsyncIOScheduler，对外提供单例调度器的创建、启停与任务注册。
供 util.schedule 对外暴露，其他模块通过 util.schedule 使用。
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_scheduler: Optional[Any] = None
_initialization_attempted = False  # 防止重复初始化尝试
_managed_by_lifespan = False  # 标记调度器是否由 lifespan 管理


def _get_apscheduler():
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        return AsyncIOScheduler
    except ImportError:
        return None


def init_scheduler() -> Optional[Any]:
    """
    初始化全局调度器并启动。

    若已存在则先关闭再创建。若 APScheduler 未安装则返回 None。
    
    注意：AsyncIOScheduler.start() 需要运行中的事件循环。
    此函数应在异步上下文中调用（如 server_lifespan）。
    """
    global _scheduler, _initialization_attempted
    
    # 如果调度器已经初始化且正在运行，直接返回
    if _scheduler is not None:
        try:
            if _scheduler.running:
                logger.debug("Scheduler already running, skipping re-initialization")
                return _scheduler
        except AttributeError:
            pass
        # 如果调度器存在但不运行，关闭它
        logger.warning("Scheduler exists but not running, shutting down existing scheduler")
        shutdown_scheduler()

    AsyncIOSchedulerCls = _get_apscheduler()
    if AsyncIOSchedulerCls is None:
        logger.error(
            "APScheduler not installed. Please install it with: pip install apscheduler>=3.10.0"
        )
        return None

    try:
        # 检查是否有运行中的事件循环（AsyncIOScheduler.start() 需要）
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            logger.debug(f"Scheduler init: found running event loop {id(loop)}")
        except RuntimeError:
            # 没有运行中的事件循环，AsyncIOScheduler.start() 会失败
            # 记录警告，但继续尝试（某些情况下可能仍然可以工作）
            logger.warning("No running event loop found, AsyncIOScheduler.start() may fail")
        
        _scheduler = AsyncIOSchedulerCls()
        _scheduler.start()
        _initialization_attempted = True
        _managed_by_lifespan = True  # 标记为由 lifespan 管理
        logger.info("Schedule scheduler started successfully")
        return _scheduler
    except RuntimeError as e:
        # 专门处理事件循环相关的错误
        if "no running event loop" in str(e) or "event loop" in str(e).lower():
            logger.error(f"Failed to initialize scheduler: no running event loop. "
                        f"This usually means init_scheduler() was called outside an async context. Error: {e}")
        else:
            logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
        _scheduler = None
        return None
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
        _scheduler = None
        return None


def shutdown_scheduler(force: bool = False) -> None:
    """
    关闭全局调度器并释放资源。
    
    Args:
        force: 如果为 True，强制关闭（即使不是由 lifespan 管理）。默认为 False，只关闭由 lifespan 管理的调度器。
    """
    global _scheduler, _initialization_attempted, _managed_by_lifespan
    if _scheduler is None:
        logger.debug("Scheduler is not running, nothing to shutdown")
        return
    
    # 如果不是由 lifespan 管理，且不是强制关闭，则跳过
    if not force and not _managed_by_lifespan:
        logger.debug("Scheduler not managed by lifespan, skipping shutdown")
        return
    
    try:
        _scheduler.shutdown(wait=True)
        logger.info("Schedule scheduler stopped successfully")
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {e}", exc_info=True)
    finally:
        _scheduler = None
        _initialization_attempted = False
        _managed_by_lifespan = False


def get_scheduler() -> Optional[Any]:
    """返回当前调度器实例，未初始化时返回 None。"""
    return _scheduler


def add_job(
    fn: Any,
    trigger: str = "interval",
    *,
    id: Optional[str] = None,
    replace_existing: bool = True,
    max_instances: int = 1,
    coalesce: bool = True,
    **kwargs: Any,
) -> Optional[Any]:
    """
    向全局调度器添加任务。

    Args:
        fn: 要执行的函数（同步即可，APScheduler 会包装）
        trigger: 触发器类型，如 'interval', 'cron'
        id: 任务 ID，用于 replace_existing
        replace_existing: 同 ID 时是否替换
        max_instances: 最大并发实例数
        coalesce: 错峰时是否合并执行
        **kwargs: 传给 add_job 的其他参数，如 hours=6, args=(...), kwargs={...}

    Returns:
        添加的 Job 实例，若调度器未初始化则返回 None。
    """
    s = get_scheduler()
    if s is None:
        logger.warning("Cannot add job: scheduler not initialized")
        return None
    job_kw = {"replace_existing": replace_existing, "max_instances": max_instances, "coalesce": coalesce}
    if id is not None:
        job_kw["id"] = id
    return s.add_job(fn, trigger, **{**job_kw, **kwargs})
