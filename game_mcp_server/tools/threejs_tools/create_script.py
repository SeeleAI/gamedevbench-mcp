"""Create remote project file tool for MCP."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

def register_create_script_tool(mcp: FastMCP):
    """Register the create_script tool with the MCP server."""
    
    @mcp.tool(description="""
        Create a new project file in the remote workspace storage.

        For Godot-oriented tasks, use this only after list_script/read_script confirms
        the target file does not already exist.

        Use this tool when the task needs a new source file, scene-related text file,
        config file, or helper script and the file does not already exist.

        Args:
            task_name: {{task_name_prompt}}, required
            script_name: Name of the file to create (for example "player.gd", "level_logic.gd", "enemy_ai.gd", "ui_config.json", "hud.tscn"),required
            code: Full text content to save into the new file,required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": Any
            }
        """)
    async def create_script(
        ctx: Context,
        task_name: str,
        script_name: str,
        code: str
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
            
            if not code or not code.strip():
                return {
                    "success": False,
                    "message": "Code parameter is required and cannot be empty or whitespace only",
                    "data": {"error_type": "missing_parameter", "parameter": "code"}
                }

            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                result = await env_client.scripts_create(ctx, script_name, code)
                logger.info(f"create_script via env: {script_name}, success={result.get('success')}")
                return result

            # --- Original S3 flow (use_env=False) ---
            # Get S3 storage instance with canvas_id
            s3_storage = await get_s3_storage(canvas_id)
            
            # Check if file already exists in S3
            exists, _, _ = await s3_storage.file_exists(script_name)
            if exists:
                return {
                    "success": False,
                    "message": f"Script '{script_name}' already exists",
                    "data": {"error_type": "file_exists", "script_name": script_name}
                }
            
            # Upload file to S3
            success, message, data = await s3_storage.upload_file(
                file_name=script_name,
                content=code,
                metadata={"created_by": "create_script_tool"}
            )
            
            if success:
                logger.info(f"Script '{script_name}' created in S3")
                
                return {
                    "success": True,
                    "message": message,
                    "data": {
                        "script_name": script_name,
                        "s3_uri": data["s3_uri"],  # type: ignore
                        "s3_key": data["s3_key"],  # type: ignore
                        "code_length": data["content_length"]  # type: ignore
                    }
                }
            else:
                logger.error(f"Failed to create script '{script_name}': {message}")
                return {
                    "success": False,
                    "message": message,
                    "data": {"error_type": "upload_failed", "script_name": script_name}
                }
            
        except Exception as e:
            logger.error(f"Error in create_script: {str(e)}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}

