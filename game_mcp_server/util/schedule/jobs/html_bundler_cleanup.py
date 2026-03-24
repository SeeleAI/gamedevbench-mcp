"""
html-bundler 临时目录定时清理任务

清理 util.html_bundler 打包产生的 html-bundler- 前缀临时目录。
可通过 register() 注册到 util.schedule 调度器；仅 ThreeJS 等服务按需调用 register。
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PREFIX = "html-bundler-"
DEFAULT_MAX_AGE_HOURS = 3
DEFAULT_INTERVAL_HOURS = 1

ENV_ENABLED = "THREEJS_CLEANUP_ENABLED"
ENV_INTERVAL_HOURS = "THREEJS_CLEANUP_INTERVAL_HOURS"
ENV_MAX_AGE_HOURS = "THREEJS_CLEANUP_MAX_AGE_HOURS"


def cleanup_old_temp_files(
    module: str = "html_bundler",
    temp_base_dir: Optional[Path] = None,
    prefix: Optional[str] = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> Dict[str, Any]:
    """
    清理旧的 html-bundler 临时目录。

    Args:
        module: 占位，兼容调用约定，实际使用 PREFIX
        temp_base_dir: 临时文件根目录，默认 tempfile.gettempdir()
        prefix: 目录前缀，默认 html-bundler-
        max_age_hours: 清理多少小时前的目录

    Returns:
        {"success", "cleaned_count", "cleaned_size_mb", "failed_count", "message"}
    """
    p = prefix if prefix is not None else PREFIX
    base = Path(tempfile.gettempdir()) if temp_base_dir is None else Path(temp_base_dir)

    if not base.exists():
        return {
            "success": False,
            "cleaned_count": 0,
            "cleaned_size_mb": 0.0,
            "failed_count": 0,
            "message": f"Temp directory does not exist: {base}",
        }

    if temp_base_dir is None:
        expected = tempfile.gettempdir()
        if str(base) != expected:
            logger.warning(
                f"Temp directory mismatch: scanning {base}, "
                f"but tempfile.gettempdir() returns {expected}."
            )

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    cleaned_count = 0
    failed_count = 0
    total_size_bytes = 0

    for item in base.iterdir():
        if not item.name.startswith(p) or not item.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(item.stat().st_mtime)
            if mtime >= cutoff:
                continue
            src_subdir = item / "src"
            if not src_subdir.exists() or not src_subdir.is_dir():
                logger.warning(
                    f"Skipping {item.name}: missing 'src' subdirectory, "
                    "may not be a valid html-bundler temp directory"
                )
                continue
            size = _dir_size(item)
            shutil.rmtree(item)
            cleaned_count += 1
            total_size_bytes += size
            logger.info(
                f"Cleaned: {item.name} "
                f"(size: {size / 1024 / 1024:.2f} MB, age: {datetime.now() - mtime})"
            )
        except PermissionError as e:
            failed_count += 1
            logger.warning(f"Permission denied cleaning {item.name}: {e}")
        except FileNotFoundError:
            logger.debug(f"Directory {item.name} no longer exists, skipping")
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to clean {item.name}: {e}", exc_info=True)

    total_mb = total_size_bytes / 1024 / 1024
    if cleaned_count > 0:
        msg = f"Cleaned {cleaned_count} directories ({total_mb:.2f} MB)"
        if failed_count:
            msg += f", {failed_count} failed"
    elif failed_count:
        msg = f"No directories cleaned, {failed_count} failed"
    else:
        msg = f"No old temp directories found (prefix: {p}, max_age: {max_age_hours}h)"
    logger.info(f"html_bundler cleanup: {msg}")
    return {
        "success": True,
        "cleaned_count": cleaned_count,
        "cleaned_size_mb": round(total_mb, 2),
        "failed_count": failed_count,
        "message": msg,
    }


def _dir_size(directory: Path) -> int:
    total = 0
    try:
        for f in directory.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception as e:
        logger.warning(f"Error calculating size for {directory}: {e}")
    return total


def is_enabled() -> bool:
    """是否启用 html-bundler 定时清理（读环境变量 THREEJS_CLEANUP_ENABLED）。"""
    v = os.environ.get(ENV_ENABLED, "true").lower()
    return v in ("true", "1", "yes", "on")


def register() -> Tuple[bool, str]:
    """
    将 html-bundler 清理任务注册到 util.schedule 调度器。

    从环境变量读取配置：
    - THREEJS_CLEANUP_ENABLED: 是否启用（默认 true）
    - THREEJS_CLEANUP_INTERVAL_HOURS: 执行间隔小时（默认 1）
    - THREEJS_CLEANUP_MAX_AGE_HOURS: 清理多少小时前的目录（默认 3）

    调度器须已 init_scheduler()。

    Returns:
        (成功, 失败原因)。成功时 reason 为空；失败时为具体原因，便于排查。
    """
    from util.schedule import add_job, get_scheduler

    if not is_enabled():
        reason = "THREEJS_CLEANUP_ENABLED is false or off"
        logger.info(f"html_bundler cleanup job disabled: {reason}")
        return False, reason

    if get_scheduler() is None:
        reason = "scheduler not initialized (get_scheduler() is None)"
        logger.warning(f"Cannot register html_bundler cleanup: {reason}")
        return False, reason

    try:
        interval = float(os.environ.get(ENV_INTERVAL_HOURS, str(DEFAULT_INTERVAL_HOURS)))
        max_age = float(os.environ.get(ENV_MAX_AGE_HOURS, str(DEFAULT_MAX_AGE_HOURS)))
    except (TypeError, ValueError) as e:
        reason = f"invalid env: {ENV_INTERVAL_HOURS}/{ENV_MAX_AGE_HOURS} must be a number, got {e}"
        logger.error(reason)
        return False, reason

    if interval <= 0 or max_age <= 0:
        reason = f"invalid config: interval={interval}, max_age={max_age} (both must be > 0)"
        logger.error(reason)
        return False, reason

    try:
        job = add_job(
            cleanup_old_temp_files,
            "interval",
            id="cleanup_html_bundler_temp",
            hours=interval,
            args=("html_bundler",),
            kwargs={"max_age_hours": max_age},
        )
    except Exception as e:
        reason = f"add_job raised: {e}"
        logger.error(f"Failed to add html_bundler cleanup job: {reason}", exc_info=True)
        return False, reason

    if job is None:
        reason = "add_job returned None (scheduler may be unusable)"
        logger.warning(reason)
        return False, reason

    logger.info(
        f"Registered html_bundler cleanup job: interval={interval}h, max_age={max_age}h"
    )
    return True, ""
