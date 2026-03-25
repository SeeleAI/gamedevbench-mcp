import asyncio
import logging

from mcp.server import FastMCP

from config import config, RUN_PLATFORM_3JS, RUN_PLATFORM_BLENDER
from .execute_menu_item import register_execute_menu_item_tools
from .get_screenshot import register_get_screenshot_tools
from .import_external_asset import register_import_external_asset_tools
from .manage_asset import register_manage_asset_tools
from .manage_editor import register_manage_editor_tools
from .manage_gameobject import register_manage_gameobject_tools
from .manage_image import register_manage_image_tools
from .manage_scene import register_manage_scene_tools
from .manage_script import register_manage_script_tools
from .manage_seele_asset import register_manage_seele_asset_tools
from .manage_shader import register_manage_shader_tools
from .read_console import register_read_console_tools
# from .resource_tools import register_resource_tools
from .seele_game_tool import register_seele_game_tools
from .task_tool import register_task_tools

logger = logging.getLogger("mcp-for-unity-server")

if config.run_platform == RUN_PLATFORM_3JS:
    def register_all_tools(mcp):
        """Register all 3JS tools with the MCP server."""
        logger.info("Registering MCP for 3JS Server tools...")
        
        # 注册所有 3JS 工具（包括脚本管理和资产工具）
        from .threejs_tools import register_threejs_tools
        register_threejs_tools(mcp)
        
        # 任务状态轮询工具暂时不注册（因为 generate_assets 已被禁用，轮询工具无用处）
        # 如果将来重新启用 generate_assets，需要同时恢复此注册
        # register_task_tools(mcp)
        
        logger.info("MCP for 3JS Server tool registration complete.")
elif config.run_platform == RUN_PLATFORM_BLENDER:
    def register_all_tools(mcp):
        """Register all blender tools with the MCP server."""
        logger.info("Registering MCP for blender Server tools...")
        from tools.blender.blender_tools import register_blender_tools
        from .import_external_asset import register_import_external_asset_tools_for_sub_asset_agent
        register_blender_tools(mcp)
        register_manage_seele_asset_tools(mcp)
        register_manage_image_tools(mcp)
        register_task_tools(mcp)
        register_import_external_asset_tools_for_sub_asset_agent(mcp)
        logger.info("MCP for blender Server tool registration complete.")
else:
    def register_all_tools(mcp):
        """Register all refactored tools with the MCP server."""
        # Prefer the surgical edits tool so LLMs discover it first
        logger.info("Registering MCP for Unity Server refactored tools...")
        register_manage_script_tools(mcp)
        register_manage_scene_tools(mcp)
        register_manage_editor_tools(mcp)
        register_manage_gameobject_tools(mcp)
        register_manage_asset_tools(mcp)
        register_manage_shader_tools(mcp)
        register_read_console_tools(mcp)
        register_execute_menu_item_tools(mcp)
        # register_task_tools(mcp)
        register_import_external_asset_tools(mcp)
        register_get_screenshot_tools(mcp)
        # register_handoff_gameobject_asset_tools(mcp)
        # register_manage_image_tools(mcp)
        register_seele_game_tools(mcp)
        logger.info("MCP for Unity Server tool registration complete.")


async def reset_tool_when_config_change(mcp: FastMCP):
    MAIN_LOOP = asyncio.get_running_loop()

    async def on_change_async(cfg: str):
        logger.info(f"Tool config changed: {cfg}, resetting tools...")
        tools = await mcp.list_tools()
        for tool in tools:
            mcp.remove_tool(tool.name)
        register_all_tools(mcp)
        logger.info(f"Tool config changed: {cfg}, reset finished {await mcp.list_tools()}")

    def on_change(cfg: str):
        asyncio.run_coroutine_threadsafe(on_change_async(cfg), MAIN_LOOP)

    from remote_config import subscribe
    from remote_config.schemas import ToolPromptConfig, ToolSwitchConfig
    subscribe(ToolPromptConfig, callback=on_change)
    subscribe(ToolSwitchConfig, callback=on_change)
