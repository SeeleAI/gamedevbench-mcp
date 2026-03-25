"""Read remote project file tool for MCP."""
import logging
from typing import Dict, Any, Optional, Tuple
from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Description variants — switched by grep_read_v2 feature flag
# ---------------------------------------------------------------------------

_DESCRIPTION_V1 = """
Read a file from the remote project workspace storage.

For Godot-oriented tasks, call this BEFORE modify_script/rewrite_script
to capture current content and avoid stale replacements.

Use this tool to inspect existing implementation before editing, compare
remote file state with local expectations, or confirm whether a target file
already exists in the MCP-managed project snapshot.

If the path is unknown, call list_script first.

Args:
    task_name: {{task_name_prompt}}, required
    script_name: Name of the file to read (for example "player.gd", "main.tscn", "ui_theme.tres", "project.godot"), required

Returns:
    Dict[str, Any]: {
        "success": bool,
        "message": str,
        "data": str  # The script content
    }
"""

_DESCRIPTION_V2 = """
Read a file from remote project workspace storage with optional line-range slicing.

Args:
    task_name: {{task_name_prompt}}, required
    script_name: Name of the file to read (for example "player.gd", "main.tscn", "ui_theme.tres", "project.godot"), required
    offset: First line to return, 1-based (default: 1 = start of file). optional
    limit: Maximum number of lines to return (default: 0 = all lines). optional

Output format: each line is prefixed with "LINE | " so you can reference exact positions.
Prefer reading a focused range after using grep_script to locate the target area,
rather than reading the entire file every time.

Returns:
    Dict[str, Any]: {
        "success": bool,
        "message": str,
        "data": str,         # Line-numbered content
        "metadata": {
            "script_name": str,
            "total_lines": int,
            "returned_lines": int,
            "offset": int,
            "limit": int
        }
    }
"""


def _add_line_numbers(content: str, offset: int = 1, limit: int = 0) -> Tuple[str, int, int]:
    """
    Return (numbered_text, total_lines, returned_lines).

    offset: 1-based start line
    limit:  max lines to return, 0 = all
    """
    all_lines = content.split('\n')
    total = len(all_lines)

    start = max(0, offset - 1)       # convert 1-based to 0-based
    if limit and limit > 0:
        end = min(start + limit, total)
    else:
        end = total

    selected = all_lines[start:end]
    width = len(str(total))           # pad line numbers to same width
    numbered = '\n'.join(
        f"{start + i + 1:>{width}} | {line}"
        for i, line in enumerate(selected)
    )
    return numbered, total, len(selected)


def register_read_script_tool(mcp: FastMCP, v2_mode: bool = False):
    """
    Register the read_script tool.

    Args:
        mcp: FastMCP server instance
        v2_mode: If True, add line numbers + offset/limit (A group experiment).
                 If False, use original plain-content logic (control group).
    """
    description = _DESCRIPTION_V2 if v2_mode else _DESCRIPTION_V1

    if v2_mode:
        @mcp.tool(description=description)
        async def read_script(
            ctx: Context,
            task_name: str,
            script_name: str,
            offset: Optional[int] = 1,
            limit: Optional[int] = 0,
        ) -> Dict[str, Any]:
            return await _read_impl(ctx, script_name, offset or 1, limit or 0, v2=True)
    else:
        @mcp.tool(description=description)
        async def read_script(
            ctx: Context,
            task_name: str,
            script_name: str,
        ) -> Dict[str, Any]:
            return await _read_impl(ctx, script_name, 1, 0, v2=False)


async def _read_impl(
    ctx: Context,
    script_name: str,
    offset: int,
    limit: int,
    v2: bool,
) -> Dict[str, Any]:
    try:
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id

        if not script_name:
            return {
                "success": False,
                "message": "Script name parameter is required",
                "data": {"error_type": "missing_parameter", "parameter": "script_name"}
            }

        # --- Route to env service if enabled ---
        if config.threejs.use_env and config.threejs.env_service_url:
            raw = await env_client.scripts_read(ctx, script_name)
            logger.info(f"read_script via env: {script_name}, success={raw.get('success')}")
            if raw.get("success"):
                content = raw.get("content", "")
                if v2:
                    numbered, total_lines, returned_lines = _add_line_numbers(content, offset, limit)
                    return {
                        "success": True,
                        "message": f"Script '{script_name}' read from env",
                        "data": numbered,
                        "metadata": {
                            "script_name": script_name,
                            "file_exists": bool(content),
                            "total_lines": total_lines,
                            "returned_lines": returned_lines,
                            "offset": offset,
                            "limit": limit,
                        },
                    }
                return {
                    "success": True,
                    "message": f"Script '{script_name}' read from env",
                    "data": content,
                    "metadata": {
                        "script_name": script_name,
                        "file_exists": bool(content),
                        "code_length": len(content),
                    },
                }
            # env said file not found
            base_meta: Dict[str, Any] = {"script_name": script_name, "file_exists": False}
            if v2:
                base_meta.update({"total_lines": 0, "returned_lines": 0, "offset": offset, "limit": limit})
            else:
                base_meta["code_length"] = 0
            return {
                "success": True,
                "message": f"File '{script_name}' does not exist",
                "data": "",
                "metadata": base_meta,
            }

        # --- Original S3 flow (use_env=False) ---
        s3_storage = await get_s3_storage(canvas_id)
        success, message, content = await s3_storage.download_file(script_name)

        if success:
            if content is None:
                return {
                    "success": False,
                    "message": "File downloaded but content is None",
                    "data": {"error_type": "invalid_content", "script_name": script_name}
                }

            logger.info(f"Script '{script_name}' read from S3, length: {len(content)}")
            s3_uri = f"s3://{s3_storage.bucket_name}/{s3_storage.base_prefix}{script_name}"

            if v2:
                numbered, total_lines, returned_lines = _add_line_numbers(content, offset, limit)
                return {
                    "success": True,
                    "message": message,
                    "data": numbered,
                    "metadata": {
                        "script_name": script_name,
                        "file_exists": True,
                        "s3_uri": s3_uri,
                        "total_lines": total_lines,
                        "returned_lines": returned_lines,
                        "offset": offset,
                        "limit": limit,
                    }
                }
            else:
                return {
                    "success": True,
                    "message": message,
                    "data": content,
                    "metadata": {
                        "script_name": script_name,
                        "file_exists": True,
                        "s3_uri": s3_uri,
                        "code_length": len(content)
                    }
                }

        else:
            file_not_exist_message = f"File '{script_name}' does not exist in S3"
            if message == file_not_exist_message:
                logger.info(f"Script '{script_name}' does not exist in S3")
                base_meta: Dict[str, Any] = {
                    "script_name": script_name,
                    "file_exists": False,
                }
                if v2:
                    base_meta.update({"total_lines": 0, "returned_lines": 0,
                                      "offset": offset, "limit": limit})
                else:
                    base_meta["code_length"] = 0
                return {
                    "success": True,
                    "message": file_not_exist_message,
                    "data": "",
                    "metadata": base_meta,
                }

            logger.warning(f"Failed to read script '{script_name}': {message}")
            return {
                "success": False,
                "message": message,
                "data": {"error_type": "read_failed", "script_name": script_name}
            }

    except Exception as e:
        logger.error(f"Error in read_script: {str(e)}")
        return {"success": False, "message": f"Python error: {str(e)}", "data": None}
