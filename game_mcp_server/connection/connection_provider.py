import logging
import time
import traceback
from typing import Dict, Any

from mcp.server.fastmcp import Context

from config import config, SERVER_START_REMOTE_MODE, RUN_PLATFORM_BLENDER
from connection.connection_interface import ConnectionInterface

logger = logging.getLogger(__name__)


def get_current_connection(ctx: Context | None = None) -> ConnectionInterface:
    """Return a Unity connection instance based on startup mode."""
    if config.start_mode == SERVER_START_REMOTE_MODE:

        if config.run_platform == RUN_PLATFORM_BLENDER:
            from connection.blender_connection_remote_delegate import BlenderConnectionRemoteDelegate
            return BlenderConnectionRemoteDelegate(ctx)
        else:
            from connection.connection_remote_delegate import (
                ConnectionRemoteDelegate,
            )
            return ConnectionRemoteDelegate(ctx)
    else:
        if config.run_platform == RUN_PLATFORM_BLENDER:
            from connection.blender_connection_local import get_blender_connection_local

            return get_blender_connection_local()
        else:
            from connection.unity_http_connection import get_unity_connection_local

            return get_unity_connection_local()


def _is_reloading_response(resp: dict) -> bool:
    """Return True if the Unity response indicates the editor is reloading."""
    if not isinstance(resp, dict):
        return False
    if resp.get("state") == "reloading":
        return True
    message_text = (resp.get("message") or resp.get("error") or "").lower()
    return "reload" in message_text


async def async_send_command_with_retry(
    ctx: Context,
    command_type: str,
    params: Dict[str, Any],
    *,
    loop=None,
    max_retries: int | None = None,
    retry_ms: int | None = None,
) -> Dict[str, Any]:
    """Async wrapper that runs the blocking retry helper in a thread pool."""
    try:
        conn = get_current_connection(ctx)

        response = await conn.send_command(command_type, params)
        # 非远程模式下，支持重试机制
        if config.start_mode != SERVER_START_REMOTE_MODE:
            if max_retries is None:
                max_retries = getattr(config, "reload_max_retries", 40)
            if retry_ms is None:
                retry_ms = getattr(config, "reload_retry_ms", 250)
            retries = 0
            while _is_reloading_response(response) and retries < max_retries:
                logger.info(f"async_send_command_with_retry retrying {command_type} due to reload response: {response}")
                delay_ms = (
                    int(response.get("retry_after_ms", retry_ms))
                    if isinstance(response, dict)
                    else retry_ms
                )
                time.sleep(max(0.0, delay_ms / 1000.0))
                retries += 1
                response = await conn.send_command(command_type, params)
        return response
    except Exception as e:
        logger.info(f"send command with retry failed: {str(e)} {traceback.format_exc()}")
        return {
            "success": False,
            "error": f"send command failed: {str(e)}",
        }
