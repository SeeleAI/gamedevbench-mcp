import logging
from contextvars import ContextVar

from config import config

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class CanvasIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.trace_id = _trace_id_var.get()
        except Exception:
            record.trace_id = "-"
        return True


def set_trace_id(trace_id: str):
    return _trace_id_var.set(trace_id or "-")


def reset_trace_id(token) -> None:
    try:
        _trace_id_var.reset(token)
    except Exception:
        pass


def install_logger_filter(logger: logging.Logger | None = None) -> None:
    """Install a logging filter that injects trace_id into all records.

    Attach to the provided logger or the root logger when None.
    """
    target = logger or logging.getLogger()

    # 1) Attach filter to the logger
    if not any(isinstance(f, CanvasIdFilter) for f in target.filters):
        target.addFilter(CanvasIdFilter())

    # 2) Attach filter to all existing handlers (covers cases where handlers format before logger filters run)
    for h in target.handlers:
        if not any(isinstance(f, CanvasIdFilter) for f in getattr(h, "filters", [])):
            h.addFilter(CanvasIdFilter())

    # 3) Ensure every LogRecord has trace_id by default via LogRecordFactory (covers third-party loggers/handlers)
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[no-redef]
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "trace_id"):
            try:
                record.trace_id = _trace_id_var.get()
            except Exception:
                record.trace_id = "-"
        return record

    logging.setLogRecordFactory(record_factory)

def init_logging():
    # Configure logging using settings from config
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format=config.log_format
    )
    install_logger_filter()