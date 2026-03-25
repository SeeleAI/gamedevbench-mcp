"""Run playability test tool for MCP remote project workflows.

在无头浏览器中加载当前远程工作区的全部源文件（多文件、保留目录结构），执行传入的验证脚本，返回可玩性结果。
"""
import logging
import tempfile
import os
import shutil
from typing import Dict, Any, Optional, Tuple

from mcp.server.fastmcp import FastMCP, Context

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.env_client import env_client
from util.threejs_runtime import execute_playability_test
from tools.threejs_tools.storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)


def register_run_playability_test_tool(mcp: FastMCP) -> None:
    """注册可玩性验证 MCP 工具。"""

    @mcp.tool(description="""Run a playability test for the current remote project in a headless browser.

Downloads all remote workspace source files from storage into a temp directory (preserving directory structure), loads index.html as entry, runs the provided test script in the page, and returns a structured result. Workspace is inferred from context. No publish required — this tests current editor state.

The test script runs inside the game page and must set window.__TEST_RESULT__ when done, e.g.:
  window.__TEST_RESULT__ = { passed: true, message: "ok", details: {} };
or
  window.__TEST_RESULT__ = { passed: false, message: "reason", details: {} };

Timeout is server-side.

Args:
    task_name: {{task_name_prompt}}, required.
    test_script: JavaScript string to run in the game page. Must set window.__TEST_RESULT__ with { passed: boolean, message: string, details?: any }.

Returns:
    success: bool — True if the test run completed.
    message: str — Human-readable summary.
    data: dict — run_status; passed; details; execution_error.
    """)
    async def run_playability_test(
        ctx: Context,
        task_name: str,
        test_script: str,
    ) -> Dict[str, Any]:
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id

        if not (test_script and test_script.strip()):
            return _error_result("test_script is required and must be non-empty", "Empty test_script")

        try:
            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                raw = await env_client.runtime_run_playability_test(ctx, test_script, DEFAULT_PLAYABILITY_TIMEOUT)
                logger.info("%s run_playability_test via env, canvas_id=%s", trace_id, canvas_id)
                run_status = raw.get("run_status", "")
                inner_data = raw.get("data") or {}
                passed = inner_data.get("passed")
                if run_status == "valid_result":
                    msg = raw.get("message", "")
                    message = f"Playability test passed. {msg}" if passed is True else f"Playability test did not pass. {msg}"
                elif run_status == "invalid_result":
                    message = raw.get("message", "Script did not set window.__TEST_RESULT__.")
                else:
                    message = raw.get("message", "Test run failed (timeout or error).")
                return {
                    "success": True,
                    "message": message,
                    "data": {
                        "run_status": run_status,
                        "passed": passed,
                        "details": inner_data.get("details"),
                        "execution_error": inner_data.get("execution_error"),
                    },
                }

            # --- Original S3 + local runtime flow (use_env=False only) ---
            entry_path, err = await _prepare_canvas_files(canvas_id, trace_id)
            if entry_path is None:
                assert err is not None
                return err
            temp_dir = os.path.dirname(entry_path)
            try:
                logger.info("%s Run playability test task_name=%s canvas_id=%s", trace_id, task_name, canvas_id)
                result = await execute_playability_test(entry_path, test_script, timeout=DEFAULT_PLAYABILITY_TIMEOUT)
                return _build_tool_result(result)
            finally:
                if temp_dir and os.path.isdir(temp_dir):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except OSError as e:
                        logger.debug("Playability cleanup temp dir %s: %s", temp_dir, e)
        except Exception as e:
            logger.exception("%s run_playability_test error", trace_id)
            return _error_result(str(e), str(e))

    # --- 实现细节（供上面工具闭包引用）---
    DEFAULT_PLAYABILITY_TIMEOUT = 90
    CANVAS_SIZE_LIMIT = 50 * 1024 * 1024

    def _error_result(message: str, execution_error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "message": message,
            "data": {
                "run_status": "script_failed",
                "passed": None,
                "execution_error": execution_error,
            },
        }

    def _build_tool_result(result: Dict[str, Any]) -> Dict[str, Any]:
        run_status = result.get("run_status", "")
        data = result.get("data") or {}
        passed = data.get("passed")
        if run_status == "valid_result":
            success = True
            msg = result.get("message", "Playability test completed.")
            message = f"Playability test passed. {msg}" if passed is True else f"Playability test did not pass. {msg}"
        elif run_status == "invalid_result":
            success = True
            message = result.get("message", "Script did not set window.__TEST_RESULT__.")
        else:
            success = True
            message = result.get("message", "Test run failed (timeout or error).")
        return {
            "success": success,
            "message": message,
            "data": {
                "run_status": run_status,
                "passed": passed,
                "details": data.get("details"),
                "execution_error": data.get("execution_error"),
            },
        }

    async def _prepare_canvas_files(canvas_id: str, trace_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """拉取画布全部文件到临时目录，返回 (index.html 入口路径, None)；失败返回 (None, 错误工具结果 dict)."""
        s3_storage = await get_s3_storage(canvas_id)
        success, message, files_data = await s3_storage.list_files()
        if not success:
            return None, _error_result(f"Failed to list canvas files: {message}", message)
        if not files_data:
            return None, _error_result("No files found in canvas.", "No files")

        total_size = sum(f.get("size") or 0 for f in files_data)
        if total_size > CANVAS_SIZE_LIMIT:
            return None, _error_result(
                f"Canvas files total size ({total_size} bytes) exceeds {CANVAS_SIZE_LIMIT} bytes limit.",
                "size_limit_exceeded",
            )

        file_names = [f["file_name"] for f in files_data]
        if "index.html" not in file_names:
            return None, _error_result("Canvas has no index.html.", "missing index.html")

        temp_dir = tempfile.mkdtemp(prefix="playability_canvas_")
        try:
            for file_info in files_data:
                file_name = file_info.get("file_name") or ""
                if not file_name.strip():
                    continue
                ok, msg, content = await s3_storage.download_file(file_name, max_retries=2)
                if not ok or content is None:
                    logger.warning("%s playability: failed to download %s: %s", trace_id, file_name, msg)
                    continue
                local_path = os.path.join(temp_dir, file_name)
                # 防止 path traversal：只允许写入 temp_dir 下
                real_path = os.path.realpath(local_path)
                real_base = os.path.realpath(temp_dir)
                if not (real_path == real_base or real_path.startswith(real_base + os.sep)):
                    logger.warning("%s playability: skip path escape file_name=%s", trace_id, file_name)
                    continue
                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)
            entry_path = os.path.join(temp_dir, "index.html")
            if not os.path.isfile(entry_path):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except OSError:
                    pass
                return None, _error_result(
                    "index.html could not be written to temp dir.",
                    "index.html missing after download",
                )
            return entry_path, None
        except Exception as e:
            if temp_dir and os.path.isdir(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except OSError:
                    pass
            logger.exception("%s _prepare_canvas_files error", trace_id)
            return None, _error_result(str(e), str(e))
