"""
ThreeJS Runtime - 内置版本

使用 Playwright 执行 ThreeJS 代码并收集控制台日志
采用按需启动策略，用完即销毁，节省资源
支持从文件路径加载 HTML，避免大文件占用内存
"""
import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ========== 自定义异常 ==========

class ThreeJSRuntimeError(Exception):
    """ThreeJS Runtime 执行错误基类"""
    pass


class ThreeJSRuntimeTimeoutError(ThreeJSRuntimeError):
    """ThreeJS Runtime 执行超时错误"""
    def __init__(self, timeout_seconds: int):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"ThreeJS execution timeout after {timeout_seconds} seconds")


class ThreeJSRuntimeExecutionError(ThreeJSRuntimeError):
    """ThreeJS Runtime 执行错误"""
    pass

# ========== 并发控制配置 ==========

# 最大并发执行数（可通过环境变量配置）
MAX_CONCURRENT_EXECUTIONS = int(os.environ.get("THREEJS_MAX_CONCURRENT", "2"))

# 浏览器关闭超时（秒），避免 close() 挂起导致清理不完整
BROWSER_CLOSE_TIMEOUT = int(os.environ.get("THREEJS_BROWSER_CLOSE_TIMEOUT", "10"))

# 全局信号量：限制同时执行的 Chromium 实例数量
_execution_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)


async def _close_browser_safe(browser, timeout: int = BROWSER_CLOSE_TIMEOUT) -> None:
    """
    带超时的浏览器关闭，保证「关闭」有上限时间；超时后由收尾的清理逻辑回收已退出的子进程。
    """
    try:
        await asyncio.wait_for(browser.close(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "Browser close timed out after %s seconds, cleanup will reap when process exits",
            timeout,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug("Browser close error (ignored): %s", e)

# 统计信息（用于监控和调试）
_stats = {
    "total_requests": 0,
    "successful_executions": 0,
    "failed_executions": 0,
    "current_concurrent": 0,
    "max_concurrent_reached": 0,
    "total_queued": 0,
}


async def execute_threejs_code(
    html_file_path: str,
    console_type: str = "error",
    lines: int = 10,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    执行 ThreeJS 代码并收集控制台日志
    
    采用按需启动策略：
    - 每次请求时启动新的 Chromium 实例
    - 执行完成后立即关闭并清理资源
    - 使用信号量控制并发数量
    
    加载方式：
    - 使用文件路径（html_file_path）：从文件加载，避免大文件占用内存
    
    Args:
        html_file_path: HTML 文件路径（必需，避免内存占用）
        console_type: 日志类型 ("error" 或 "info")
        lines: 返回最后 N 条日志（必须 > 0）
        timeout: 执行超时时间（秒），默认 30 秒（必须 > 0）
        
    Returns:
        {
            "logs": str,              # 日志内容（可能为空字符串）
            "total_logs": int,        # 总日志数
            "filtered_logs": int,      # 过滤后的日志数
            "console_type": str        # 日志类型
        }
        
    Raises:
        ValueError: 参数验证失败
        ThreeJSRuntimeTimeoutError: 执行超时
        ThreeJSRuntimeExecutionError: 执行失败
    """
    # 参数验证：html_file_path 是必需的（html_code 已废弃）
    if not html_file_path:
        raise ValueError("html_file_path is required (html_code parameter is deprecated)")
    if not os.path.exists(html_file_path):
        raise ValueError(f"html_file_path does not exist: {html_file_path}")
    if console_type not in ["error", "info"]:
        raise ValueError(f"console_type must be 'error' or 'info', got '{console_type}'")
    if lines <= 0:
        raise ValueError(f"lines must be greater than 0, got {lines}")
    if timeout <= 0:
        raise ValueError(f"timeout must be greater than 0, got {timeout}")
    
    _stats["total_requests"] += 1
    
    # 检查是否需要排队
    if _execution_semaphore.locked():
        _stats["total_queued"] += 1
        logger.info(
            f"Request queued, current concurrent: {_stats['current_concurrent']}/{MAX_CONCURRENT_EXECUTIONS}"
        )
    
    # 获取信号量（如果已满，会在这里等待）
    async with _execution_semaphore:
        try:
            # 更新并发统计
            _stats["current_concurrent"] += 1
            if _stats["current_concurrent"] > _stats["max_concurrent_reached"]:
                _stats["max_concurrent_reached"] = _stats["current_concurrent"]
            
            logger.info(
                f"Executing ThreeJS code "
                f"(concurrent: {_stats['current_concurrent']}/{MAX_CONCURRENT_EXECUTIONS})"
            )
            
            # 实际执行（带超时）
            try:
                result = await asyncio.wait_for(
                    _execute_code_internal(html_file_path=html_file_path, console_type=console_type, lines=lines),
                    timeout=timeout
                )
                _stats["successful_executions"] += 1
                return result
            except asyncio.TimeoutError:
                # 超时时，任务会被取消，但需要等待清理完成
                _stats["failed_executions"] += 1
                logger.error(f"ThreeJS execution timeout after {timeout} seconds")
                # 给一点时间让清理完成
                await asyncio.sleep(0.1)
                raise ThreeJSRuntimeTimeoutError(timeout)
            
        except asyncio.TimeoutError:
            # 双重保护
            _stats["failed_executions"] += 1
            logger.error(f"ThreeJS execution timeout after {timeout} seconds")
            raise ThreeJSRuntimeTimeoutError(timeout)
        except (ThreeJSRuntimeError, ValueError):
            # 重新抛出已知异常
            raise
        except Exception as e:
            _stats["failed_executions"] += 1
            logger.error(f"ThreeJS execution error: {e}", exc_info=True)
            raise ThreeJSRuntimeExecutionError(f"Execution failed: {str(e)}") from e
        finally:
            # 更新并发统计
            _stats["current_concurrent"] -= 1


async def _execute_code_internal(
    html_file_path: str,
    console_type: str = "error",
    lines: int = 10
) -> Dict[str, Any]:
    """
    内部执行函数（实际启动 Chromium）
    
    流程：
    1. 启动 Playwright
    2. 启动 Chromium（headless 模式）
    3. 从文件加载 HTML（避免内存占用）
    4. 收集控制台日志
    5. 关闭浏览器
    6. 返回日志
    """
    try:
        # 动态导入 Playwright（避免启动时加载）
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Please run: pip install playwright")
        raise ImportError("Playwright is required but not installed")
    
    try:
        # 启动 Playwright
        async with async_playwright() as p:
            # 启动 Chromium 浏览器（先置 None，launch 抛错时 finally 里可安全判断）
            browser = None
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-web-security",           # 关闭跨域限制
                    "--enable-3d-apis",                 # 启用 3D API
                    "--enable-webgl",                   # 启用 WebGL
                    "--enable-webgl2",                   # 启用 WebGL2
                    "--ignore-gpu-blocklist",           # 忽略 GPU 黑名单
                    "--disable-gpu-driver-bug-workarounds",
                    "--enable-features=WebGL",
                    "--disable-features=UseSkiaRenderer",
                    "--enable-unsafe-swiftshader",      # 启用软件渲染（无 GPU 环境）
                ]
            )
            
            page = None  # 初始化为 None，防止未定义错误
            logs: List[Dict[str, str]] = []  # 在外部定义，确保所有路径都能访问
            on_console = None  # 初始化为 None，防止未定义错误
            on_page_error = None  # 初始化为 None，防止未定义错误
            browser_closed = False  # 标记浏览器是否已关闭，避免重复关闭
            
            try:
                # 创建新页面
                page = await browser.new_page()
                
                # 收集日志（已在外部定义）
                
                # 监听控制台消息
                async def on_console(msg):
                    try:
                        log_level = 'info' if msg.type != 'error' else 'error'
                        logs.append({
                            "level": log_level,
                            "message": msg.text
                        })
                        logger.debug(f"[Console][{msg.type.upper()}] {msg.text}")
                    except Exception as e:
                        # 忽略浏览器关闭时的异常
                        logger.debug(f"Console listener error (ignored): {e}")
                
                # 监听页面错误
                async def on_page_error(error):
                    try:
                        logs.append({
                            "level": "error",
                            "message": str(error)
                        })
                        logger.debug(f"[PageError] {error}")
                    except Exception as e:
                        # 忽略浏览器关闭时的异常
                        logger.debug(f"Page error listener error (ignored): {e}")
                
                # 注册事件监听器
                page.on("console", on_console)
                page.on("pageerror", on_page_error)
                
                try:
                    # 使用文件路径加载（避免大文件占用内存）
                    # 转换为 file:// URL（Windows 需要特殊处理路径）
                    if os.name == 'nt':  # Windows
                        file_url = Path(html_file_path).as_uri()
                    else:
                        # Unix/Linux/Mac
                        file_url = f"file://{html_file_path}"
                    
                    logger.debug(f"Loading HTML from file: {html_file_path}")
                    await page.goto(file_url, wait_until="domcontentloaded")
                    
                    # 等待 3 秒让 JavaScript 执行
                    await page.wait_for_timeout(3000)
                except (asyncio.CancelledError, Exception) as e:
                    # 超时取消或其他异常时，先移除事件监听器
                    try:
                        page.remove_listener("console", on_console)
                        page.remove_listener("pageerror", on_page_error)
                    except Exception:
                        pass
                    if isinstance(e, asyncio.CancelledError):
                        raise
                    # 其他异常（如 goto 失败）继续向外传播，由上层转为 ThreeJSRuntimeExecutionError
                    raise
                
                # 提取指定类型的日志
                filtered_logs = [
                    log["message"] for log in logs
                    if log["level"] == console_type.lower()
                ]
                
                # 取最后 N 条日志
                log_messages = filtered_logs[-lines:] if filtered_logs else []
                log_text = "\n".join(log_messages)
                
                logger.info(
                    f"Execution completed: total_logs={len(logs)}, "
                    f"filtered_logs={len(filtered_logs)}, "
                    f"console_type={console_type}"
                )
                
                # 准备返回结果
                result = {
                    "logs": log_text,
                    "total_logs": len(logs),
                    "filtered_logs": len(filtered_logs),
                    "console_type": console_type
                }
                
                # 清理：移除事件监听器（防止内存泄漏）
                try:
                    page.remove_listener("console", on_console)
                    page.remove_listener("pageerror", on_page_error)
                except Exception as e:
                    logger.debug(f"Error removing listeners (ignored): {e}")
                
                # 清理：关闭页面（释放页面资源）
                try:
                    await page.close()
                except Exception as e:
                    logger.debug(f"Error closing page (ignored): {e}")
                
                # 清理：清空 logs 列表（释放内存）
                logs.clear()
                
                return result
                
            except asyncio.CancelledError:
                # 超时取消时，确保资源被清理
                try:
                    # 清理 logs 列表（防止内存泄漏）
                    if logs:
                        logs.clear()
                    
                    # 尝试移除事件监听器（如果 page 和监听器都已创建）
                    if page and on_console and on_page_error:
                        try:
                            page.remove_listener("console", on_console)
                            page.remove_listener("pageerror", on_page_error)
                        except Exception:
                            pass
                    
                    # 关闭页面（如果已创建）
                    if page:
                        try:
                            await asyncio.wait_for(page.close(), timeout=5)
                        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                            pass
                    
                    # 关闭浏览器（带超时，保证清理有上限）
                    await _close_browser_safe(browser)
                    browser_closed = True
                except BaseException:
                    pass
                raise
            finally:
                # 关闭：确保浏览器被关闭（带超时）
                if browser is not None and not browser_closed:
                    try:
                        await _close_browser_safe(browser)
                        logger.debug("Browser closed (or close attempted)")
                    except (Exception, asyncio.CancelledError):
                        pass
                # 清理：回收已退出的子进程（无论关闭是否抛错都执行）
                try:
                    while True:
                        pid, _ = os.waitpid(-1, os.WNOHANG)
                        if pid <= 0:
                            break
                except (ChildProcessError, OSError, AttributeError):
                    pass
                
    except Exception as e:
        logger.error(f"Error in _execute_code_internal: {e}", exc_info=True)
        raise


def get_runtime_stats() -> Dict[str, Any]:
    """
    获取 Runtime 统计信息（用于监控）
    
    Returns:
        {
            "max_concurrent": int,
            "current_concurrent": int,
            "total_requests": int,
            "successful_executions": int,
            "failed_executions": int,
            "max_concurrent_reached": int,
            "total_queued": int,
            "semaphore_locked": bool
        }
    """
    return {
        "max_concurrent": MAX_CONCURRENT_EXECUTIONS,
        "current_concurrent": _stats["current_concurrent"],
        "total_requests": _stats["total_requests"],
        "successful_executions": _stats["successful_executions"],
        "failed_executions": _stats["failed_executions"],
        "max_concurrent_reached": _stats["max_concurrent_reached"],
        "total_queued": _stats["total_queued"],
        "semaphore_locked": _execution_semaphore.locked()
    }


# ========== 可玩性验证脚本（独立功能，不接入 execute_threejs_code 流程）==========

async def _execute_playability_test_internal(
    html_file_path: str,
    test_script: str,
    page_load_wait_ms: int = 10000,
    script_timeout_ms: int = 25000,
) -> Optional[Dict[str, Any]]:
    """
    内部：启动无头浏览器，加载 HTML，在页面内执行测试脚本，返回 window.__TEST_RESULT__。
    仅供 execute_playability_test 调用，不与其他流程耦合。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Please run: pip install playwright")
        raise ImportError("Playwright is required but not installed")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--enable-3d-apis",
                "--enable-webgl",
                "--enable-webgl2",
                "--ignore-gpu-blocklist",
                "--enable-unsafe-swiftshader",
            ],
        )
        page = await browser.new_page()
        eval_task = None  # 始终保留引用，finally 里对未完成的 task 做 await 以消费异常
        try:
            if os.name == "nt":
                file_url = Path(html_file_path).as_uri()
            else:
                file_url = f"file://{html_file_path}"
            logger.debug("Playability test: loading HTML from %s", html_file_path)
            # 游戏通常在 window load 里初始化（如 init()），需等 load 再跑测试脚本
            await page.goto(file_url, wait_until="load")
            await page.wait_for_timeout(page_load_wait_ms)

            # 执行脚本后轮询等待 window.__TEST_RESULT__，不依赖脚本是否返回 Promise
            wrapper_js = """async (script) => {
                const fn = new Function(script);
                fn();
                const deadline = Date.now() + """ + str(script_timeout_ms) + """;
                while (Date.now() < deadline) {
                    if (window.__TEST_RESULT__ !== undefined) return window.__TEST_RESULT__;
                    await new Promise(r => setTimeout(r, 100));
                }
                return window.__TEST_RESULT__;
            }"""
            # 用 wait 做超时且不 cancel evaluate，避免 close 后 Playwright 给 evaluate 的 Future 设 TargetClosedError 导致 "Future exception was never retrieved"
            eval_task = asyncio.create_task(page.evaluate(wrapper_js, test_script))
            script_timeout_s = script_timeout_ms / 1000.0
            done, pending = await asyncio.wait([eval_task], timeout=script_timeout_s)
            if pending:
                result = None
            else:
                result = eval_task.result()
            return result
        finally:
            # 未完成的 eval_task：用 callback 消费异常，避免取消时 finally 里 await 再抛 CancelledError 导致永远走不到 await eval_task
            if eval_task is not None and not eval_task.done():
                def _consume_eval(t):
                    try:
                        t.exception()
                    except (asyncio.CancelledError, Exception):
                        pass
                eval_task.add_done_callback(_consume_eval)
            try:
                await page.close()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("Playability test cleanup (page.close): %s", e)
            try:
                await _close_browser_safe(browser)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("Playability test cleanup (browser close): %s", e)


async def execute_playability_test(
    html_file_path: str,
    test_script: str,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    可玩性验证：在无头浏览器中加载游戏 HTML，执行验证脚本，返回结构化结果。

    与 execute_threejs_code 独立，不共用执行流程，便于单独调整。

    Args:
        html_file_path: 游戏 HTML 文件路径（本地 file://）
        test_script: 在游戏页面内执行的 JS 字符串，结束时需设置 window.__TEST_RESULT__
        timeout: 总超时（秒），含加载与脚本执行，默认 90

    Returns:
        {
            "run_status": "script_failed" | "invalid_result" | "valid_result",
            "message": str,
            "data": { "passed": bool?, "details": any?, "execution_error": str? }
        }
    """
    if not html_file_path or not os.path.exists(html_file_path):
        return {
            "run_status": "script_failed",
            "message": "html_file_path required and must exist",
            "data": {"passed": None, "execution_error": "Invalid html_file_path"},
        }
    if not test_script or not test_script.strip():
        return {
            "run_status": "script_failed",
            "message": "test_script required",
            "data": {"passed": None, "execution_error": "Empty test_script"},
        }
    if timeout <= 0:
        timeout = 90

    script_timeout_ms = min(25000, max(1000, (timeout - 5) * 1000))

    async def _run() -> Optional[Dict[str, Any]]:
        async with _execution_semaphore:
            return await _execute_playability_test_internal(
                html_file_path,
                test_script,
                page_load_wait_ms=10000,
                script_timeout_ms=script_timeout_ms,
            )

    try:
        result = await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        return {
            "run_status": "script_failed",
            "message": f"Playability test timeout after {timeout}s",
            "data": {"passed": None, "execution_error": f"Timeout {timeout}s"},
        }
    except Exception as e:
        logger.debug("Playability test execution error: %s", e, exc_info=True)
        return {
            "run_status": "script_failed",
            "message": str(e),
            "data": {"passed": None, "execution_error": str(e)},
        }

    if result is None:
        return {
            "run_status": "invalid_result",
            "message": "Script did not set window.__TEST_RESULT__",
            "data": {"passed": None, "details": None},
        }
    if not isinstance(result, dict) or "passed" not in result:
        return {
            "run_status": "invalid_result",
            "message": "window.__TEST_RESULT__ missing or invalid (no 'passed' field)",
            "data": {"passed": None, "details": result},
        }

    return {
        "run_status": "valid_result",
        "message": result.get("message", ""),
        "data": {
            "passed": result.get("passed"),
            "details": result.get("details"),
            "execution_error": None,
        },
    }
