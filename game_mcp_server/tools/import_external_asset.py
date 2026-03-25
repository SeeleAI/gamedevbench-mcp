"""
Defines tools for importing external assets into Unity project.
"""
import json
import logging
import traceback
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from config import config
from connection.connection_provider import async_send_command_with_retry
from util.asset_util import get_target_property, update_property_item, transform_data_url, PUBLIC_FIX
from util.context_util import get_context_canvas_id

logger = logging.getLogger(__name__)


def register_import_external_asset_tools(mcp: FastMCP):
    """Register the external asset import tools with the MCP server."""

    @mcp.tool(description="""Import the generated asset or search asset into Unity by asset_id.

        This tool downloads the asset from the provided asset_id and imports it into the Unity project.
        For motion assets (FBX files), it automatically extracts animation clips and saves them as separate .anim files.

        Args:
            category: the category of the asset (e.g., 'terrain', 'object', 'avatar', 'motion', 'music', 'image').
            asset_id: The asset_id returned by the Generate Assets tool or the Search Assets tool.
            task_name: {{task_name_prompt}}

        Returns:
            Dictionary with operation results ('success', 'message', 'data', 'game_object_name').
        """)
    async def import_external_asset(
            ctx: Context,
            category: Literal["terrain", "object", "avatar", "motion", "music", "image"],
            asset_id: str,
            task_name: str,
    ) -> dict:
        return await import_external_asset_iml(ctx, category, asset_id, task_name)


def register_import_external_asset_tools_for_sub_asset_agent(mcp: FastMCP):
    """Register the external asset import tools with the MCP server."""

    @mcp.tool(description="""Import the generated asset or search asset into Unity by asset_id.

        This tool downloads the asset from the provided asset_id and imports it into the Unity project.
        For motion assets (FBX files), it automatically extracts animation clips and saves them as separate .anim files.

        Args:
            category: the category of the asset (e.g., 'terrain', 'object', 'motion', 'music', 'image').
            asset_id: The asset_id returned by the Generate Assets tool or the Search Assets tool.
            task_name: {{task_name_prompt}}

        Returns:
            Dictionary with operation results ('success', 'message', 'data', 'game_object_name').
        """)
    async def import_external_asset(
            ctx: Context,
            category: Literal["terrain", "object", "motion", "music", "image"],
            asset_id: str,
            task_name: str,
    ) -> dict:
        return await import_external_asset_iml(ctx, category, asset_id, task_name)


async def import_external_asset_iml(
        ctx: Context,
        category: Literal["terrain", "object", "avatar", "motion", "music", "image"],
        asset_id: str,
        task_name: str,
) -> dict:
    # 获取请求 header 中的 canvas_id
    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id

    try:
        target_property = await get_target_property(canvas_id, asset_id)
    except Exception as e:
        return {"success": False, "message": str(e)}
    if not target_property:
        return {"success": False, "message": f"Property with ID {asset_id} not found."}
    logger.info(f"target_property: {target_property}")
    data = target_property.get("data", {}) or {}
    await transform_data_url(data)
    if data.get("fbx_url" + PUBLIC_FIX):
        url = data.get("fbx_url" + PUBLIC_FIX)
    elif data.get("model_url" + PUBLIC_FIX):
        url = data.get("model_url" + PUBLIC_FIX)
    elif data.get("sfx_url" + PUBLIC_FIX):
        url = data.get("sfx_url" + PUBLIC_FIX)
    elif data.get("bgm_url" + PUBLIC_FIX):
        url = data.get("bgm_url" + PUBLIC_FIX)
    elif data.get("image_url" + PUBLIC_FIX):
        url = data.get("image_url" + PUBLIC_FIX)
    else:
        return {"success": False, "message": f"asset_id: {asset_id} has no resource."}
    logger.info(f"url: {url}")
    await update_property_item(canvas_id, target_property)
    params = {
        "url": url,
        "asset_id": asset_id,
        "category": category,
        "auto_import": True,
        "all_assets": json.dumps(data),
        "name": asset_id
    }
    try:
        result = await async_send_command_with_retry(ctx, "import_external_asset", params, max_retries=1,
                                                     retry_ms=600)
        logger.info(f"Import asset with name {asset_id} successfully, result: {result}")
        if result and isinstance(result, dict):
            return result
        else:
            return {"success": False,
                    "message": f"unity return invalid result when import asset with name {asset_id}."}
    except Exception as e:
        logger.error(f"Import external asset failed: {e} {traceback.format_exc()}")
        return {"success": False, "message": f"Import external asset failed: {e}"}
