"""
ThreeJS Runtime - 内置版本

使用 Playwright 执行 ThreeJS 代码并收集控制台日志
采用按需启动策略，用完即销毁，节省资源
"""
from .runtime import (
    execute_threejs_code,
    execute_playability_test,
    get_runtime_stats,
    ThreeJSRuntimeError,
    ThreeJSRuntimeTimeoutError,
    ThreeJSRuntimeExecutionError,
)

__all__ = [
    "execute_threejs_code",
    "execute_playability_test",
    "get_runtime_stats",
    "ThreeJSRuntimeError",
    "ThreeJSRuntimeTimeoutError",
    "ThreeJSRuntimeExecutionError",
]
