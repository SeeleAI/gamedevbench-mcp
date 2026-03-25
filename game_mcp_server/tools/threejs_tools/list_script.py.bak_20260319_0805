"""List remote project files tool for MCP."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

def register_list_script_tool(mcp: FastMCP):
    """Register the list_script tool with the MCP server."""
    
    @mcp.tool(description="""
        List all files currently stored in the remote project workspace.

        For Godot-oriented tasks, this should usually be the FIRST file tool you call
        when file paths are uncertain.

        Use this tool to:
        - Inspect remote project structure before reading or editing files
        - Check which files already exist before creating new ones
        - Avoid overwriting or deleting the wrong file
        - Understand which implementation artifacts are available in MCP-managed storage

        Typical Godot file types you may see:
        - .gd scripts, .tscn/.scn scenes, .tres/.res resources, .cfg/.json config files
        
        Args:
            task_name: {{task_name_prompt}},required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": [
                    {
                        "file_name": str,          # File name (for example "main.tscn")
                        "s3_key": str,             # Full S3 key
                        "size": int,                # File size in bytes
                        "last_modified": str        # Last modification time
                    }
                ]
            }
        """)
    async def list_script(
        ctx: Context,
        task_name: str
    ) -> Dict[str, Any]:
        
        try:
            # Get canvas_id for project isolation
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id

            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                result = await env_client.scripts_list(ctx)
                logger.info(f"list_script via env: canvas {canvas_id}, success={result.get('success')}")
                return result

            # --- Original S3 flow (use_env=False) ---
            # Get S3 storage instance with canvas_id
            s3_storage = await get_s3_storage(canvas_id)
            
            # List all files from S3
            success, message, files_data = await s3_storage.list_files()
            
            if success and files_data:
                logger.info(f"Listed {len(files_data)} files from canvas {canvas_id}")
                return {
                    "success": True,
                    "message": f"Found {len(files_data)} files",
                    "data": files_data,
                    "metadata": {
                        "canvas_id": canvas_id,
                        "total_files": len(files_data),
                        "file_names": [f["file_name"] for f in files_data]
                    }
                }
            elif success and not files_data:
                logger.info(f"No files found in canvas {canvas_id}")
                return {
                    "success": True,
                    "message": "No files found in current canvas",
                    "data": [],
                    "metadata": {
                        "canvas_id": canvas_id,
                        "total_files": 0
                    }
                }
            else:
                logger.warning(f"Failed to list files from canvas {canvas_id}: {message}")
                return {
                    "success": False,
                    "message": message,
                    "data": {
                        "error_type": "list_failed",
                        "canvas_id": canvas_id
                    }
                }
            
        except Exception as e:
            logger.error(f"Error in list_script: {str(e)}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}
