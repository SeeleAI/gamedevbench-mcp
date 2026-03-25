"""
grep_script tool for MCP remote project workflows.

In-memory regex search across workspace files stored in remote storage.
Inspired by OpenCode's grep tool (ripgrep-based) but adapted for
cloud-stored files: downloads all files into memory, then searches.
"""
import re
import asyncio
import logging
from typing import Dict, Any, List, Optional

from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

DESCRIPTION = """
Search for a regex pattern across all project files in the current remote workspace.

Each matched line is returned with its file name and line number so you can
immediately follow up with read_script using offset/limit to view the context,
then modify_script to apply changes — without reading every file in full.

Args:
    task_name: {{task_name_prompt}}, required
    pattern: Regular expression pattern to search for (Python re syntax), required
    file_glob: Optional filename filter (e.g. "*.gd", "*.tscn", "*.json", "game*"). Defaults to all files.
    case_sensitive: Whether the match is case-sensitive (default: true), optional
    max_results: Maximum number of matching lines to return (default: 100), optional

Output format:
    Each match is one line: "filename:LINE_NUMBER: matched_line_content"
    Results are sorted by filename then line number.

Returns:
    Dict[str, Any]: {
        "success": bool,
        "message": str,
        "data": {
            "matches": [str],         # list of "file:line: content" strings
            "match_count": int,
            "files_searched": int,
            "truncated": bool         # true when max_results was reached
        }
    }
"""


def _filename_matches_glob(filename: str, glob_pattern: str) -> bool:
    """Simple glob matcher supporting * wildcard only."""
    import fnmatch
    return fnmatch.fnmatch(filename, glob_pattern)


def register_grep_script_tool(mcp: FastMCP):
    """Register the grep_script tool (only called when grep_read_v2 is enabled)."""

    @mcp.tool(description=DESCRIPTION)
    async def grep_script(
        ctx: Context,
        task_name: str,
        pattern: str,
        file_glob: Optional[str] = None,
        case_sensitive: Optional[bool] = True,
        max_results: Optional[int] = 100,
    ) -> Dict[str, Any]:
        try:
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id

            if not pattern:
                return {
                    "success": False,
                    "message": "pattern parameter is required",
                    "data": {"error_type": "missing_parameter", "parameter": "pattern"}
                }

            # Compile regex
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(pattern, flags)
            except re.error as e:
                return {
                    "success": False,
                    "message": f"Invalid regex pattern: {e}",
                    "data": {"error_type": "invalid_pattern", "pattern": pattern}
                }

            limit = max_results if max_results and max_results > 0 else 100

            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                # Env service always uses default flags; embed (?i) when case-insensitive
                env_pattern = f"(?i){pattern}" if not case_sensitive else pattern
                raw = await env_client.scripts_grep(ctx, env_pattern)
                logger.info(f"grep_script via env: canvas {canvas_id}, success={raw.get('success')}")
                if raw.get("success"):
                    matches = raw.get("matches", [])
                    # Apply max_results limit (env doesn't support it natively)
                    truncated = len(matches) > limit
                    matches = matches[:limit]
                    return {
                        "success": True,
                        "message": (
                            f"Found {len(matches)} match(es)"
                            + (" (truncated)" if truncated else "")
                        ),
                        "data": {
                            "matches": matches,
                            "match_count": len(matches),
                            "files_searched": None,
                            "truncated": truncated,
                        },
                    }
                return raw

            # ------------------------------------------------------------------
            # Step 1: List all files for this canvas
            # ------------------------------------------------------------------
            s3_storage = await get_s3_storage(canvas_id)
            ok, msg, file_list = await s3_storage.list_files()
            if not ok or not file_list:
                return {
                    "success": True,
                    "message": "No script files found for this canvas",
                    "data": {
                        "matches": [],
                        "match_count": 0,
                        "files_searched": 0,
                        "truncated": False
                    }
                }

            # Apply optional filename glob filter
            if file_glob:
                file_list = [f for f in file_list if _filename_matches_glob(f["file_name"], file_glob)]

            if not file_list:
                return {
                    "success": True,
                    "message": f"No files match glob '{file_glob}'",
                    "data": {
                        "matches": [],
                        "match_count": 0,
                        "files_searched": 0,
                        "truncated": False
                    }
                }

            # ------------------------------------------------------------------
            # Step 2: Download all files concurrently
            # ------------------------------------------------------------------
            async def _download(file_info: dict):
                name = file_info["file_name"]
                try:
                    dl_ok, _, file_content = await s3_storage.download_file(name)
                    return name, file_content if dl_ok else None
                except Exception as e:
                    logger.warning(f"grep_script: failed to download '{name}': {e}")
                    return name, None

            downloads = await asyncio.gather(*[_download(f) for f in file_list])

            # ------------------------------------------------------------------
            # Step 3: Search in memory
            # ------------------------------------------------------------------
            matches: List[str] = []
            truncated = False
            files_searched = 0

            for filename, content in sorted(downloads, key=lambda x: x[0]):
                if content is None:
                    continue
                files_searched += 1
                for lineno, line in enumerate(content.split('\n'), start=1):
                    if compiled.search(line):
                        matches.append(f"{filename}:{lineno}: {line.rstrip()}")
                        if len(matches) >= limit:
                            truncated = True
                            break
                if truncated:
                    break

            return {
                "success": True,
                "message": (
                    f"Found {len(matches)} match(es) across {files_searched} file(s)"
                    + (" (truncated)" if truncated else "")
                ),
                "data": {
                    "matches": matches,
                    "match_count": len(matches),
                    "files_searched": files_searched,
                    "truncated": truncated,
                }
            }

        except Exception as e:
            logger.error(f"Error in grep_script: {e}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}
