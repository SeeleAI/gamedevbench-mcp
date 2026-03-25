"""Switch remote project version tool for MCP."""
import logging
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.env_client import env_client, build_session_id, EnvServiceUnavailableError
from util.threejs_utils import (
    read_versions_json,
    update_versions_json,
    load_version_snapshot,
    replace_canvas_files_with_snapshot,
    notify_threejs_sync
)

logger = logging.getLogger(__name__)


def register_switch_canvas_version_tool(mcp: FastMCP) -> None:
    """Register the switch canvas version tool with the MCP server."""
    
    @mcp.tool(description="""
        Switch the remote project workspace to a different saved version by moving
        forward or backward N versions.
        
        This tool will:
        1. Load the source code snapshot from the target version
        2. Replace all remote project files with the snapshot files
        3. Update the current version in versions.json
        
        Use this tool for rollback, comparison, recovery from bad edits, or restoring
        a previously published project state.
        
        Args:
            direction: Direction to switch - "backward" (go to older version) or "forward" (go to newer version)
            n: Number of versions to move (default: 1). Must be a positive integer.
            task_name: {{task_name_prompt}},required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": {
                    "version": int,  # The version switched to
                    "bundled_url": str  # The packaged preview URL for this version (for reference)
                }
            }
        """)
    async def switch_canvas_version(
        ctx: Context,
        direction: str,
        n: int = 1,
        task_name: str = ""
    ) -> Dict[str, Any]:
        
        try:
            # 1. 获取上下文信息
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
            trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
            
            # 2. 参数验证
            if direction not in ["backward", "forward"]:
                return {
                    "success": False,
                    "message": f"Invalid direction: {direction}. Must be 'backward' or 'forward'",
                    "data": {"error_type": "invalid_direction"}
                }
            
            if n < 1:
                return {
                    "success": False,
                    "message": f"Invalid n: {n}. Must be a positive integer",
                    "data": {"error_type": "invalid_n"}
                }
            
            # 3. 读取 versions.json
            versions_data = await read_versions_json(canvas_id)
            current_version = versions_data.get("current_version", 0)
            
            if current_version == 0:
                return {
                    "success": False,
                    "message": "No versions available. Please deliver a version first.",
                    "data": {"error_type": "no_versions"}
                }
            
            # 4. 计算目标版本
            if direction == "backward":
                target_version = current_version - n
            else:  # forward
                target_version = current_version + n
            
            # 5. 验证目标版本
            if target_version < 1:
                return {
                    "success": False,
                    "message": f"Cannot switch to version {target_version}. Version must be >= 1",
                    "data": {
                        "error_type": "invalid_version",
                        "current_version": current_version,
                        "target_version": target_version
                    }
                }
            
            # 检查目标版本是否存在
            version_exists = any(v.get("version") == target_version for v in versions_data.get("versions", []))
            if not version_exists:
                return {
                    "success": False,
                    "message": f"Version {target_version} does not exist. Available versions: {[v.get('version') for v in versions_data.get('versions', [])]}",
                    "data": {
                        "error_type": "version_not_found",
                        "current_version": current_version,
                        "target_version": target_version
                    }
                }
            
            logger.info(f"{trace_id} Switching from version {current_version} to version {target_version} for canvas {canvas_id}")
            
            # 6. 加载目标版本的源代码快照
            snapshot_success, snapshot_message, snapshot = await load_version_snapshot(canvas_id, target_version)
            if not snapshot_success:
                return {
                    "success": False,
                    "message": f"Failed to load version snapshot: {snapshot_message}",
                    "data": {
                        "error_type": "snapshot_load_failed",
                        "target_version": target_version
                    }
                }
            
            # 7. 用快照替换源画布文件（传入当前版本号，用于失败时回滚）
            replace_success, replace_message = await replace_canvas_files_with_snapshot(
                canvas_id, 
                snapshot,
                current_version=current_version  # 传入当前版本号，失败时自动回滚
            )
            if not replace_success:
                return {
                    "success": False,
                    "message": f"Failed to replace canvas files: {replace_message}",
                    "data": {
                        "error_type": "replace_failed",
                        "target_version": target_version
                    }
                }
            
            # 7.5 use_env 模式：重新初始化 env session，使 workspace 与切换后的版本一致
            # replace_canvas_files_with_snapshot 已更新 S3 源路径，init 会从 S3 拉取最新内容。
            if config.threejs.use_env and config.threejs.env_service_url:
                try:
                    session_id = build_session_id(canvas_id)
                    await env_client._init_session(canvas_id, session_id)
                    logger.info(
                        f"{trace_id} Re-initialized env session {session_id} "
                        f"with V{target_version} snapshot ({len(snapshot)} files)"
                    )
                except EnvServiceUnavailableError as e:
                    logger.warning(
                        f"{trace_id} Failed to re-init env session after version switch "
                        f"(S3 files are correct, but env workspace may be stale): {e}"
                    )

            # 8. 更新 versions.json 的 current_version
            # 重新读取 versions.json（确保使用最新数据）
            versions_data = await read_versions_json(canvas_id)
            versions_data["current_version"] = target_version
            update_success = await update_versions_json(canvas_id, versions_data)
            if not update_success:
                logger.error(f"{trace_id} Failed to update versions.json, attempting to rollback files...")
                # 更新失败，尝试回滚到当前版本（使用之前保存的 current_version）
                # 注意：这里使用之前读取的 current_version，不是 target_version
                rollback_success, rollback_msg, current_snapshot = await load_version_snapshot(canvas_id, current_version)
                if rollback_success:
                    rollback_result, rollback_result_msg = await replace_canvas_files_with_snapshot(
                        canvas_id,
                        current_snapshot,
                        current_version=None  # 避免递归回滚
                    )
                    if rollback_result:
                        logger.info(f"{trace_id} Rolled back to version {current_version} after update failure")
                        return {
                            "success": False,
                            "message": f"Failed to update version metadata. Rolled back to V{current_version}.",
                            "data": {
                                "error_type": "version_update_failed",
                                "target_version": target_version,
                                "rolled_back": True
                            }
                        }
                    else:
                        logger.error(f"{trace_id} Rollback failed: {rollback_result_msg}")
                
                # 回滚失败或无法回滚，返回错误（状态不一致）
                logger.warning(f"{trace_id} Failed to update versions.json and rollback, state may be inconsistent")
                return {
                    "success": False,
                    "message": "Failed to update version metadata. Files were replaced but version not updated.",
                    "data": {
                        "error_type": "version_update_failed",
                        "target_version": target_version,
                        "warning": "State may be inconsistent: files are at target version but current_version not updated"
                    }
                }
            
            # 9. 获取目标版本的打包文件 URL（重新读取确保使用最新数据）
            versions_data = await read_versions_json(canvas_id)
            target_version_info = next(
                (v for v in versions_data.get("versions", []) if v.get("version") == target_version),
                None
            )
            
            if not target_version_info or "bundled_url" not in target_version_info:
                return {
                    "success": False,
                    "message": f"Version {target_version} bundled URL not found",
                    "data": {
                        "error_type": "bundled_url_not_found",
                        "target_version": target_version
                    }
                }
            
            bundled_url = target_version_info["bundled_url"]
            
            # 10. 通知前端切换打包文件
            # 注意：前端无法直接读取 S3 中的 versions.json，需要通过 API 通知前端加载对应版本的打包文件
            if "|" in trace_id:
                turn_id = trace_id.split("|")[1]
            else:
                turn_id = trace_id
            
            notify_success = await notify_threejs_sync(canvas_id, turn_id, [bundled_url])
            if not notify_success:
                logger.warning(f"{trace_id} Failed to notify frontend, but version switch completed")
            
            logger.info(f"{trace_id} Successfully switched to version {target_version} for canvas {canvas_id}")
            
            return {
                "success": True,
                "message": f"Successfully switched to version {target_version}",
                "data": {
                    "version": target_version,
                    "bundled_url": bundled_url,
                    "previous_version": current_version
                }
            }
            
        except Exception as e:
            logger.error(f"Error in switch_canvas_version: {str(e)}")
            
            # 异常处理：如果文件已经被替换但 versions.json 未更新，尝试回滚
            # 检查逻辑：如果 versions.json 中的 current_version 还是原来的值，说明更新未成功
            # 此时文件可能已被替换，需要回滚
            try:
                # 检查 current_version 是否已定义（说明至少执行到了第76行）
                if 'current_version' in locals() and current_version > 0:
                    # 重新读取 versions.json 检查当前状态
                    versions_data = await read_versions_json(canvas_id)
                    file_current_version = versions_data.get("current_version", 0)
                    
                    # 如果 versions.json 中的 current_version 还是原来的值（说明更新未成功）
                    # 且文件可能已被替换（因为 replace_canvas_files_with_snapshot 可能已成功）
                    # 尝试回滚到原来的版本
                    if file_current_version == current_version:
                        # 文件可能已被替换，但 versions.json 未更新，尝试回滚
                        logger.info(f"{trace_id} Exception occurred, attempting to rollback to version {current_version}...")
                        rollback_success, rollback_msg, current_snapshot = await load_version_snapshot(canvas_id, current_version)
                        if rollback_success:
                            rollback_result, rollback_result_msg = await replace_canvas_files_with_snapshot(
                                canvas_id,
                                current_snapshot,
                                current_version=None  # 避免递归回滚
                            )
                            if rollback_result:
                                logger.info(f"{trace_id} Rolled back to version {current_version} after exception")
                                return {
                                    "success": False,
                                    "message": f"Error switching version: {str(e)}. Rolled back to V{current_version}.",
                                    "data": {
                                        "error_type": "unknown_error",
                                        "rolled_back": True
                                    }
                                }
                            else:
                                logger.error(f"{trace_id} Rollback failed: {rollback_result_msg}")
                        else:
                            logger.error(f"{trace_id} Failed to load snapshot for rollback: {rollback_msg}")
            except Exception as rollback_error:
                logger.error(f"{trace_id} Failed to rollback after exception: {rollback_error}")
            
            return {
                "success": False,
                "message": f"Error switching version: {str(e)}",
                "data": {"error_type": "unknown_error"}
            }

