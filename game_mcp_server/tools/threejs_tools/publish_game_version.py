"""Publish remote project version tool for MCP."""
import logging
from typing import Dict, Any
from datetime import datetime

# 不再需要aiohttp和orjson，因为不调用后端API
from mcp.server.fastmcp import FastMCP, Context

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.env_client import env_client
from util.threejs_utils import (
    bundle_and_notify_canvas,
    upload_html_to_s3,
    notify_threejs_sync,
    read_versions_json,
    update_versions_json,
    save_version_snapshot,
    replace_canvas_files_with_snapshot,
)
from util.metrics import BUSINESS_CALLS, APP_LABEL_VALUE

logger = logging.getLogger(__name__)


def register_publish_game_version_tools(mcp: FastMCP) -> None:
    """Register the 3JS publish game version tools with the MCP server."""
    
    @mcp.tool(description="""Publish a new remote project version by packaging files, creating a version snapshot, and notifying the preview consumer.
    
    Call this ONLY when:
    - All user requirements have been implemented
    - The current project has been checked via read_console and is working properly
    - User explicitly requests preview, delivery, or versioned output
    
    DO NOT call this for intermediate edits or when execution logs still show errors.
    
    This tool automatically:
    1. Creates a new version number
    2. Saves a source code snapshot
    3. Packages the current remote project files for preview/runtime consumption
    4. Notifies the downstream preview surface to load the new version
    5. Updates version metadata
    
    The bundling process is transparent and uses caching when available. You don't need 
    to worry about the bundling details - it happens automatically before publishing.
    
    Args:
        task_name: {{task_name_prompt}},required
        message: Inform the user that the updated project has been prepared and is being delivered or previewed.
                 Should convey: 
                 1) Requirements have been implemented
                 2) Delivery/preview package is being prepared
                 3) Preparation may take about 1-2 minutes
        game_title: A short, descriptive title for the delivered project output
        
    Returns:
        - success: bool — True if version was published successfully
        - message: str — The notification message to display to user
        - data: dict — Additional information including version number, workspace id, etc.
        """)
    async def publish_game_version(
        ctx: Context,
        task_name: str,
        message: str, 
        game_title: str = None
    ) -> Dict[str, Any]:
        
        # 1. 获取上下文信息（用于日志追踪）
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        
        # 2. 版本管理：读取版本信息，计算新版本号
        try:
            versions_data = await read_versions_json(canvas_id)
            stored_max_version = versions_data.get("max_version", 0)
            
            # 从 versions 列表计算实际的 max_version（双重保险，防止数据不一致）
            versions_list = versions_data.get("versions", [])
            if versions_list:
                actual_max_version = max(v.get("version", 0) for v in versions_list)
                # 使用两者中的较大值，确保版本号不会倒退
                max_version = max(stored_max_version, actual_max_version)
                
                # 如果发现不一致，记录警告（但不影响功能）
                if stored_max_version != actual_max_version:
                    logger.warning(
                        f"{trace_id} max_version mismatch detected for canvas {canvas_id}: "
                        f"stored={stored_max_version}, actual={actual_max_version}, using {max_version}"
                    )
            else:
                max_version = stored_max_version
            
            new_version = max_version + 1
            
            logger.info(f"{trace_id} Creating new version V{new_version} for canvas {canvas_id} (previous max: {max_version})")
            
            # 3. 保存源代码快照（在打包前保存）
            # use_env=True 时文件存在于 env workspace，需从 env 拉取。
            snapshot_files_dict = None
            if config.threejs.use_env and config.threejs.env_service_url:
                snapshot_files_dict = await env_client.fetch_all_files_as_dict(ctx)
                logger.info(
                    f"{trace_id} Fetched {len(snapshot_files_dict)} files from env for snapshot"
                )

            snapshot_success, snapshot_message, snapshot = await save_version_snapshot(
                canvas_id, new_version, files_dict=snapshot_files_dict
            )
            if not snapshot_success:
                logger.error(f"{trace_id} Failed to save version snapshot: {snapshot_message}")
                return {
                    "success": False,
                    "message": f"Failed to save version snapshot: {snapshot_message}",
                    "data": {
                        "error_type": "snapshot_failed",
                        "canvas_id": canvas_id,
                        "game_title": game_title
                    }
                }
            
            # 3.5 use_env 时：将源文件同步回 S3，确保 session 过期后 re-init 能拉到最新内容
            if config.threejs.use_env and snapshot:
                sync_ok, sync_msg = await replace_canvas_files_with_snapshot(canvas_id, snapshot)
                if not sync_ok:
                    logger.warning(f"{trace_id} Source sync to S3 failed: {sync_msg}")
            
            # 4. 打包并上报（传入版本号）
            # 注意：版本号更新应该在打包成功后进行，避免打包失败导致版本号跳跃
            bundled_url = None
            try:
                if config.threejs.use_env and config.threejs.env_service_url:
                    bundle_raw = await env_client.bundle(ctx)
                    if not bundle_raw.get("success"):
                        raise Exception(f"Env bundle failed: {bundle_raw.get('message')}")
                    html_content = bundle_raw.get("html_content", "")
                    upload_ok, bundled_url = await upload_html_to_s3(
                        canvas_id, new_version, html_content
                    )
                    if not upload_ok or not bundled_url:
                        raise Exception("Failed to upload bundled HTML to S3")
                    if "|" in trace_id:
                        turn_id = trace_id.split("|")[1]
                    else:
                        turn_id = trace_id
                    notify_ok = await notify_threejs_sync(canvas_id, turn_id, [bundled_url])
                    if not notify_ok:
                        raise Exception("Failed to notify frontend after bundle")
                    logger.info(
                        f"{trace_id} publish via env: V{new_version} for canvas {canvas_id}"
                    )
                else:
                    success, bundled_url = await bundle_and_notify_canvas(ctx, fail_on_error=True, version=new_version)
                    if not success:
                        raise Exception("Bundle and notify failed")
            except Exception as e:
                logger.error(f"{trace_id} Failed to bundle and notify canvas {canvas_id}: {str(e)}")
                return {
                    "success": False,
                    "message": f"Failed to bundle game files: {str(e)}",
                    "data": {
                        "error_type": "bundle_failed",
                        "canvas_id": canvas_id,
                        "game_title": game_title
                    }
                }
            
            # 5. 打包成功，更新 versions.json（添加新版本记录并更新版本号）
            # 注意：bundle_and_notify_canvas 在 fail_on_error=True 时，如果 bundled_url 为 None 会抛出异常
            # 所以这里 bundled_url 一定不为 None，但为了防御性编程，仍然检查
            if not bundled_url:
                logger.error(f"{trace_id} Bundled URL is None after successful bundle for canvas {canvas_id}")
                return {
                    "success": False,
                    "message": "Bundled URL is missing after successful bundle",
                    "data": {
                        "error_type": "bundle_url_missing",
                        "canvas_id": canvas_id,
                        "game_title": game_title
                    }
                }
            
            # 更新版本记录
            # 提取 turn_id
            if "|" in trace_id:
                turn_id = trace_id.split("|")[1]
            else:
                turn_id = trace_id
            
            new_version_record = {
                "version": new_version,
                "bundled_url": bundled_url,
                "created_at": datetime.now().isoformat(),
                "turn_id": turn_id
            }
            
            # 重新读取 versions.json（防止并发修改）
            versions_data = await read_versions_json(canvas_id)
            versions_data["versions"].append(new_version_record)
            versions_data["current_version"] = new_version
            versions_data["max_version"] = new_version  # 打包成功后才更新 max_version
            
            update_success = await update_versions_json(canvas_id, versions_data)
            if not update_success:
                logger.error(f"{trace_id} Failed to update versions.json with new version record")
                # 这是一个严重问题：打包成功但版本记录失败，需要记录警告
                # 但已经无法回滚打包文件，只能记录错误
                return {
                    "success": False,
                    "message": "Failed to update version metadata after successful bundle",
                    "data": {
                        "error_type": "version_update_failed",
                        "canvas_id": canvas_id,
                        "game_title": game_title,
                        "version": new_version,
                        "bundled_url": bundled_url  # 即使失败也返回，方便后续修复
                    }
                }
            else:
                logger.info(f"{trace_id} Created version V{new_version} for canvas {canvas_id}")
            
        except Exception as e:
            logger.error(f"{trace_id} Failed to manage version for canvas {canvas_id}: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to manage version: {str(e)}",
                "data": {
                    "error_type": "version_management_failed",
                    "canvas_id": canvas_id,
                    "game_title": game_title
                }
            }
        
        # 7. 记录通知发送
        logger.info(f"{trace_id} Sending 3JS game notification for {game_title}")
        
        # 8. 直接返回用户通知（不需要调用后端API）
        status = "ok"
        
        # 构建返回数据（使用已更新的 new_version）
        result_data = {
            "success": True,
            "message": message,
            "data": {
                "game_title": game_title,
                "canvas_id": canvas_id,
                "notification_type": "game_generated",
                "status": "preparing",
                "version": new_version  # 返回新创建的版本号
            }
        }
        
        logger.info(f"{trace_id} 3JS game notification sent successfully for {game_title}")
        
        # 记录监控指标
        BUSINESS_CALLS.labels(
            name="publish_game_version",
            status=status,
            application=APP_LABEL_VALUE
        ).inc()
        
        return result_data
