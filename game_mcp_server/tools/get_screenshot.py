"""
Defines the get_screenshot tool for capturing Unity Editor screenshots.
"""

import json
import logging

from mcp.server.fastmcp import Context, FastMCP

from config import config
from connection.connection_provider import async_send_command_with_retry
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.invoke_llm_util import analyze_screenshot_with_vision

logger = logging.getLogger("UnityMCPServer")


def _validate_unity_response(resp: dict) -> dict | None:
    """
    验证Unity返回的响应数据是否有效。

    Args:
        resp: Unity返回的响应字典

    Returns:
        如果验证通过，返回result字典；否则返回None
    """
    result = resp.get("result", {})
    if not result:
        return None
    if not isinstance(result, dict):
        return None
    if not result.get("success"):
        return None
    return result


def _extract_screenshot_data(result: dict) -> tuple[str, str, dict | None]:
    """
    从Unity响应结果中提取截图相关数据。

    Args:
        result: Unity返回的result字典

    Returns:
        元组包含: (url, base64Image, screen_objects_info)
    """
    url = result.get("data", {}).get("url", "")
    base64Image = result.get("data", {}).get("base64Image", "")
    screen_objects_info: dict | None = result.get("data", {}).get(
        "screen_objects_info", None
    )
    return url, base64Image, screen_objects_info


def register_get_screenshot_tools(mcp: FastMCP) -> None:
    """Registers the get_screenshot tool with the MCP server."""

    @mcp.tool(
        description="""Get a screenshot from the Scene view navigation in the Unity Editor.

        Args:
            target: Name of the target GameObject to frame/screenshot. Required when frame_mode = "target".
            frame_mode: Framing mode. One of: "target" (default), "game" (game view).
            task_name: {{task_name_prompt}}

        Returns:
            dict: {"image_url": url, "llm_analyzed_info": str, "screen_objects_info": str}
            image_url: the s3 url of the screenshot
            llm_analyzed_info: the analyzed info by llm
            screen_objects_info: the objects info in the screenshot
        """
    )
    async def get_screenshot(
        ctx: Context,
        target: str = "",
        frame_mode: str | None = None,
        task_name: str | None = None,
    ) -> dict:
        # 1. 构建请求参数
        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        params_dict = {
            "target": target,
            "canvas_id": canvas_id,
        }
        # forward minimal set only when provided (avoid changing defaults on Unity side)
        if frame_mode is not None:
            params_dict["frame_mode"] = frame_mode

        # 2. 发送截图请求到Unity
        resp: dict | None = None
        try:
            resp = await async_send_command_with_retry(
                ctx, "get_screenshot", params_dict
            )
        except Exception as e:
            logger.info("register_get_screenshot_tools error", str(e))
            return {
                "success": False,
                "message": f"Python error getting screenshot: {str(e)}",
            }

        logger.info(f"get_screenshot resp: {resp}")

        # 3. 验证Unity响应
        if not resp.get("success"):
            return resp

        # 4. 提取截图数据（此时result已经确认不为None）
        url, base64Image, screen_objects_info = _extract_screenshot_data(resp)

        # 5. 构建基础返回字典（方案2.2：不返回base64图片）
        return_dict = {
            "success": True,
            "data": {
                # "image_url": url,
                "image": url,  # 返回截图的url
            },
        }

        # 6. 方案2：无论有没有物体信息，都调用视觉理解补充信息
        # 注意：如果Unity没有返回base64图片，视觉理解可能无法工作
        # 这种情况下，llm_analyze_result会包含错误信息
        if base64Image:
            llm_analyze_result = await analyze_screenshot_with_vision(
                base64Image, screen_objects_info, task_name, trace_id
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
                "Unity screenshot response does not contain base64 image, skipping vision analysis"
            )
            return_dict["data"]["llm_analyzed_info"] = (
                "Vision analysis skipped: base64 image not available"
            )

        # 8. 添加物体信息（如果有）
        if screen_objects_info and isinstance(screen_objects_info, dict):
            return_dict["data"]["screen_objects_info"] = json.dumps(screen_objects_info)
        else:
            return_dict["data"]["screen_objects_info"] = ""

        return return_dict
