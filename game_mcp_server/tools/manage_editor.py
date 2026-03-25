from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry


def register_manage_editor_tools(mcp: FastMCP):
    """Register all editor management tools with the MCP server."""

    @mcp.tool(description="""Controls and queries the Unity editor's state and settings.

        Args:
            action: Operation (e.g., 'play', 'pause', 'stop', 'get_state', 'get_project_root', 'get_windows', 'get_active_tool', 'get_selection', 'set_active_tool', 'add_tag', 'remove_tag', 'get_tags', 'add_layer', 'remove_layer', 'get_layers', 'get_player_settings', 'get_graphics_settings', 'get_packages').
            task_name: {{task_name_prompt}}
            wait_for_completion: Optional. If True, waits for certain actions.
            Action-specific arguments (e.g., tool_name, tag_name, layer_name).

        Returns:
            Dictionary with operation results ('success', 'message', 'data').
        """)
    async def manage_editor(
        ctx: Context,
        action: str,
        task_name: str = None,
        wait_for_completion: bool = None,
        # --- Parameters for specific actions ---
        tool_name: str = None, 
        tag_name: str = None,
        layer_name: str = None,
    ) -> Dict[str, Any]:
        
        try:
            # Prepare parameters, removing None values
            params = {
                "action": action,
                "waitForCompletion": wait_for_completion,
                "toolName": tool_name, # Corrected parameter name to match C#
                "tagName": tag_name,   # Pass tag name
                "layerName": layer_name, # Pass layer name
            }
            params = {k: v for k, v in params.items() if v is not None}
            
            # Send command using centralized retry helper
            response = await async_send_command_with_retry(ctx, "manage_editor", params)

            # Preserve structured failure data; unwrap success into a friendlier shape
            if isinstance(response, dict) and response.get("success"):
                return {"success": True, "message": response.get("message", "Editor operation successful."), "data": response.get("data")}
            return response if isinstance(response, dict) else {"success": False, "message": str(response)}

        except Exception as e:
            return {"success": False, "message": f"Python error managing editor: {str(e)}"}