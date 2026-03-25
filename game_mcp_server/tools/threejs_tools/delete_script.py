"""Delete remote project file tool for MCP."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

def register_delete_script_tool(mcp: FastMCP):
    """Register the delete_script tool with the MCP server."""
    
    @mcp.tool(description="""
        Delete a file from the remote project workspace storage.

        For Godot-oriented tasks, this is relatively low-frequency and should be used
        cautiously. Confirm target path via list_script/read_script before deleting.

        Use this tool when a generated file is incorrect, obsolete, duplicated, or
        should be removed as part of a refactor.
        
        Args:
            task_name: {{task_name_prompt}},required
            script_name: Name of the file to delete (for example "old_enemy.gd", "tmp_scene.tscn"),required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": Any
            }
        """)
    async def delete_script(
        ctx: Context,
        task_name: str,
        script_name: str
    ) -> Dict[str, Any]:

        try:
            # Get canvas_id for project isolation
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
            
            # Validate parameters
            if not script_name:
                return {
                    "success": False,
                    "message": "Script name parameter is required",
                    "data": {"error_type": "missing_parameter", "parameter": "script_name"}
                }
            
            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                result = await env_client.scripts_delete(ctx, script_name)
                logger.info(f"delete_script via env: {script_name}, success={result.get('success')}")
                return result

            # --- Original S3 flow (use_env=False) ---
            # Get S3 storage instance with canvas_id
            s3_storage = await get_s3_storage(canvas_id)

            # Delete file from S3
            success, message, data = await s3_storage.delete_file(script_name)
            
            if success:
                # Type assertion: when success is True, data should not be None
                if data is None:
                    return {
                        "success": False,
                        "message": f"File '{script_name}' deleted but data is None",
                        "data": {"error_type": "invalid_data", "script_name": script_name}
                    }
                logger.info(f"Script '{script_name}' deleted from S3")
                
                return {
                    "success": True,
                    "message": message,
                    "data": {
                        "script_name": script_name,
                        "s3_uri": data["s3_uri"],
                        "s3_key": data["s3_key"]
                    }
                }
            else:
                logger.warning(f"Failed to delete script '{script_name}': {message}")
                return {
                    "success": False,
                    "message": message,
                    "data": {"error_type": "delete_failed", "script_name": script_name}
                }
            
        except Exception as e:
            logger.error(f"Error in delete_script: {str(e)}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}

