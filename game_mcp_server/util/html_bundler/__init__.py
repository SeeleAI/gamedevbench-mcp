"""
HTML Bundler integration for game_mcp_server
本地打包功能，避免重复下载文件
"""
import os
import json
import logging
import tempfile
import shutil
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 获取 html_bundler 目录路径
HTML_BUNDLER_DIR = Path(__file__).parent
NODE_BUNDLE_WRAPPER = HTML_BUNDLER_DIR / "node_bundle_wrapper.js"


async def bundle_files_dict(
    files_dict: Dict[str, str],
    canvas_id: str,
    version: Optional[int] = None,
    enable_s3_upload: bool = True
) -> Dict[str, Any]:
    """
    本地打包函数：将文件内容字典打包成单个 index.html
    
    Args:
        files_dict: 文件内容字典 {file_name: content}
        canvas_id: 画布 ID
        version: 版本号（可选）
        enable_s3_upload: 是否上传到 S3（默认 True，publish 需要，read_console 不需要）
    
    Returns:
        {
            "success": bool,
            "message": str,
            "data": {
                "bundled_html_path": str,  # HTML 文件路径（供 runtime 使用，避免内存占用）
                "bundled_url": str,   # 打包后的 S3 URL（当 enable_s3_upload=True 时提供）
                "files_count": int
            }
        }
    """
    
    temp_dir = None
    try:
        # 1. 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix='html-bundler-')
        src_dir = os.path.join(temp_dir, 'src')
        os.makedirs(src_dir, exist_ok=True)
        
        logger.info(f"Created temp directory for bundling: {temp_dir}")
        
        # 2. 写入文件到临时目录（保持目录结构）
        # 注意：文件大小检查已在下载阶段完成，这里不再重复检查
        
        # 路径验证和标准化
        validated_files = []
        for file_name, content in files_dict.items():
            # 标准化路径（统一使用正斜杠）
            normalized_name = file_name.replace('\\', '/')
            
            # 路径安全验证
            if '..' in normalized_name or os.path.isabs(normalized_name):
                logger.error(f"Invalid file path detected: {file_name}")
                files_dict.clear()  # 释放内存
                return {
                    "success": False,
                    "message": f"Invalid file path: {file_name}",
                    "data": {"error_type": "invalid_path"}
                }
            
            # 构建完整路径
            file_path = os.path.join(src_dir, normalized_name)
            validated_files.append((file_path, content))
        
        # 异步并发写入所有文件
        async def write_file_async(file_path: str, content: str):
            """异步写入单个文件到磁盘"""
            def _write():
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            await asyncio.to_thread(_write)
        
        # 并发写入所有文件
        write_tasks = [write_file_async(path, content) for path, content in validated_files]
        results = await asyncio.gather(*write_tasks, return_exceptions=True)
        
        # 检查是否有写入失败
        failed_count = sum(1 for r in results if isinstance(r, Exception))
        if failed_count > 0:
            logger.error(f"Failed to write {failed_count} out of {len(validated_files)} files")
            # 记录失败的文件
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to write file {validated_files[i][0]}: {result}")
            files_dict.clear()  # 释放内存
            return {
                "success": False,
                "message": f"Failed to write {failed_count} files to temp directory",
                "data": {"error_type": "file_write_failed", "failed_count": failed_count}
            }
        
        logger.info(f"Wrote {len(validated_files)} files to temp directory")
        
        # 3. 立即释放内存
        files_dict.clear()
        logger.debug(f"Cleared files_dict from memory")
        
        # 4. 调用 Node.js 打包脚本
        # 注意：bucket 参数仍需传递给 Node.js（用于构建路径），但从 config 读取
        from config import config
        params = {
            "srcDir": src_dir,
            "canvas_id": canvas_id,
            "bucket": config.s3.private_bucket,
            "version": version
        }
        
        logger.info(f"Calling Node.js bundler for canvas {canvas_id}, version={version}")
        
        # 执行 Node.js 脚本（异步，流式处理输出）
        # 注意：Node.js 只负责打包，不再上传到 S3，因此不需要传递 S3 凭证
        process = await asyncio.create_subprocess_exec(
            'node', str(NODE_BUNDLE_WRAPPER), json.dumps(params),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(HTML_BUNDLER_DIR)
        )
        
        # 流式处理输出，避免内存累积
        stdout_lines = []
        stderr_lines = []
        
        async def read_stream(stream, lines_list, log_prefix):
            """异步读取并记录输出流（使用 readline 方法，更稳定）"""
            try:
                while True:
                    # 使用 readline()，更稳定地处理 EAGAIN 错误
                    try:
                        line = await stream.readline()
                    except (ValueError, OSError) as e:
                        # 流已关闭或进程异常退出
                        logger.debug(f"Stream {log_prefix} closed or error: {e}")
                        break
                    
                    if not line:  # EOF
                        break
                    
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    if decoded_line:
                        lines_list.append(decoded_line)
                        # 限制日志长度，避免大 HTML 打印到日志
                        log_content = decoded_line if len(decoded_line) <= 200 else decoded_line[:200] + "... (truncated)"
                        logger.info(f"[Node.js {log_prefix}] {log_content}")
            except Exception as e:
                logger.warning(f"Error reading {log_prefix}: {e}")
        
        # 并发读取 stdout 和 stderr（修复竞态条件）
        # 1. 先创建读取任务（在 try 块外，以便超时处理时可以访问）
        stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_lines, "stdout"))
        stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_lines, "stderr"))
        
        try:
            # 2. 等待进程结束（带超时）
            await asyncio.wait_for(process.wait(), timeout=60.0)
            
            # 3. 确保所有流数据都被读取完成
            # 先等待读取任务完成（读取剩余数据）
            # 注意：进程结束后，流会自动发送 EOF，readline() 会返回空字节
            # StreamReader 不需要手动关闭，进程结束后会自动关闭
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        except asyncio.TimeoutError:
            logger.error("Node.js script timeout, terminating process")
            # 取消读取任务
            stdout_task.cancel()
            stderr_task.cancel()
            
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("Process did not terminate, killing")
                process.kill()
                await process.wait()
            
            # 等待任务取消完成
            # 注意：StreamReader 不需要手动关闭，进程结束后会自动关闭
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            
            return {
                "success": False,
                "message": "Bundle timeout (exceeded 60 seconds)",
                "data": {"error_type": "timeout"}
            }
        finally:
            # 清理：回收 Node 子进程（esbuild）被 kill 后挂到本进程下的已退出子进程
            try:
                while True:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid <= 0:
                        break
            except (ChildProcessError, OSError, AttributeError):
                pass
        
        returncode = process.returncode
        
        # 检查返回码
        if returncode != 0:
            logger.error(f"Node.js script failed (returncode={returncode})")
            
            # 尝试从 stderr 解析 JSON 错误信息
            if stderr_lines:
                try:
                    error_response = json.loads(stderr_lines[-1])
                    if isinstance(error_response, dict) and "message" in error_response:
                        return error_response
                except (json.JSONDecodeError, IndexError):
                    pass
            
            # 尝试从 stdout 解析 JSON 错误信息（Node.js 可能将错误输出到 stdout）
            if stdout_lines:
                try:
                    error_response = json.loads(stdout_lines[-1])
                    if isinstance(error_response, dict) and "success" in error_response and not error_response.get("success"):
                        return error_response
                except (json.JSONDecodeError, IndexError):
                    pass
            
            # 组合错误信息（显示更多上下文）
            error_parts = []
            if stderr_lines:
                error_parts.append(f"stderr: {' '.join(stderr_lines[-5:])}")  # 最后5行
            if stdout_lines:
                # 检查 stdout 中是否有错误信息
                stdout_error = '\n'.join(stdout_lines[-10:])  # 最后10行
                if "error" in stdout_error.lower() or "failed" in stdout_error.lower():
                    error_parts.append(f"stdout: {stdout_error[:500]}")
            
            error_msg = ' | '.join(error_parts) if error_parts else "Unknown error"
            return {
                "success": False,
                "message": f"Bundle failed: {error_msg[:500]}",  # 增加长度限制以便显示更多信息
                "data": {"error_type": "bundle_failed", "returncode": returncode}
            }
        
        # 解析 Node.js 返回的 JSON（从 stdout 最后一行）
        json_line = stdout_lines[-1] if stdout_lines else ""
        
        try:
            response = json.loads(json_line)
            logger.info(f"Successfully parsed JSON response: success={response.get('success')}")
            
            # 检查打包是否成功
            if not response.get('success'):
                return response
            
            # 获取文件路径（不再从 JSON 中获取 HTML 内容）
            bundled_vite_path = response.get('data', {}).get('bundled_html_path')
            bundled_html_size = response.get('data', {}).get('bundled_html_size', 0)
            files_count = response.get('data', {}).get('files_count', 0)
            
            if not bundled_vite_path:
                logger.error("Bundled HTML path not found in response")
                return {
                    "success": False,
                    "message": "Bundled HTML path not found in Node.js response",
                    "data": {"error_type": "missing_html_path"}
                }
            
            # 尝试路径：优先使用 Node.js 返回的路径，如果失败则尝试标准路径
            possible_paths = [
                os.path.join(src_dir, bundled_vite_path),  # Node.js 返回的路径（应该是 dist/index.html）
                os.path.join(src_dir, 'dist', 'index.html'),  # 标准路径作为备用
            ]
            
            # 确定最终使用的 HTML 文件路径
            bundled_indexhtml_path = None
            for html_path in possible_paths:
                if os.path.exists(html_path):
                    bundled_indexhtml_path = html_path
                    break
            
            if not bundled_indexhtml_path:
                logger.error(f"Bundled HTML file not found at any of: {possible_paths}")
                return {
                    "success": False,
                    "message": f"Bundled HTML file not found: {bundled_vite_path}",
                    "data": {"error_type": "html_file_not_found", "searched_paths": possible_paths}
                }
            
            logger.debug(f"Using bundled HTML file path: {bundled_indexhtml_path}")
            
            # 根据参数决定是否上传到 S3
            bundled_url = None
            if enable_s3_upload:
                # 验证：必须有版本号才能上传（publish 场景）
                if version is None:
                    logger.error("Cannot upload to S3: version is required for S3 upload")
                    return {
                        "success": False,
                        "message": "Cannot upload to S3: version is required",
                        "data": {"error_type": "upload_requires_version"}
                    }
                
                from tools.threejs_tools.storage.s3_storage import S3Storage
                from tools.threejs_tools.storage.s3_helper import get_aioboto3_session
                
                # 创建专门用于打包目录的 S3Storage 实例
                bundle_storage = S3Storage(
                    canvas_id=canvas_id,
                    session=get_aioboto3_session(),
                    custom_base_prefix="threejs/tmp/pack"  # 使用打包专用路径
                )
                
                # 构建文件名（相对于 base_prefix: threejs/tmp/pack/{canvas_id}/）
                # 使用版本路径（不再使用 hash 路径）
                file_name = f"versions/V{version}/index.html"
                
                # 上传到 S3（自动重试 3 次）
                # 使用文件路径上传（避免内存占用）
                upload_success, upload_message, upload_data = await bundle_storage.upload_file(
                    file_name,
                    source_file_path=bundled_indexhtml_path,
                    metadata={"content_type": "bundled_html", "files_count": str(files_count)},
                    max_retries=3
                )
                
                if not upload_success:
                    logger.error(f"Failed to upload bundled HTML: {upload_message}")
                    return {
                        "success": False,
                        "message": f"Bundle succeeded but upload failed: {upload_message}",
                        "data": {"error_type": "upload_failed"}
                    }
                
                bundled_url = upload_data["s3_uri"]
                logger.info(f"Successfully uploaded bundled HTML to {bundled_url}")
            else:
                logger.debug("Skipping S3 upload (enable_s3_upload=False)")
            
            # 准备返回结果
            return_data = {
                "bundled_html_path": bundled_indexhtml_path,  # HTML 文件路径（供 runtime 使用，避免内存占用）
                "files_count": files_count
            }
            
            # 只在需要时添加这些字段
            if bundled_url is not None:
                return_data["bundled_url"] = bundled_url  # S3 URL（当 enable_s3_upload=True 时提供）
            
            return {
                "success": True,
                "message": f"Successfully bundled {files_count} files into index.html",
                "data": return_data
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Node.js response as JSON: {e}")
            logger.error(f"Stdout lines: {stdout_lines}")
            return {
                "success": False,
                "message": f"Failed to parse response: {json_line[:200]}",
                "data": {"error_type": "parse_error"}
            }
    except Exception as e:
        error_str = str(e)
        # 检测资源错误（不应该重试）
        is_resource_error = (
            "Resource temporarily unavailable" in error_str or
            "Errno 11" in error_str or
            "BlockingIOError" in error_str or
            "Cannot fork" in error_str
        )
        
        if is_resource_error:
            logger.error(f"Error in bundle_files_dict (resource exhausted): {e}", exc_info=True)
            return {
                "success": False,
                "message": f"System resource temporarily unavailable. Please try again later: {error_str}",
                "data": {"error_type": "resource_exhausted", "retryable": True}
            }
        
        logger.error(f"Error in bundle_files_dict: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "data": {"error_type": "unknown_error"}
        }
    finally:
        # 不立即删除临时目录，由定时清理任务处理（util.schedule.jobs.html_bundler_cleanup）
        # 这样可以避免 read_console 使用文件路径时文件已被删除的问题
        # 定时任务会清理超过 24 小时的临时目录
        if temp_dir and os.path.exists(temp_dir):
            logger.debug(f"Temporary directory will be cleaned up by scheduled task: {temp_dir}")

