"""
MCP tools for remote game project editing, asset workflows, and version operations.
"""
import logging
from mcp.server import FastMCP

logger = logging.getLogger(__name__)


def register_threejs_tools(mcp: FastMCP):
    """Register all remote project tools with the MCP server."""
    logger.info("Registering remote project MCP tools...")
    # Script management tools
    from .create_script import register_create_script_tool
    from .delete_script import register_delete_script_tool
    from .modify_script import register_modify_script_tool
    from .rewrite_script import register_rewrite_script_tool
    from .read_script import register_read_script_tool
    from .grep_script import register_grep_script_tool
    from .list_script import register_list_script_tool
    from .switch_canvas_version import register_switch_canvas_version_tool
    from .convert_s3_file_url import register_convert_s3_file_url_tool
    from .ad_integration import register_ad_integration_tool
    from .sprite_player import register_sprite_player_tool
    # Asset management tools
    from .manage_seele_asset import register_manage_seele_asset_tools
    from .manage_image import register_manage_image_tools
    from .task_tool import register_task_tools
    from remote_config.schemas.tool_prompt_config import ToolSwitchConfig

    tool_switch_config = ToolSwitchConfig.current()
    grep_read_v2 = tool_switch_config.switch.get("grep_read_v2", {}).get("use", True)
    fuzzy_modify = tool_switch_config.switch.get("fuzzy_modify", {}).get("use", True)
    # Query operations (查询操作)
    register_read_script_tool(mcp, v2_mode=grep_read_v2)
    register_grep_script_tool(mcp)
    register_list_script_tool(mcp)
    register_create_script_tool(mcp)
    register_modify_script_tool(mcp, fuzzy_mode=fuzzy_modify)
    register_rewrite_script_tool(mcp)
    register_delete_script_tool(mcp)
    register_convert_s3_file_url_tool(mcp)
    register_switch_canvas_version_tool(mcp)
    # Ad integration tool
    register_ad_integration_tool(mcp)
    # Sprite player tool
    register_sprite_player_tool(mcp)
    # Asset operations (资产操作)
    register_manage_seele_asset_tools(
        mcp,
        enable_generate_assets=False,
        enable_search_external_asset=True,
    )
    register_manage_image_tools(mcp, enable_generate_image=True)
    logger.info("Remote project MCP tools registration complete.")


# Keep old function name for backward compatibility
def register_threejs_script_tools(mcp: FastMCP):
    """Deprecated: Use register_threejs_tools instead."""
    register_threejs_tools(mcp)
