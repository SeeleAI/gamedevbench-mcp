"""
ThreeJS 定时任务生命周期管理

独立管理 ThreeJS 平台的定时任务（调度器）生命周期，与 Unity 连接管理分离。
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from config import RUN_PLATFORM_3JS
from util.schedule import init_scheduler
from util.schedule.jobs import html_bundler_cleanup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def threejs_scheduler_lifespan() -> AsyncIterator[None]:
    """
    ThreeJS 定时任务生命周期管理上下文管理器。
    
    用于独立管理 ThreeJS 平台的定时任务（调度器）生命周期。
    应该在服务启动时调用，确保调度器在整个服务生命周期中运行。
    
    Usage:
        async with threejs_scheduler_lifespan():
            # 服务运行期间
            await server.serve()
    """
    from config import config
    
    # 只在 ThreeJS 模式下初始化
    if config.run_platform != RUN_PLATFORM_3JS:
        yield
        return
    
    scheduler_initialized = False
    
    try:
        # 确保在异步上下文中初始化（AsyncIOScheduler.start() 需要运行中的事件循环）
        try:
            loop = asyncio.get_running_loop()
            logger.debug(f"Initializing ThreeJS scheduler in async context, event loop: {id(loop)}")
        except RuntimeError:
            logger.warning("No running event loop found, scheduler initialization may fail")
        
        if not html_bundler_cleanup.is_enabled():
            logger.info("ThreeJS cleanup disabled via env, schedule not started")
            yield
            return
        
        # 初始化调度器
        s = init_scheduler()
        if s is None:
            logger.warning("ThreeJS schedule init failed (e.g. APScheduler not installed or event loop issue)")
            yield
            return
        
        scheduler_initialized = True
        
        # 注册清理任务
        try:
            ok, reason = html_bundler_cleanup.register()
        except Exception as reg_err:
            ok, reason = False, f"register() raised: {reg_err}"
            logger.warning(f"Failed to register html_bundler cleanup job: {reason}", exc_info=True)
        
        if ok:
            logger.info("ThreeJS schedule + html_bundler cleanup job initialized")
        else:
            # 注册失败时，关闭调度器
            try:
                from util.schedule._impl import shutdown_scheduler
                shutdown_scheduler(force=True)
            except Exception as shut_err:
                logger.warning(f"Error shutting down schedule after register failure: {shut_err}")
            logger.warning("html_bundler job not registered, scheduler stopped; reason=%s", reason)
            scheduler_initialized = False
        
        # 服务运行期间
        yield
        
    except Exception as e:
        logger.warning(f"Failed to initialize ThreeJS schedule/cleanup: {e}", exc_info=True)
        if scheduler_initialized:
            try:
                from util.schedule._impl import shutdown_scheduler
                shutdown_scheduler(force=True)
            except Exception:
                pass
        raise
    finally:
        # 服务关闭时，关闭调度器
        if scheduler_initialized:
            try:
                from util.schedule._impl import shutdown_scheduler
                shutdown_scheduler(force=True)
                logger.info("ThreeJS scheduler stopped during shutdown")
            except Exception as e:
                logger.warning(f"Error shutting down ThreeJS scheduler: {e}")
