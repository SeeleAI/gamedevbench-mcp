"""Modify script tool for ThreeJS MCP."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Description variants — switched by fuzzy_modify feature flag
# ---------------------------------------------------------------------------

_DESCRIPTION_EXACT = """
Modify a ThreeJS script file in S3 by replacing specific text.

Args:
    task_name: {{task_name_prompt}}, required
    script_name: Code file name, required
    old_code: Original code text to replace.
              Must exactly match and appear only once in the file, required
    new_code: Replacement code text, required
    return_modified_content: If true, include the full modified file content in response (default False)

Returns:
    Dict[str, Any]: {
        "success": bool,
        "message": str,
        "data": Any (when return_modified_content=True, data includes "modified_content": str)
    }
"""

_DESCRIPTION_FUZZY = """
Modify a ThreeJS script file in S3 by replacing a specific code block.

Args:
    task_name: {{task_name_prompt}}, required
    script_name: Code file name, required
    old_code: The code block to replace. Provide 3-5 lines of surrounding context
              to uniquely identify the target location. Does not need to be
              character-perfect — minor indentation and whitespace differences
              are tolerated. Must identify exactly one location in the file, required
    new_code: Replacement code text, required
    return_modified_content: If true, include the full modified file content in response (default False)

Usage notes:
- Always call read_script before modify_script to verify the exact content
- If the tool reports "ambiguous match", expand old_code with more surrounding lines
- On success, the response includes "matched_strategy" showing which tolerance level was used

Returns:
    Dict[str, Any]: {
        "success": bool,
        "message": str,
        "data": Any
    }
"""


def register_modify_script_tool(mcp: FastMCP, fuzzy_mode: bool = False):
    """
    Register the modify_script tool with the MCP server.

    Args:
        mcp: FastMCP server instance
        fuzzy_mode: If True, use multi-layer fuzzy matching (B group experiment).
                    If False, use original exact-match logic (control group).
    """
    description = _DESCRIPTION_FUZZY if fuzzy_mode else _DESCRIPTION_EXACT

    @mcp.tool(description=description)
    async def modify_script(
        ctx: Context,
        task_name: str,
        script_name: str,
        old_code: str,
        new_code: str,
        return_modified_content: bool = False
    ) -> Dict[str, Any]:
        try:
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id

            if not script_name:
                return {
                    "success": False,
                    "message": "Script name parameter is required",
                    "data": {"error_type": "missing_parameter", "parameter": "script_name"}
                }
            if not old_code:
                return {
                    "success": False,
                    "message": "old_code parameter is required",
                    "data": {"error_type": "missing_parameter", "parameter": "old_code"}
                }
            # new_code 允许为空字符串（表示删除该代码块）

            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                raw = await env_client.scripts_modify(
                    ctx, script_name, old_code, new_code, fuzzy_mode=fuzzy_mode
                )
                logger.info(f"modify_script via env: {script_name}, success={raw.get('success')}")
                if raw.get("success"):
                    result_data: Dict[str, Any] = {
                        "script_name": script_name,
                        "old_code_length": len(old_code),
                        "new_code_length": len(new_code),
                        "replacement_count": 1,
                        "matched_strategy": raw.get("_matched_strategy", "exact"),
                    }
                    want_content = return_modified_content is True or (
                        isinstance(return_modified_content, str)
                        and return_modified_content.strip().lower() == "true"
                    )
                    if want_content and "_modified_content" in raw:
                        result_data["modified_content"] = raw["_modified_content"]
                    return {
                        "success": True,
                        "message": f"Script '{script_name}' modified successfully",
                        "data": result_data,
                    }
                return raw

            # --- Original S3 flow (use_env=False) ---
            s3_storage = await get_s3_storage(canvas_id)
            success, message, current_content = await s3_storage.download_file(script_name)
            if not success:
                return {
                    "success": False,
                    "message": f"Script '{script_name}' does not exist: {message}",
                    "data": {"error_type": "file_not_found", "script_name": script_name}
                }
            if current_content is None:
                return {
                    "success": False,
                    "message": f"Script '{script_name}' downloaded but content is None",
                    "data": {"error_type": "invalid_content", "script_name": script_name}
                }

            # ------------------------------------------------------------------
            # Core replacement logic — exact vs fuzzy depending on mode
            # ------------------------------------------------------------------
            matched_strategy = "exact"

            if not fuzzy_mode:
                # Original exact-match logic
                if old_code not in current_content:
                    return {
                        "success": False,
                        "message": f"Old code not found in script '{script_name}'",
                        "data": {
                            "error_type": "code_not_found",
                            "script_name": script_name,
                            "old_code_length": len(old_code)
                        }
                    }
                count = current_content.count(old_code)
                if count > 1:
                    return {
                        "success": False,
                        "message": (
                            f"Old code appears {count} times in script '{script_name}'. "
                            "It must appear exactly once."
                        ),
                        "data": {
                            "error_type": "multiple_matches",
                            "script_name": script_name,
                            "count": count
                        }
                    }
                new_content = current_content.replace(old_code, new_code, 1)

            else:
                # Fuzzy multi-layer replacement
                from util.fuzzy_replace import (
                    fuzzy_replace,
                    FuzzyReplaceError,
                    FuzzyReplaceAmbiguousError,
                )
                try:
                    new_content, matched_strategy = fuzzy_replace(
                        current_content, old_code, new_code
                    )
                except FuzzyReplaceAmbiguousError as e:
                    return {
                        "success": False,
                        "message": str(e),
                        "data": {
                            "error_type": "multiple_matches",
                            "script_name": script_name,
                        }
                    }
                except FuzzyReplaceError as e:
                    return {
                        "success": False,
                        "message": str(e),
                        "data": {
                            "error_type": "code_not_found",
                            "script_name": script_name,
                            "old_code_length": len(old_code)
                        }
                    }
                except Exception as e:
                    logger.error(f"Unexpected error in fuzzy_replace: {e}")
                    return {
                        "success": False,
                        "message": f"Fuzzy match internal error: {str(e)}",
                        "data": {
                            "error_type": "fuzzy_replace_error",
                            "script_name": script_name,
                        }
                    }

            # ------------------------------------------------------------------
            # Upload modified content back to S3
            # ------------------------------------------------------------------
            success, message, data = await s3_storage.upload_file(
                file_name=script_name,
                content=new_content,
                metadata={"modified_by": "modify_script_tool"}
            )

            if success:
                logger.info(f"Script '{script_name}' modified (strategy: {matched_strategy})")
                result_data: Dict[str, Any] = {
                    "script_name": script_name,
                    "s3_uri": data["s3_uri"],       # type: ignore
                    "s3_key": data["s3_key"],       # type: ignore
                    "old_code_length": len(old_code),
                    "new_code_length": len(new_code),
                    "matched_strategy": matched_strategy,
                }
                want_content = return_modified_content is True or (
                    isinstance(return_modified_content, str)
                    and return_modified_content.strip().lower() == "true"
                )
                if want_content:
                    result_data["modified_content"] = new_content
                return {
                    "success": True,
                    "message": f"Script '{script_name}' modified successfully",
                    "data": result_data
                }
            else:
                logger.error(f"Failed to upload modified script '{script_name}': {message}")
                return {
                    "success": False,
                    "message": f"Failed to save modifications: {message}",
                    "data": {"error_type": "upload_failed", "script_name": script_name}
                }

        except Exception as e:
            logger.error(f"Error in modify_script: {str(e)}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}
