"""
Defines the execute_menu_item tool for running Unity Editor menu commands.
"""
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry  # Import retry helper


def register_execute_menu_item_tools(mcp: FastMCP):
    """Registers the execute_menu_item tool with the MCP server."""

    @mcp.tool(description="""Executes a Unity Editor menu item via its path (e.g., "File/Save Project").

        Args:
            menu_path: The full path of the menu item to execute.
            action: The operation to perform (default: 'execute').
            parameters: Optional parameters for the menu item (rarely used).
            task_name: {{task_name_prompt}}

        Returns:
            A dictionary indicating success or failure, with optional message/error.
        """)
    async def execute_menu_item(
        ctx: Context,
        menu_path: str,
        action: str = 'execute',
        parameters: Dict[str, Any] = None,
        task_name: str = None,
    ) -> Dict[str, Any]:
        
        
        action = action.lower() if action else 'execute'
        
        # Prepare parameters for the C# handler
        params_dict = {
            "action": action,
            "menuPath": menu_path,
            "parameters": parameters if parameters else {},
        }

        # Remove None values
        params_dict = {k: v for k, v in params_dict.items() if v is not None}

        if "parameters" not in params_dict:
            params_dict["parameters"] = {} # Ensure parameters dict exists

        # Use centralized retry helper
        resp = await async_send_command_with_retry(ctx, "execute_menu_item", params_dict)
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}