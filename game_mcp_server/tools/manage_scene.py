from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry


def register_manage_scene_tools(mcp: FastMCP):
    """Register all scene management tools with the MCP server."""

    @mcp.tool(description="""Manages Unity scenes (load, save, create, get hierarchy, etc.).

        Args:
            action: Operation (enum: 'load', 'save', 'create', 'get_hierarchy', 'get_gameobject_hierarchy', 'get_active', 'get_build_settings'). get_hierarchy can get the root object and its basic information and number of children;get_gameobject_hierarchy can get the GameObject's hierarchy information based on uniqueID; get_active gets the current active scene info; get_build_settings gets scenes in build settings
            task_name: {{task_name_prompt}}
            name: Scene name (no extension) for create/load.
            path: Relative path under Assets/ folder for scene operations. 
                  - For 'create': required, defaults to "Scenes" if not provided
                  - For 'load': optional, specifies scene path under Assets/ to load
                  - For 'save': required, specifies where to save the scene under Assets/
            build_index: Build index for load/build settings actions.
            unique_id: GameObject unique ID for get_gameobject_hierarchy action.
            max_depth: Maximum depth for hierarchy queries (default: 3).

        Returns:
            Dictionary with operation results ('success', 'message', 'data').
        """)
    async def manage_scene(
        ctx: Context,
        action: str,
        task_name: str = None,
        name: str = None,
        path: str = None,
        build_index: int = None,
        unique_id: str = None,
        max_depth: int = None,
    ) -> Dict[str, Any]:
        
        try:
            params = {
                "action": action,
                "name": name,
                "path": path,
                "buildIndex": build_index,
                "uniqueID": unique_id,
                "maxDepth": max_depth
            }
            params = {k: v for k, v in params.items() if v is not None}
            
            # Use centralized retry helper
            response = await async_send_command_with_retry(ctx, "manage_scene", params)

            # Preserve structured failure data; unwrap success into a friendlier shape
            if isinstance(response, dict) and response.get("success"):
                return {"success": True, "message": response.get("message", "Scene operation successful."), "data": response.get("data")}
            return response if isinstance(response, dict) else {"success": False, "message": str(response)}

        except Exception as e:
            return {"success": False, "message": f"Python error managing scene: {str(e)}"}