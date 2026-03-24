"""
通用定时任务调度模块

提供 init_scheduler、shutdown_scheduler、add_job、get_scheduler，
供各服务注册定时任务。具体任务实现放在 util.schedule.jobs 下。
"""

from util.schedule._impl import (
    init_scheduler,
    shutdown_scheduler,
    get_scheduler,
    add_job,
)

__all__ = [
    "init_scheduler",
    "shutdown_scheduler",
    "get_scheduler",
    "add_job",
]
