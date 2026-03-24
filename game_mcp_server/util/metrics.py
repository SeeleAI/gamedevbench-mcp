import time
from functools import wraps
from prometheus_client import Counter, Histogram, Gauge

from config import config

APP_LABEL_VALUE = f"{config.run_platform}-mcp-server"

TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    labelnames=("tool", "status", "application"),
)

TOOL_LATENCY = Histogram(
    "mcp_tool_duration_seconds",
    "MCP tool latency in seconds",
    labelnames=("tool", "status", "application"),
    buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 180.0, 300.0, 600.0, 1200.0, float("inf")),
)

TOOL_INFLIGHT = Gauge(
    "mcp_tool_inflight",
    "Number of in-flight MCP tool calls",
    labelnames=("tool", "application"),
)

BUSINESS_CALLS = Counter(
    "mcp_business_calls_total",
    "Total MCP business calls",
    labelnames=("name", "status", "application"),
)

COMMAND_CALLS = Counter(
    "mcp_command_calls_total",
    "Total MCP command calls",
    labelnames=("command_type", "status", "business_status", "type", "application"),
)

COMMAND_LATENCY = Histogram(
    "mcp_command_duration_seconds",
    "MCP command latency in seconds",
    labelnames=("command_type", "status", "business_status", "type", "application"),
    buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 180.0, 300.0, 600.0, 1200.0, float("inf")),
)


def instrument_tool(tool_name: str):
    def _decorator(func):
        @wraps(func)
        async def _wrapped(*args, **kwargs):
            start = time.perf_counter()
            status = "ok"
            TOOL_INFLIGHT.labels(tool=tool_name, application=APP_LABEL_VALUE).inc()
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                dur = time.perf_counter() - start
                TOOL_CALLS.labels(tool=tool_name, status=status, application=APP_LABEL_VALUE).inc()
                TOOL_LATENCY.labels(tool=tool_name, status=status, application=APP_LABEL_VALUE).observe(dur)
                try:
                    TOOL_INFLIGHT.labels(tool=tool_name, application=APP_LABEL_VALUE).dec()
                except Exception:
                    # Guard against accidental negative due to double-finally; should not happen
                    pass
        return _wrapped
    return _decorator
