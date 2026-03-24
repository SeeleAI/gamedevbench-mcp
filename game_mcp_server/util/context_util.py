import logging
import sys
from typing import Any, Optional

from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)


def _get_request_headers(ctx: Context) -> dict[str, Any]:
    try:
        request = ctx.request_context.request
        headers = getattr(request, "headers", None)
        if not headers:
            return {}
        # Starlette Headers is case-insensitive but not a plain dict.
        return dict(headers.items())
    except Exception as e:
        logger.debug(f"Failed to get request headers from request object: {e}")
        return {}


def _get_meta_headers(ctx: Context) -> dict[str, Any]:
    try:
        meta = ctx.request_context.meta
        if meta is None or meta.model_extra is None:
            return {}
        return meta.model_extra.get("headers", {}) or {}
    except Exception as e:
        logger.debug(f"Failed to get context headers from meta: {e}")
        return {}


def get_context_header_value(ctx: Context, key: Optional[str] = None) -> Any | None:
    request_headers = _get_request_headers(ctx)
    meta_headers = _get_meta_headers(ctx)
    request_canvas_id = request_headers.get("x-canvas-id")
    meta_canvas_id = meta_headers.get("x-canvas-id")
    print(
        "[context_util] request_canvas_id="
        f"{request_canvas_id} meta_canvas_id={meta_canvas_id} "
        f"request_header_keys={sorted(request_headers.keys())[:8]} "
        f"meta_header_keys={sorted(meta_headers.keys())[:8]}",
        file=sys.stderr,
        flush=True,
    )

    if key:
        return request_headers.get(key) or meta_headers.get(key)

    combined = dict(meta_headers)
    combined.update(request_headers)
    return combined or None


def get_context_canvas_id(ctx: Context) -> str:
    return get_context_header_value(ctx, "x-canvas-id")


def get_context_mcp_request_id(ctx: Context) -> str:
    return get_context_header_value(ctx, "x-mcp-request-id")


def get_context_x_thread_id(ctx: Context) -> str:
    return get_context_header_value(ctx, "x-thread-id")


def get_context_x_seele_canvas_trace_id(ctx: Context) -> str:
    return get_context_header_value(ctx, "x-seele-canvas-trace-id")
