"""ThreeJS 同步工具模块

提供 ThreeJS 画布变更通知和文件 URL 获取功能。
"""
import json
import logging
import asyncio
import os
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import aiohttp

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from tools.threejs_tools.storage.s3_helper import get_s3_storage, get_aioboto3_session
from tools.threejs_tools.storage.s3_storage import S3Storage

logger = logging.getLogger(__name__)


async def get_canvas_threejs_urls(canvas_id: str) -> List[str]:
    """
    获取当前 canvas 下的所有 3JS 文件 URLs
    
    Args:
        canvas_id: 画布 ID
        
    Returns:
        List[str]: S3 URI 列表
    """
    try:
        # 获取 S3 storage 实例
        s3_storage = await get_s3_storage(canvas_id)
        
        # 列出所有文件
        success, message, files_data = await s3_storage.list_files()
        
        if not success or not files_data:
            logger.warning(f"No files found in canvas {canvas_id}: {message}")
            return []
        
        # 提取文件名
        file_names = [file_info["file_name"] for file_info in files_data]
        
        # 拼接 S3 URIs
        s3_uris = []
        for file_name in file_names:
            s3_uri = f"s3://{s3_storage.bucket_name}/{s3_storage.base_prefix}{file_name}"
            s3_uris.append(s3_uri)
        
        logger.info(f"Found {len(file_names)} files in canvas {canvas_id}: {file_names}")
        return s3_uris
        
    except Exception as e:
        logger.error(f"Error getting canvas files for {canvas_id}: {str(e)}")
        return []


async def notify_threejs_sync(canvas_id: str, turn_id: str, threejs_urls: List[str]) -> bool:
    """
    调用 ThreeJS 同步接口通知画布变更
    
    Args:
        canvas_id: 画布 ID
        turn_id: 轮次 ID
        threejs_urls: 3JS 文件 URL 列表
        
    Returns:
        bool: 是否成功
    """
    try:
        url = f"{config.app_base_url}/app/openapi/canvas/threejs-sync"
        headers = {
            "Content-Type": "application/json",
            "token": "seele_koko_pwd",
            "x-canvas-id": canvas_id,
        }
        
        payload = {
            "canvasId": canvas_id,
            "turnId": turn_id,
            "threeJSUrls": threejs_urls
        }
        
        logger.info(f"Notifying ThreeJS sync for canvas {canvas_id} with {len(threejs_urls)} files")
        
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"ThreeJS sync notification successful for canvas {canvas_id}")
                    return True
                else:
                    logger.warning(f"ThreeJS sync notification failed: status {response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"Error notifying ThreeJS sync for canvas {canvas_id}: {str(e)}")
        return False


async def notify_canvas_change(ctx) -> bool:
    """
    通用画布变更通知函数
    
    Args:
        ctx: MCP Context 对象
        
    Returns:
        bool: 是否成功
    """
    try:
        # 获取上下文信息
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        
        # 从 trace_id 中提取 turn_id
        if "|" in trace_id:
            turn_id = trace_id.split("|")[1]
        else:
            turn_id = trace_id  # 如果没有分隔符，使用整个 trace_id
        
        # 获取当前画布的所有文件 URLs
        threejs_urls = await get_canvas_threejs_urls(canvas_id)
        
        # 调用同步接口
        return await notify_threejs_sync(canvas_id, turn_id, threejs_urls)
        
    except Exception as e:
        logger.error(f"Error in notify_canvas_change: {str(e)}")
        return False


async def bundle_and_notify_canvas(ctx, fail_on_error: bool = False, version: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    打包并上报画布变更（打包后的 index.html）
    
    该函数会：
    1. 调用 html-bundler 打包画布下的所有文件
    2. 获取打包后的 bundled_url
    3. 上报给前端（notify_threejs_sync）
    
    Args:
        ctx: MCP Context 对象
        fail_on_error: 如果为 True，失败时抛出异常；如果为 False，失败只记录 warning
        version: 版本号（必需），用于构建版本路径（versions/V{version}/index.html）
    
    Returns:
        Tuple[bool, Optional[str]]: (是否成功, bundled_url)
    """
    
    try:
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        
        # 1. 打包
        logger.info(f"{trace_id} Bundling files for canvas {canvas_id}, version={version}")
        bundle_result = await bundle_canvas_files(canvas_id, version=version)
        
        if not bundle_result.get("success"):
            error_msg = f"Failed to bundle files: {bundle_result.get('message', 'Unknown error')}"
            if fail_on_error:
                raise Exception(error_msg)
            logger.warning(f"{trace_id} {error_msg}, skip notification")
            return False, None
        
        logger.info(f"{trace_id} Successfully bundled files for canvas {canvas_id}")
        
        # 2. 获取 bundled_url
        bundled_url = bundle_result.get("data", {}).get("bundled_url")
        if not bundled_url:
            error_msg = "Bundled URL not found in bundle result"
            if fail_on_error:
                raise Exception(error_msg)
            logger.warning(f"{trace_id} {error_msg}, skip notification")
            return False, None
        
        # 3. 提取 turn_id 并上报
        if "|" in trace_id:
            turn_id = trace_id.split("|")[1]
        else:
            turn_id = trace_id
        
        success = await notify_threejs_sync(canvas_id, turn_id, [bundled_url])
        
        if success:
            logger.info(f"{trace_id} Notified canvas change with bundled file for {canvas_id}: {bundled_url}")
        else:
            if fail_on_error:
                raise Exception("Failed to notify canvas change")
            logger.warning(f"{trace_id} Failed to notify canvas change for {canvas_id}")
        
        return success, bundled_url
        
    except Exception as e:
        if fail_on_error:
            raise
        logger.warning(f"Error in bundle_and_notify_canvas: {e}")
        return False, None


async def get_bundle_storage(canvas_id: str) -> S3Storage:
    """
    获取用于打包目录的 S3Storage 实例
    
    Returns:
        S3Storage: 指向打包目录的 S3Storage 实例
        base_prefix = "threejs/tmp/pack/{canvas_id}/"
    """
    session = get_aioboto3_session()
    
    # 创建自定义前缀的 S3Storage
    bundle_storage = S3Storage(
        canvas_id=canvas_id,
        session=session,
        custom_base_prefix="threejs/tmp/pack"
    )
    # base_prefix = "threejs/tmp/pack/{canvas_id}/"
    
    return bundle_storage


async def read_versions_json(canvas_id: str) -> Dict[str, Any]:
    """
    读取 versions.json
    
    Returns:
        Dict[str, Any]: 版本元数据，如果文件不存在返回初始结构
    """
    try:
        bundle_storage = await get_bundle_storage(canvas_id)
        # 使用重试机制读取 versions.json（最多 3 次尝试）
        success, message, content = await bundle_storage.download_file("versions.json", max_retries=3)
        
        if not success:
            # 文件不存在，返回初始结构
            logger.info(f"versions.json not found for canvas {canvas_id}, returning initial structure")
            return {
                "current_version": 0,
                "max_version": 0,
                "versions": []
            }
        
        try:
            versions_data = json.loads(content)
            logger.info(f"Read versions.json for canvas {canvas_id}: current_version={versions_data.get('current_version')}, max_version={versions_data.get('max_version')}")
            return versions_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse versions.json for canvas {canvas_id}: {e}")
            # 返回初始结构
            return {
                "current_version": 0,
                "max_version": 0,
                "versions": []
            }
    except Exception as e:
        logger.error(f"Error reading versions.json for canvas {canvas_id}: {str(e)}")
        return {
            "current_version": 0,
            "max_version": 0,
            "versions": []
        }


async def update_versions_json(canvas_id: str, versions_data: Dict[str, Any]) -> bool:
    """
    更新 versions.json
    
    Args:
        canvas_id: 画布 ID
        versions_data: 版本元数据字典
        
    Returns:
        bool: 是否成功
    """
    try:
        bundle_storage = await get_bundle_storage(canvas_id)
        json_content = json.dumps(versions_data, indent=2, ensure_ascii=False)
        
        # 使用重试机制更新 versions.json（最多 3 次尝试）
        success, message, _ = await bundle_storage.upload_file(
            "versions.json", 
            content=json_content,
            metadata={"updated_by": "version_manager"},
            max_retries=3
        )
        
        if not success:
            logger.error(f"Failed to update versions.json for canvas {canvas_id}: {message}")
        else:
            logger.info(f"Updated versions.json for canvas {canvas_id}: current_version={versions_data.get('current_version')}, max_version={versions_data.get('max_version')}")
        
        return success
    except Exception as e:
        logger.error(f"Error updating versions.json for canvas {canvas_id}: {str(e)}")
        return False


async def get_max_version(canvas_id: str) -> int:
    """
    获取最大版本号
    
    Returns:
        int: 最大版本号，如果不存在返回 0
    """
    versions_data = await read_versions_json(canvas_id)
    max_version = versions_data.get("max_version", 0)
    logger.info(f"Max version for canvas {canvas_id}: {max_version}")
    return max_version


async def save_version_snapshot(
    canvas_id: str,
    version: int,
    files_dict: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[Dict[str, str]]]:
    """
    保存版本源代码快照到 V{version}.json

    Args:
        canvas_id:  画布 ID
        version:    版本号
        files_dict: 可选的预取文件字典 {filename: content}。
                    当 use_env=True 时由调用方从 env workspace 读取后传入，
                    避免本函数直接读 S3（env 模式下 S3 没有文件）。
                    为 None 时回退到原有的 S3 读取逻辑。

    Returns:
        Tuple[bool, str, Optional[Dict[str, str]]]: (是否成功, 消息, 快照字典)
    """
    try:
        if files_dict is not None:
            # 调用方已提供文件内容（use_env 场景），直接使用
            snapshot = files_dict
            if not snapshot:
                return False, "No files found in canvas", None
        else:
            # 1. 获取当前源画布所有文件（原有 S3 逻辑）
            s3_storage = await get_s3_storage(canvas_id)
            success, message, files_data = await s3_storage.list_files()

            if not success:
                return False, f"Failed to list files: {message}", None

            if not files_data:
                return False, "No files found in canvas", None

            # 2. 下载所有文件内容
            snapshot = {}
            for file_info in files_data:
                file_name = file_info["file_name"]
                download_success, download_message, content = await s3_storage.download_file(file_name)

                if not download_success:
                    logger.warning(f"Failed to download file {file_name} for snapshot: {download_message}")
                    continue

                snapshot[file_name] = content

            if not snapshot:
                return False, "No files could be downloaded for snapshot", None
        
        # 3. 保存快照到 snapshots/V{version}.json（避免与打包目录冲突）
        bundle_storage = await get_bundle_storage(canvas_id)
        snapshot_json = json.dumps(snapshot, indent=2, ensure_ascii=False)
        snapshot_file_name = f"snapshots/V{version}.json"
        
        # 使用重试机制保存快照（最多 3 次尝试）
        upload_success, upload_message, _ = await bundle_storage.upload_file(
            snapshot_file_name,
            content=snapshot_json,
            metadata={"version": str(version), "created_by": "version_manager"},
            max_retries=3
        )
        
        if not upload_success:
            return False, f"Failed to save snapshot: {upload_message}", None
        
        logger.info(f"Saved version snapshot V{version}.json for canvas {canvas_id}: {len(snapshot)} files")
        return True, f"Snapshot saved successfully", snapshot
        
    except Exception as e:
        logger.error(f"Error saving version snapshot for canvas {canvas_id}, version {version}: {str(e)}")
        return False, f"Error: {str(e)}", None


async def load_version_snapshot(canvas_id: str, version: int) -> Tuple[bool, str, Optional[Dict[str, str]]]:
    """
    加载版本源代码快照从 V{version}.json
    
    Args:
        canvas_id: 画布 ID
        version: 版本号
        
    Returns:
        Tuple[bool, str, Optional[Dict[str, str]]]: (是否成功, 消息, 快照字典)
    """
    try:
        bundle_storage = await get_bundle_storage(canvas_id)
        snapshot_file_name = f"snapshots/V{version}.json"
        
        success, message, content = await bundle_storage.download_file(snapshot_file_name)
        
        if not success:
            return False, f"Failed to load snapshot: {message}", None
        
        try:
            snapshot = json.loads(content)
            logger.info(f"Loaded version snapshot V{version}.json for canvas {canvas_id}: {len(snapshot)} files")
            return True, "Snapshot loaded successfully", snapshot
        except json.JSONDecodeError as e:
            return False, f"Failed to parse snapshot JSON: {str(e)}", None
            
    except Exception as e:
        logger.error(f"Error loading version snapshot for canvas {canvas_id}, version {version}: {str(e)}")
        return False, f"Error: {str(e)}", None


async def replace_canvas_files_with_snapshot(
    canvas_id: str, 
    snapshot: Dict[str, str],
    current_version: Optional[int] = None
) -> Tuple[bool, str]:
    """
    用快照替换源画布的所有文件
    
    流程：
    1. 先写入快照中的所有文件
    2. 删除当前源画布中不在快照中的文件
    
    如果替换失败且提供了 current_version，会用当前版本的快照自动回滚。
    回滚时不会再次回滚（避免递归）。
    
    Args:
        canvas_id: 画布 ID
        snapshot: 快照字典 {文件名: 代码内容}
        current_version: 当前版本号（可选），用于失败时回滚到当前版本
        
    Returns:
        Tuple[bool, str]: (是否成功, 消息)
    """
    try:
        s3_storage = await get_s3_storage(canvas_id)
        uploaded_files = []
        
        # 1. 先写入快照中的所有文件
        snapshot_file_names = set(snapshot.keys())
        for file_name, file_content in snapshot.items():
            success, message, _ = await s3_storage.upload_file(file_name, content=file_content)
            if not success:
                logger.error(f"Failed to upload file {file_name}: {message}")
                
                # 如果提供了当前版本，尝试用当前版本的快照回滚
                rollback_attempted = False
                rollback_succeeded = False
                
                if current_version is not None:
                    logger.info(f"Attempting to rollback to version {current_version} snapshot...")
                    rollback_attempted = True
                    
                    # 检查当前版本快照是否存在
                    bundle_storage = await get_bundle_storage(canvas_id)
                    snapshot_exists, _, _ = await bundle_storage.file_exists(f"snapshots/V{current_version}.json")
                    
                    if snapshot_exists:
                        rollback_success, rollback_msg, current_snapshot = await load_version_snapshot(
                            canvas_id, current_version
                        )
                        if rollback_success:
                            # 回滚：调用自己，但不传入 current_version（避免递归）
                            logger.info(f"Rolling back to version {current_version} snapshot...")
                            rollback_result, rollback_result_msg = await replace_canvas_files_with_snapshot(
                                canvas_id,
                                current_snapshot,
                                current_version=None  # 关键：不传入，避免递归
                            )
                            if rollback_result:
                                rollback_succeeded = True
                                return False, f"Failed to upload {file_name}: {message}. Rolled back to V{current_version}."
                            else:
                                logger.error(f"Rollback failed: {rollback_result_msg}")
                                # 回滚失败，不再清理，直接返回失败
                                return False, f"Failed to upload {file_name}: {message}. Rollback to V{current_version} also failed: {rollback_result_msg}. Canvas is in inconsistent state. Manual intervention may be required."
                        else:
                            logger.error(f"Failed to load current version snapshot for rollback: {rollback_msg}")
                            return False, f"Failed to upload {file_name}: {message}. Cannot load V{current_version} snapshot for rollback: {rollback_msg}. Canvas is in inconsistent state."
                    else:
                        logger.warning(f"Current version snapshot V{current_version}.json not found, cannot rollback")
                        return False, f"Failed to upload {file_name}: {message}. V{current_version} snapshot not found, cannot rollback. Canvas is in inconsistent state."
                
                # 只有在没有 current_version 的情况下才清理已写入的文件
                # 这样可以恢复到操作前的状态
                if current_version is None:
                    logger.warning(f"No current_version provided, cleaning up uploaded files...")
                    for uploaded_file in uploaded_files:
                        try:
                            await s3_storage.delete_file(uploaded_file)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup uploaded file {uploaded_file}: {cleanup_error}")
                    
                    return False, f"Failed to upload {file_name}: {message}. Cleaned up {len(uploaded_files)} uploaded files."
            
            # 只有上传成功才添加到已上传列表
            uploaded_files.append(file_name)
        
        logger.info(f"Uploaded {len(snapshot)} files from snapshot to canvas {canvas_id}")
        
        # 2. 删除当前源画布中不在快照中的文件
        success, message, current_files = await s3_storage.list_files()
        if success and current_files:
            current_file_names = {f["file_name"] for f in current_files}
            files_to_delete = current_file_names - snapshot_file_names
            
            # 记录删除失败的文件
            failed_deletes = []
            for file_name in files_to_delete:
                delete_success, delete_message, _ = await s3_storage.delete_file(file_name)
                if not delete_success:
                    logger.error(f"Failed to delete file {file_name}: {delete_message}")
                    failed_deletes.append(file_name)
                else:
                    logger.info(f"Deleted file {file_name} (not in snapshot)")
            
            # 如果有文件删除失败，视为整体失败，尝试回滚
            if failed_deletes:
                logger.error(f"Failed to delete {len(failed_deletes)} files: {failed_deletes}")
                
                # 如果提供了当前版本，尝试回滚
                if current_version is not None:
                    logger.info(f"Attempting to rollback to version {current_version} after delete failure...")
                    
                    # 检查当前版本快照是否存在
                    bundle_storage = await get_bundle_storage(canvas_id)
                    snapshot_exists, _, _ = await bundle_storage.file_exists(f"snapshots/V{current_version}.json")
                    
                    if snapshot_exists:
                        rollback_success, rollback_msg, current_snapshot = await load_version_snapshot(
                            canvas_id, current_version
                        )
                        if rollback_success:
                            # 回滚到当前版本
                            rollback_result, rollback_result_msg = await replace_canvas_files_with_snapshot(
                                canvas_id,
                                current_snapshot,
                                current_version=None  # 避免递归回滚
                            )
                            if rollback_result:
                                logger.info(f"Rolled back to version {current_version} after delete failure")
                                return False, f"Failed to delete files: {failed_deletes}. Rolled back to V{current_version}."
                            else:
                                logger.error(f"Rollback failed: {rollback_result_msg}")
                                # 回滚失败，不再尝试清理，直接返回失败
                                # 因为我们不知道回滚失败在哪个阶段，继续清理可能让情况更糟
                                return False, f"Failed to delete files: {failed_deletes}. Rollback to V{current_version} also failed: {rollback_result_msg}. Canvas is in inconsistent state. Manual intervention may be required."
                        else:
                            logger.error(f"Failed to load current version snapshot for rollback: {rollback_msg}")
                            return False, f"Failed to delete files: {failed_deletes}. Cannot load V{current_version} snapshot for rollback: {rollback_msg}. Canvas is in inconsistent state."
                    else:
                        logger.warning(f"Current version snapshot V{current_version}.json not found, cannot rollback")
                        return False, f"Failed to delete files: {failed_deletes}. V{current_version} snapshot not found, cannot rollback. Canvas is in inconsistent state."
                
                # 只有在没有 current_version 的情况下才清理已上传的文件
                # 这样可以恢复到操作前的状态
                if current_version is None:
                    logger.warning(f"No current_version provided, cleaning up uploaded files...")
                    cleanup_failed = []
                    for file_name in snapshot_file_names:
                        try:
                            cleanup_success, cleanup_msg, _ = await s3_storage.delete_file(file_name)
                            if not cleanup_success:
                                cleanup_failed.append(file_name)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup uploaded file {file_name}: {cleanup_error}")
                            cleanup_failed.append(file_name)
                    
                    if cleanup_failed:
                        return False, f"Failed to delete files: {failed_deletes}. Cleanup partially failed: {cleanup_failed}. Canvas may be in inconsistent state."
                    else:
                        return False, f"Failed to delete files: {failed_deletes}. Cleaned up uploaded files."
        
        logger.info(f"Replaced canvas files with snapshot for canvas {canvas_id}: {len(snapshot)} files")
        return True, "Canvas files replaced successfully"
        
    except Exception as e:
        logger.error(f"Error replacing canvas files with snapshot for canvas {canvas_id}: {str(e)}")
        
        # 异常时也尝试回滚（如果提供了 current_version）
        if current_version is not None:
            try:
                logger.info(f"Exception occurred, attempting to rollback to version {current_version}...")
                bundle_storage = await get_bundle_storage(canvas_id)
                snapshot_exists, _, _ = await bundle_storage.file_exists(f"snapshots/V{current_version}.json")
                
                if snapshot_exists:
                    rollback_success, _, current_snapshot = await load_version_snapshot(canvas_id, current_version)
                    if rollback_success:
                        rollback_result, rollback_result_msg = await replace_canvas_files_with_snapshot(
                            canvas_id,
                            current_snapshot,
                            current_version=None  # 避免递归
                        )
                        if rollback_result:
                            return False, f"Exception occurred: {str(e)}. Rolled back to V{current_version}."
                        else:
                            logger.error(f"Rollback failed: {rollback_result_msg}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback after exception: {rollback_error}")
        
        return False, f"Error: {str(e)}"


async def bundle_canvas_files(canvas_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    """
    将画布下的多个文件打包成一个 index.html
    使用本地打包（通过 Node.js 脚本）
    
    Args:
        canvas_id: 画布 ID
        version: 版本号（可选），用于确定打包输出路径
        
    Returns:
        Dict[str, Any]: {
            "success": bool,
            "message": str,
            "data": Optional[Dict]  # 包含 files_count, bundled_url 等信息
        }
    """
    # 使用本地打包
    logger.info(f"Attempting local bundle for canvas {canvas_id}, version={version}")
    result = await _download_and_bundle_canvas_files(canvas_id, version)
    if result.get("success"):
        logger.info(f"Local bundle successful for canvas {canvas_id}")
    else:
        logger.error(f"Local bundle failed for canvas {canvas_id}: {result.get('message')}")
    return result


async def _download_and_bundle_canvas_files(canvas_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    """
    下载画布文件并打包：从 S3 下载文件到内存，然后调用本地 Node.js 打包
    """
    try:
        # 1. 获取文件列表
        from tools.threejs_tools.storage.s3_helper import get_s3_storage
        s3_storage = await get_s3_storage(canvas_id)
        success, message, files_data = await s3_storage.list_files()
        
        if not success or not files_data:
            return {
                "success": False,
                "message": f"No files found in canvas {canvas_id}: {message}",
                "data": {"error_type": "no_files_found", "canvas_id": canvas_id}
            }
        
        # 2. 并发下载所有文件内容到内存（限制并发数为10）
        # 同时检查文件大小和关键文件
        files_dict = {}
        total_size = 0
        size_limit = 50 * 1024 * 1024  # 50MB
        required_files = ['index.html']  # 关键文件列表
        semaphore = asyncio.Semaphore(10)
        
        async def download_file_with_semaphore(file_info):
            async with semaphore:
                file_name = file_info["file_name"]
                # 使用重试机制下载（最多 3 次尝试）
                download_success, download_message, content = await s3_storage.download_file(file_name, max_retries=3)
                if download_success and content:
                    # 计算文件大小
                    file_size = len(content.encode('utf-8'))
                    return file_name, content, file_size
                else:
                    logger.warning(f"Failed to download file {file_name}: {download_message}")
                    return None, None, 0
        
        # 并发下载
        download_tasks = [download_file_with_semaphore(file_info) for file_info in files_data]
        results = await asyncio.gather(*download_tasks, return_exceptions=True)
        
        # 收集成功下载的文件，并累计大小
        for result in results:
            # 检查是否有异常
            if isinstance(result, Exception):
                logger.error(f"Download task failed with exception: {result}")
                continue
            
            file_name, content, file_size = result
            if file_name and content:
                # 检查总大小（在下载过程中检查，避免内存占用过大）
                if total_size + file_size > size_limit:
                    logger.warning(f"Total file size ({total_size + file_size} bytes) exceeds 50MB threshold, stopping")
                    files_dict.clear()  # 释放已下载的文件内存
                    return {
                        "success": False,
                        "message": f"File size exceeds 50MB limit (current: {total_size + file_size} bytes)",
                        "data": {"error_type": "size_limit_exceeded", "total_size": total_size + file_size}
                    }
                files_dict[file_name] = content
                total_size += file_size
        
        if not files_dict:
            files_dict.clear()  # 清理（虽然已经是空的，但保持一致性）
            return {
                "success": False,
                "message": "No files could be downloaded",
                "data": {"error_type": "download_failed"}
            }
        
        # 检查关键文件是否存在
        missing_required = [req_file for req_file in required_files if req_file not in files_dict]
        if missing_required:
            logger.error(f"Required files missing: {missing_required}")
            files_dict.clear()  # 释放已下载的文件内存
            return {
                "success": False,
                "message": f"Required files could not be downloaded: {', '.join(missing_required)}",
                "data": {"error_type": "missing_required_file", "missing_files": missing_required}
            }
        
        logger.info(f"Downloaded {len(files_dict)} files for local bundling (total size: {total_size} bytes)")
        
        # 3. 调用本地打包函数
        # 根据 version 参数判断调用场景：
        # - version is None: read_console 调用，不需要上传 S3
        # - version is not None: publish 调用，需要上传 S3
        from util.html_bundler import bundle_files_dict
        enable_s3_upload = (version is not None)  # publish 需要上传 S3
        result = await bundle_files_dict(
            files_dict, 
            canvas_id, 
            version,
            enable_s3_upload=enable_s3_upload
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in local bundling: {e}", exc_info=True)
        # 清理内存（files_dict 可能还在调用栈中）
        if 'files_dict' in locals():
            files_dict.clear()
        return {
            "success": False,
            "message": f"Local bundling error: {str(e)}",
            "data": {"error_type": "local_bundle_error"}
        }


async def fetch_canvas_files_as_dict(canvas_id: str) -> Dict[str, str]:
    """拉取画布 S3 所有源文件，返回 {filename: content} 字典。

    【注】重构后 init 由 threejs-env 自行从 S3 拉取，本函数不再被 init 使用。
    保留供 use_env=False 时的本地 bundle 等场景备用。下载失败的文件会被跳过并打印警告。
    """
    s3_storage = await get_s3_storage(canvas_id)
    ok, _, file_list = await s3_storage.list_files()
    if not ok or not file_list:
        logger.warning("fetch_canvas_files_as_dict: no files found for canvas %s", canvas_id)
        return {}

    files: Dict[str, str] = {}
    for file_info in file_list:
        name = file_info.get("file_name", "")
        if not name:
            continue
        dl_ok, _, content = await s3_storage.download_file(name)
        if dl_ok and content is not None:
            files[name] = content
        else:
            logger.warning("fetch_canvas_files_as_dict: skip %s (download failed)", name)

    logger.info("fetch_canvas_files_as_dict: fetched %d files for canvas %s", len(files), canvas_id)
    return files


async def upload_html_to_s3(
    canvas_id: str,
    version: int,
    html_content: str,
) -> Tuple[bool, Optional[str]]:
    """把 threejs-env bundle 返回的 HTML 内容上传到 S3 的版本化路径。

    使用与 html_bundler 相同的 custom_base_prefix（threejs/tmp/pack），
    确保生成的 bundled_url 路径和原有打包流程一致。
    返回 (success, bundled_url)。
    """
    try:
        bundle_storage = S3Storage(
            canvas_id=canvas_id,
            session=get_aioboto3_session(),
            custom_base_prefix="threejs/tmp/pack",
        )
        file_name = f"versions/V{version}/index.html"
        ok, message, data = await bundle_storage.upload_file(
            file_name=file_name,
            content=html_content,
            metadata={
                "generated_by": "threejs-env",
                "canvas_id": canvas_id,
                "version": str(version),
            },
            max_retries=3,
        )
        if ok and data:
            bundled_url = data.get("s3_uri", "")
            logger.info(
                "upload_html_to_s3: uploaded %s for canvas %s v%d: %s",
                file_name, canvas_id, version, bundled_url,
            )
            return True, bundled_url
        logger.error("upload_html_to_s3: upload failed for canvas %s: %s", canvas_id, message)
        return False, None
    except Exception as e:
        logger.error("upload_html_to_s3 error for canvas %s: %s", canvas_id, e)
        return False, None
