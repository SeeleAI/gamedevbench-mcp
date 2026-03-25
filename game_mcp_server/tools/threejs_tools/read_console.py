"""Read remote project execution logs tool for MCP."""
import logging
import json
import asyncio
import os
import aiohttp
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.env_client import env_client
from util.threejs_utils import bundle_canvas_files
from util.threejs_runtime import (
    execute_threejs_code,
    ThreeJSRuntimeError,
    ThreeJSRuntimeTimeoutError,
    ThreeJSRuntimeExecutionError
)

logger = logging.getLogger(__name__)

def register_read_console_tool(mcp: FastMCP):
    """Register the read_console tool with the MCP server."""

    @mcp.tool(description="""
        Read logs from the remote project execution and validation pipeline. Supports
        two modes: build/check logs and runtime logs.

        Godot-oriented usage note:
        - Use this mainly as a remote pipeline/runtime signal tool after file edits.
        - It is NOT a native Godot engine/GDScript compiler. Script-level changes should
          primarily rely on list_script/read_script/modify_script/rewrite_script workflow.
        
        MODE 1 - Compile mode (log_mode="compile", default):
        - Automatically prepares the remote project files for execution in the current runtime pipeline
        - Runs the prepared build and returns build/execution logs
        - The preparation process is transparent and may use caching when available
        - Use this mode to CHECK whether the current implementation has execution errors
        
        MODE 2 - Runtime mode (log_mode="runtime"):
        - Retrieves runtime logs emitted during actual execution
        - Calls the backend log API to get logs reported by the running project
        - Useful for debugging behavior after the project has been launched or exercised
        - May take up to 5 minutes to wait for logs (backend interface timeout)
        
        Args:
            task_name: {{task_name_prompt}},required
            lines: Number of last lines to read from console logs (default: 10)
            console_type: Log type filter - "info" (all non-error logs) or "error" (only error logs) (default: "error")
            log_mode: Log mode - "compile" (compile-time logs) or "runtime" (runtime logs from frontend) (default: "compile")
            
        Returns (Compile mode):
            Dict[str, Any]: {
                "success": bool,  # True if the code check process completed successfully, False if the check process failed
                                  # IMPORTANT: success=True means the check was able to run, NOT that the code is correct
                "message": str,   # The console logs content or status message:
                                  # - When console_type="error" and no errors: "No errors found. Code check passed."
                                  # - When console_type="error" and errors found: Contains the actual error log messages
                                  # - When console_type="info" and has info logs: Contains the actual info log messages
                                  # - When console_type="info" and no info logs: "No info logs found."
                "data": {
                    "canvas_id": str,
                    "has_errors": bool  # True if errors were found (only meaningful when console_type="error")
                                        # When console_type="error": has_errors=False means code is correct (test PASSED)
                                        # When console_type="error": has_errors=True means code has errors (test FAILED)
                }
            }
            
        Returns (Runtime mode):
            Dict[str, Any]: {
                "success": bool,  # True if successfully called the API, False if connection failed
                "message": str,   # Status message: "Runtime logs retrieved successfully" or "No runtime logs found"
                "data": {
                    "canvas_id": str,
                    "logMessage": str  # The actual runtime log content (may be long)
                }
            }
            
        IMPORTANT INTERPRETATION GUIDE (Compile mode):
        - The "success" field indicates whether the CHECK PROCESS completed, NOT whether the code is correct
        - To determine if code has errors (when console_type="error"):
          * Check data.has_errors: False = no errors found (code is correct, test PASSED)
          * Check data.has_errors: True = errors found (code has problems, test FAILED)
        - The "message" field:
          * When console_type="error" and no errors: "No errors found. Code check passed."
          * When console_type="error" and errors found: Contains the actual error log messages
          * When console_type="info" and has info logs: Contains the actual info log messages
          * When console_type="info" and no info logs: "No info logs found."
        - success=False: The check process itself failed - this is a process error, not a code error
        - CRITICAL: Use data.has_errors to determine if code has errors, NOT the success field
        
        IMPORTANT INTERPRETATION GUIDE (Runtime mode):
        - The actual log content is in data.logMessage, not in the message field
        - message field only contains status information ("Runtime logs retrieved successfully" or "No runtime logs found")
        - If you need to analyze the logs, read from data.logMessage
        """)
    async def read_console(
        ctx: Context,
        task_name: str,
        lines: int = 10,
        console_type: str = "error",
        log_mode: str = "compile"
    ) -> Dict[str, Any]:

        try:
            # Get canvas_id for project isolation
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
            
            # Validate parameters
            if lines <= 0:
                return {
                    "success": False,
                    "message": "Lines parameter must be greater than 0",
                    "data": {
                        "log_mode": log_mode if log_mode in ["compile", "runtime"] else "unknown",  # 如果 log_mode 有效则使用，否则标记为 unknown
                        "error_type": "invalid_parameter",
                        "parameter": "lines",
                        "value": lines
                    }
                }
            
            if console_type not in ["info", "error"]:
                return {
                    "success": False,
                    "message": "Console type must be 'info' or 'error'",
                    "data": {
                        "log_mode": log_mode if log_mode in ["compile", "runtime"] else "unknown",  # 如果 log_mode 有效则使用，否则标记为 unknown
                        "error_type": "invalid_parameter",
                        "parameter": "console_type",
                        "value": console_type
                    }
                }
            
            if log_mode not in ["compile", "runtime"]:
                return {
                    "success": False,
                    "message": "Log mode must be 'compile' or 'runtime'",
                    "data": {
                        "log_mode": "unknown",  # log_mode 本身无效，标记为 unknown
                        "error_type": "invalid_parameter",
                        "parameter": "log_mode",
                        "value": log_mode
                    }
                }
            
            # Runtime mode: 调用 Java 接口获取运行时日志
            if log_mode == "runtime":
                return await _read_console_runtime(ctx, canvas_id, lines, console_type)
            
            # Compile mode: --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                raw = await env_client.runtime_read_console(ctx, lines, console_type)
                logger.info(f"read_console(compile) via env: canvas {canvas_id}, success={raw.get('success')}")
                if raw.get("success"):
                    logs = raw.get("logs", "")
                    has_errors = raw.get("has_errors", False)
                    if logs:
                        message_text = logs
                    elif console_type == "error":
                        message_text = "No errors found. Code check passed."
                    else:
                        message_text = "No info logs found."
                    return {
                        "success": True,
                        "message": message_text,
                        "data": {
                            "canvas_id": canvas_id,
                            "log_mode": "compile",
                            "has_errors": has_errors,
                        },
                    }
                return {
                    "success": False,
                    "message": raw.get("message", "Env read_console failed"),
                    "data": {
                        "canvas_id": canvas_id,
                        "log_mode": "compile",
                        "has_errors": True,
                    },
                }

            # Compile mode (use_env=False only): 使用 3JS-Runtime 获取编译/执行日志
            # 1. 先进行打包：将多个文件打包成 index.html
            logger.info(f"Bundling files for canvas {canvas_id} before read_console")
            bundle_result = await bundle_canvas_files(canvas_id)
            
            if not bundle_result.get("success"):
                error_type = bundle_result.get("data", {}).get("error_type", "bundle_failed")
                return {
                    "success": False,
                    "message": bundle_result.get("message", "Failed to bundle files"),
                    "data": {
                        "log_mode": "compile",  # 标识这是 compile 模式
                        "error_type": error_type,
                        "canvas_id": canvas_id
                    }
                }
            
            logger.info(f"Successfully bundled files for canvas {canvas_id}")
            
            # 2. 获取打包后的 HTML 文件路径（优先使用文件路径，避免内存占用）
            bundle_data = bundle_result.get("data", {})
            html_file_path = bundle_data.get("bundled_html_path")
            
            # 3. 使用内置 Runtime 执行代码
            logger.info(f"Executing ThreeJS code with internal runtime (console_type={console_type}, lines={lines})")
            
            runtime_timeout = config.threejs.runtime_timeout  # 从配置读取
            
            try:
                # 使用文件路径（避免大文件占用内存）
                # bundle_files_dict 总是返回 bundled_html_path，所以这里应该总是存在
                if not html_file_path:
                    logger.error(f"Bundled HTML path not found in bundle result for canvas {canvas_id}")
                    return {
                        "success": False,
                        "message": "Failed to bundle files: bundled_html_path not found in bundle result",
                        "data": {
                            "log_mode": "compile",  # 标识这是 compile 模式
                            "error_type": "bundle_failed",
                            "canvas_id": canvas_id,
                            "details": "Local bundling should always return bundled_html_path"
                        }
                    }
                
                logger.info(f"Using bundled HTML file path: {html_file_path}")
                result = await execute_threejs_code(
                    html_file_path=html_file_path,
                    console_type=console_type,
                    lines=lines,
                    timeout=runtime_timeout
                )
                
                # 执行成功：直接使用返回的日志数据
                logs = result.get("logs", "")
                filtered_logs = result.get("filtered_logs", 0)
                
                # 计算是否有错误（当 console_type="error" 时，filtered_logs > 0 表示有错误）
                has_errors = (console_type == "error" and filtered_logs > 0)
                
                # 当没有匹配的日志时，返回明确的状态消息，而不是空字符串
                if logs:
                    # 有日志时返回日志内容
                    message = logs
                elif console_type == "error":
                    # 没有错误日志时，返回明确的状态消息
                    message = "No errors found. Code check passed."
                else:
                    # console_type="info" 且没有 info 日志时，返回明确的状态消息
                    message = "No info logs found."
                
                # 准备返回结果
                return_result = {
                    "success": True,
                    "message": message,
                    "data": {
                        "canvas_id": canvas_id,
                        "log_mode": "compile",  # 标识这是 compile 模式
                        "has_errors": has_errors  # 明确标识是否有错误（当 console_type="error" 时）
                    }
                }
                
                return return_result
                
            except ThreeJSRuntimeTimeoutError as e:
                # 超时错误
                return {
                    "success": False,
                    "message": str(e),
                    "data": {
                        "log_mode": "compile",  # 标识这是 compile 模式
                        "error_type": "execution_timeout",
                        "timeout_seconds": e.timeout_seconds,
                        "canvas_id": canvas_id
                    }
                }
            except (ThreeJSRuntimeError, ValueError) as e:
                # 执行错误或参数错误
                return {
                    "success": False,
                    "message": str(e),
                    "data": {
                        "log_mode": "compile",  # 标识这是 compile 模式
                        "error_type": "execution_failed",
                        "canvas_id": canvas_id,
                        "error": str(e)
                    }
                }
            finally:
                # 清理：释放 bundle_data 内存
                # 注意：bundle_files_dict 不再返回 bundled_html 字段，只返回 bundled_html_path
                # 这里清理 bundle_data 主要是为了释放字典本身的内存
                if bundle_data:
                    bundle_data.clear()
                    logger.debug("Cleared bundle_data")
            
        except Exception as e:
            error_msg = str(e) if str(e) else repr(e)
            logger.error(f"Error in read_console: {error_msg}", exc_info=True)
            return {
                "success": False,
                "message": f"Python error: {error_msg}",
                "data": {
                    "log_mode": log_mode,  # 标识模式（函数参数，总是存在）
                    "error_type": "python_exception",
                    "exception_type": type(e).__name__,
                    "canvas_id": canvas_id if 'canvas_id' in locals() else None
                }
            }


async def _read_console_runtime(
    ctx: Context,
    canvas_id: str,
    lines: int,
    console_type: str
) -> Dict[str, Any]:
    """
    Runtime mode: 调用 Java 接口获取运行时日志
    
    Args:
        ctx: MCP Context 对象
        canvas_id: 画布 ID
        lines: 日志行数限制
        console_type: 日志类型 ("info" 或 "error")
        
    Returns:
        Dict[str, Any]: 返回格式与 compile 模式对齐
    """
    try:
        # 获取 turnId
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        if not trace_id:
            return {
                "success": False,
                "message": "Missing trace_id in context, cannot determine turnId",
                "data": {
                    "log_mode": "runtime",  # 标识这是 runtime 模式
                    "error_type": "missing_trace_id",
                    "canvas_id": canvas_id
                }
            }
        
        if "|" in trace_id:
            turn_id = trace_id.split("|")[1]
        else:
            turn_id = trace_id  # 如果没有分隔符，使用整个 trace_id
        
        # 验证 turnId 不为空
        if not turn_id:
            return {
                "success": False,
                "message": "turnId is empty, cannot call runtime log API",
                "data": {
                    "log_mode": "runtime",  # 标识这是 runtime 模式
                    "error_type": "empty_turn_id",
                    "canvas_id": canvas_id,
                    "trace_id": trace_id
                }
            }
        
        # 转换 console_type 到 logLevel（console_type 已在主函数中验证，这里直接映射）
        log_level_map = {
            "info": "INFO",
            "error": "ERROR"
        }
        log_level = log_level_map[console_type]  # 直接使用，不需要默认值
        
        # 调用 Java 接口（生产接口）
        url = f"{config.app_base_url}/app/innerapi/tool/read-console"
        headers = {
            "Content-Type": "application/json",
            "token": "seele_koko_pwd",
            "x-canvas-id": canvas_id,
        }
        
        payload = {
            "canvasId": canvas_id,
            "turnId": turn_id,
            "logLimit": lines,
            "logLevel": log_level
        }
        
        logger.info(f"Calling runtime log API for canvas {canvas_id}, turnId: {turn_id}, logLevel: {log_level}")
        
        # 超时时间：Java 接口等待前端上报日志的超时是 5 分钟，MCP 等待 Java 接口响应也设置为 5 分钟
        timeout = aiohttp.ClientTimeout(total=300)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    # 直接尝试解析响应，不管状态码（与 compile 模式保持一致）
                    try:
                        result = await response.json()
                        log_message = result.get("logMessage", "")
                        
                        # 返回格式对齐 compile 模式
                        if log_message:
                            return {
                                "success": True,
                                "message": "Runtime logs retrieved successfully",
                                "data": {
                                    "canvas_id": canvas_id,
                                    "log_mode": "runtime",  # 标识这是 runtime 模式
                                    "logMessage": log_message
                                }
                            }
                        else:
                            return {
                                "success": True,
                                "message": "No runtime logs found",
                                "data": {
                                    "canvas_id": canvas_id,
                                    "log_mode": "runtime",  # 标识这是 runtime 模式
                                    "logMessage": ""
                                }
                            }
                            
                    except aiohttp.ContentTypeError:
                        # 返回的不是 JSON
                        text = await response.text()
                        return {
                            "success": False,
                            "message": f"Invalid response format from runtime log API: {text[:200]}...",
                            "data": {
                                "log_mode": "runtime",  # 标识这是 runtime 模式
                                "error_type": "invalid_response_format",
                                "content_type": response.headers.get('content-type'),
                                "canvas_id": canvas_id,
                                "response_preview": text[:200]
                            }
                        }
                        
        except aiohttp.ClientConnectorError as e:
            return {
                "success": False,
                "message": f"Failed to connect to runtime log API at {url}. Please ensure the service is running.",
                "data": {
                    "log_mode": "runtime",  # 标识这是 runtime 模式
                    "error_type": "service_unavailable",
                    "url": url,
                    "canvas_id": canvas_id,
                    "error": str(e)
                }
            }
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # aiohttp 超时会抛出 asyncio.TimeoutError
            if isinstance(e, asyncio.TimeoutError):
                return {
                    "success": False,
                    "message": "Timeout waiting for runtime log API response (exceeded 5 minutes)",
                    "data": {
                        "log_mode": "runtime",  # 标识这是 runtime 模式
                        "error_type": "timeout",
                        "canvas_id": canvas_id,
                        "timeout_seconds": 300
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to call runtime log API: {str(e)}",
                    "data": {
                        "log_mode": "runtime",  # 标识这是 runtime 模式
                        "error_type": "api_connection_error",
                        "canvas_id": canvas_id,
                        "error": str(e)
                    }
                }
            
    except Exception as e:
        logger.error(f"Error in _read_console_runtime: {str(e)}")
        return {
            "success": False,
            "message": f"Python error: {str(e)}",
            "data": {
                "log_mode": "runtime",  # 标识这是 runtime 模式
                "error_type": "python_error",
                "canvas_id": canvas_id
            }
        }

