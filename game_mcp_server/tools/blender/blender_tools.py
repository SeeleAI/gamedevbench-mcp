import logging
from typing import Any, Dict, Optional, Literal, List

from mcp.server.fastmcp import FastMCP, Context

from config import config
from connection.connection_provider import async_send_command_with_retry
from util.asset_util import update_property_item, get_unique_name, normalize_string
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.invoke_llm_util import (
    analyze_screenshot_with_vision,
    extract_blender_screenshot_data,
)

logger = logging.getLogger(__name__)


def register_blender_tools(mcp: FastMCP):
    @mcp.tool(
        description="""Get detailed information about the current Blender scene
        Args:
            task_name: {{task_name_prompt}}"""
    )
    async def get_scene_info(ctx: Context, task_name: str) -> Dict[str, Any]:
        try:
            result = await async_send_command_with_retry(ctx, "get_scene_info", {})
            return result
        except Exception as e:
            logger.error(f"Error getting scene info from Blender: {str(e)}")
            return {"success": False, "message": str(e)}

    @mcp.tool(
        description="""
        Get detailed information about a specific object in the Blender scene.

        Args:
            object_name: The name of the object to get information about
            task_name: {{task_name_prompt}}
        """
    )
    async def get_object_info(
        ctx: Context, object_name: str, task_name: str
    ) -> Dict[str, Any]:
        try:
            result = await async_send_command_with_retry(
                ctx, "get_object_info", {"object_name": object_name}
            )

            return result
        except Exception as e:
            logger.error(f"Error getting object info from Blender: {str(e)}")
            return {"success": False, "message": str(e)}

    @mcp.tool(
        description="""
        Capture a screenshot of the current Blender 3D viewport.

        Args:
            task_name: {{task_name_prompt}}
            target_object_name: Objects to focus the camera on before capturing the screenshot
            ignore_other_object: When True, hides all objects except target_object_name (requires a valid target)
            view_axis: Optional fixed camera axis to align the view before capture
                FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM: keeps the classic orthographic snaps (front/back/left/right at eye level, top/bottom straight down/up).
                TOP_FRONT_LEFT, TOP_FRONT_RIGHT, TOP_BACK_LEFT, TOP_BACK_RIGHT, BOTTOM_FRONT_LEFT, BOTTOM_FRONT_RIGHT, BOTTOM_BACK_LEFT, BOTTOM_BACK_RIGHT: places the virtual camera on the corresponding cube corner (±X, ±Y, ±Z) so it looks toward the scene from a true 45° diagonal.
        Returns:
            dict: {"image_url": url, "llm_analyzed_info": str, "screen_objects_info": str}
            image_url: the s3 url of the screenshot
            llm_analyzed_info: the analyzed info by llm
            screen_objects_info: the objects info in the screenshot
        """
    )
    async def get_viewport_screenshot(
        ctx: Context,
        task_name: str,
        target_object_name: Optional[List[str]] = None,
        ignore_other_object: Optional[bool] = False,
        view_axis: Optional[
            Literal[
                "LEFT", "RIGHT", "BOTTOM", "TOP", "FRONT", "BACK", "TOP_FRONT_LEFT", "TOP_FRONT_RIGHT", "TOP_BACK_LEFT", "TOP_BACK_RIGHT", "BOTTOM_FRONT_LEFT", "BOTTOM_FRONT_RIGHT", "BOTTOM_BACK_LEFT", "BOTTOM_BACK_RIGHT"]
        ] = None,
    ) -> Dict[str, Any]:
        # 1. 构建请求参数
        params_dict = {
            "target_object_name": target_object_name,
            "ignore_other_object": ignore_other_object,
            "view_axis": view_axis,
        }

        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id

        # 2. 发送截图请求到Blender
        try:
            resp = await async_send_command_with_retry(
                ctx, "get_viewport_screenshot", params_dict
            )
            if not _result_is_success(resp):
                return resp
        except Exception as e:
            logger.error(f"Error capturing screenshot: {str(e)}")
            return {
                "success": False,
                "message": f"Python error getting screenshot: {str(e)}",
            }

        logger.info(f"get_viewport_screenshot resp: {resp}")

        data = resp.get("data", {})
        scene_info = data.get("scene_info", {})

        # 4. 提取截图数据（此时result已经确认不为None）
        url, base64Image, _ = await extract_blender_screenshot_data(data)

        # 5. 构建基础返回字典（方案2.2：不返回base64图片）
        return_dict = {
            "success": True,
            "data": {
                # "image_url": url,
                "image": url,  # 返回截图的url
            },
        }

        # 6. 方案2：无论有没有物体信息，都调用视觉理解补充信息
        # 注意：如果Blender没有返回base64图片，视觉理解可能无法工作
        # 这种情况下，llm_analyze_result会包含错误信息
        if base64Image:
            llm_analyze_result = await analyze_screenshot_with_vision(
                base64Image, scene_info, task_name, trace_id
            )
            # 7. 根据分析结果决定是否返回截图
            if llm_analyze_result.get("success", False):
                # 分析成功，不返回截图，只返回分析结果
                return_dict["data"]["llm_analyzed_info"] = llm_analyze_result["content"]
                # 移除截图数据（如果存在）
                return_dict["data"].pop("image", None)
            else:
                # 分析失败，保留截图让上游LLM自行判断
                return_dict["data"]["llm_analyzed_info"] = llm_analyze_result[
                    "llm_analyzed_info"
                ]
                # 保留截图数据供上游参考
                logger.info(
                    f"Vision analysis failed, keeping screenshot for upstream LLM: {llm_analyze_result.get('content', '')}"
                )
        else:
            logger.warning(
                "Blender screenshot response does not contain base64 image, skipping vision analysis"
            )
            return_dict["data"]["llm_analyzed_info"] = (
                "Vision analysis skipped: base64 image not available"
            )
        logger.info(f"get_viewport_screenshot result task_name:{task_name} image:{url} scene_info:{scene_info}")

        return return_dict

    @mcp.tool(
        description="""
        Execute arbitrary Python code in Blender. Make sure to do it step-by-step by breaking it into smaller chunks.

        Args:
            code: The Python code to execute
            task_name: {{task_name_prompt}}
        """
    )
    async def execute_blender_code(
        ctx: Context, code: str, task_name: str
    ) -> Dict[str, Any]:
        try:
            # Get the global connection
            result = await async_send_command_with_retry(
                ctx, "execute_code", {"code": code}
            )

            return result
        except Exception as e:
            logger.error(f"Error executing code: {str(e)}")
            return {"success": False, "message": str(e)}

    @mcp.tool(description="""
        Export the current Blender visible objects and register the resulting files.

        Args:
            ctx: Active MCP context used to communicate with Blender
            asset_id: use single words or short phrases to naturally describe the asset; ensure ID uniqueness by appending a numeric suffix
            task_name: {{task_name_prompt}}
            target_object_name: Optional list of object names to export; if None, exports the current visible objects

        Returns:
            asset_id: Unique asset identifier
        """)
    async def export_model(ctx: Context, asset_id: str, task_name: str,
                           target_object_name: Optional[List[str]] = None) -> Dict[str, Any]:
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        try:
            result = await async_send_command_with_retry(ctx, "export_model",
                                                         {"target_object_name": target_object_name})

            if not _result_is_success(result):
                return result

            data = result.get("data", {})
            # fbx_url = data.get("fbx_url", "")
            glb_url = data.get("glb_url", "")
            logger.info(f"export finished: glb_url={glb_url}")
            try:
                property_id = await get_unique_name(normalize_string(asset_id), canvas_id)
            except Exception as e:
                return {"success": False, "message": str(e)}
            save_result = await update_property_item(
                canvas_id,
                {
                    "property_id": property_id,
                    "object_type": "export_model",
                    "data": {
                        "model_url": glb_url,
                        # "fbx_url": fbx_url,
                        "glb_url": glb_url,
                    },
                },
            )
            if not save_result.get("success", True):
                return save_result
            return {"success": True, "asset_id": property_id}
        except Exception as e:
            logger.error(f"Error exporting model: {str(e)}")
            return {"success": False, "message": str(e)}

    def _result_is_success(result: Dict[str, Any]) -> bool:
        return result.get("success", False) is True
