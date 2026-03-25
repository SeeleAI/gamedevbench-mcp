import json
import logging
from typing import Dict, Any, List, Literal, Optional, cast

from mcp.server.fastmcp import FastMCP, Context

from config import config
from remote_config.schemas import DifyConfig
from util.asset_util import get_unique_name, normalize_string, get_image_url_by_asset_id
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id

# 导入完全相同的通用函数
from ..manage_seele_asset import (
    _dify_thing_gen_creat_task,
    search_external_asset_main,
    generate_assets_main
)

logger = logging.getLogger(__name__)


def register_manage_seele_asset_tools(
        mcp: FastMCP,
        enable_generate_assets: bool = True,
        enable_search_external_asset: bool = True,
) -> None:
    if enable_generate_assets:
        @mcp.tool(description="""Create an asynchronous asset generation or asset edit job from text (or image).

        This method only enqueues/starts the generation workflow (job-creating). You must call the job
        status/result query interface later to retrieve outputs after the workflow finishes.

        Use this tool when the task needs new art, motion, terrain, avatar, or object assets
        that can support gameplay, visuals, or content production for the current game project.

        Args:
        - category: 'terrain_indoor' | 'terrain_outdoor' | 'object' | 'avatar' | 'motion'
        - prompt: English AIGC prompt describing desired asset (supports detailed modifiers)
        - action: 'edit' | 'generate' (edit supports only 'terrain_outdoor' | 'object' | 'avatar'; generate supports all listed categories)
        - asset_id: 
            - When action='edit', provide the asset_id of the resource to edit (use an ID returned by a previous generate or search)
            - When action='generate', use single words or short phrases to naturally describe the asset; ensure ID uniqueness by appending a numeric suffix
        - task_name:  {{task_name_prompt}}
        - image_url: Image-conditioned input for generation (image-to-asset). When provided, the model uses the image as a conditioning signal to generate the asset. Supports HTTP(S) URL and image asset_id. Supported for 'terrain_outdoor', 'object', and 'avatar'
        - complexity: Optional 'simple' | 'complex' (only for 'terrain_indoor'/'terrain_outdoor'; default 'simple')
        - room_list: For 'terrain_indoor' to define each room. Required when category is 'terrain_indoor' and must contain at least one item. List of objects with fields:
            - room_name: string (e.g., "Bedroom", "Kitchen")
            - walls: string (e.g., "concrete walls")
            - floor: string (e.g., "wood flooring")
            - ceiling: string (e.g., "white ceiling")
          Example:
          [
              {
                "room_name": "Bedroom",
                "walls": "concrete walls",
                "floor": "wood flooring",
                "ceiling": "white ceiling"
              },
              {
                "room_name": "Kitchen",
                "walls": "concrete walls",
                "floor": "wood flooring",
                "ceiling": "white ceiling"
              }
          ]

        Returns:
        - success: boolean
        - asset_id: Unique asset identifier for this generation job; use it to fetch job status/result
        - message: string (only when success=False)

        Complexity notes (terrain_outdoor):
        - complex: diverse structures and rich details with layered spaces or many decorative elements (e.g., dense forests, jagged rocky fields, deep canyons, coral reefs, jungles, gardens/streets/cityscapes/playgrounds/ruins)
        - simple: single, flat or repetitive surfaces with minimal detail (e.g., desert dunes, beaches, grasslands, snowfields, plains, calm lake surfaces)
        """)
        async def generate_assets(
                ctx: Context,
                category: Literal[
                    "terrain_indoor", "terrain_outdoor", "object", "avatar", "motion"],
                prompt: str,
                action: Literal["edit", "generate"],
                asset_id: str,
                task_name: Optional[str] = None,
                image_url: Optional[str] = None,
                room_list: Optional[List[Dict[str, Any]]] = None,
                complexity: Optional[Literal["simple", "complex"]] = None,
        ) -> Dict[str, Any]:
            # 对于 terrain_indoor，需要特殊处理（通用函数不支持）
            if category == "terrain_indoor":
                # Runtime validation
                if action == "edit":
                    return {"success": False, "message": "edit is not supported for 'terrain_indoor'"}
                if not room_list or not isinstance(room_list, list) or len(room_list) == 0:
                    return {"success": False,
                            "message": "room_list is required for 'terrain_indoor' and must contain at least one item"}
                
                canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
                trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
                property_id = await get_unique_name(normalize_string(asset_id), canvas_id)
                logger.info(
                    f"generate_assets asset_id: {asset_id}, property_id: {property_id} category {category} canvas_id: {canvas_id}")
                args = {
                    "prompt": prompt,
                    "complexity": complexity or "simple",
                    "dimensions": [1, 1, 1],
                    "property_id": property_id,
                    "need_update_property": 0,
                    "room_list": room_list or [],
                }
                dify_config = DifyConfig.current()
                if not dify_config or not dify_config.thing_gen_key:
                    return {"success": False, "message": "thing_gen_key not configured"}
                return await _dify_thing_gen_creat_task(dify_config.thing_gen_key, {
                    "type": "terrain_room",
                    "args_data": json.dumps(args),
                    "canvas_id": canvas_id,
                    "x_seele_canvas_trace_id": trace_id,
                    "seele_canvas_trace_id": trace_id,
                    "prompt": prompt,
                    "property_id": property_id,
                    "need_update_property": 0,
                }, property_id, canvas_id)
            else:
                # 对于其他 category，直接调用通用函数
                # 通用函数中 task_name: str = None，运行时接受 None
                return await generate_assets_main(ctx, category, prompt, action, asset_id, task_name, image_url, complexity)  # type: ignore[arg-type]

    if enable_search_external_asset:
        @mcp.tool(description="""Search external game asset libraries for pre-made assets. It is optimized for single-item queries so you can select the best match from candidate results.

        Args:
        - category: 'object' | 'terrain' | 'avatar' | 'basic_motion' | 'dance_motion' | 'sfx' | 'bgm'
        - asset_id: Starting identifier for returned assets. Use single words or short phrases to naturally describe the asset; ensure ID uniqueness by appending a numeric suffix
        - action: 'text' | 'image' 
            - text: text-based retrieval
            - image: image-based retrieval, required for visual category('object' | 'terrain' | 'avatar')
        - text_query: Concise English prompt focus on the single item wanted. Only required for text-based retrieval.
        - image_query: URL or existing image asset_id. Required (and only accepted) when action='image'.
        - task_name: {{task_name_prompt}}
        
        Returns:
        - success: boolean
        - message: string (only when success=False)
        - search_results: list of result objects, each containing:
            - public_url: Publicly accessible URL for the asset
            - tags: string (tags/keywords)
        """)
        async def search_external_asset(ctx: Context,
                                        category: Literal[
                                            "object", "terrain", "avatar", "basic_motion", "dance_motion", "sfx", "bgm"],
                                        asset_id: str,
                                        action: Literal["text", "image"],
                                        text_query: Optional[str] = "",
                                        image_query: Optional[str] = None,
                                        task_name: Optional[str] = None) -> Dict[str, Any]:
            # 将 ThreeJS 的 category 映射到通用版本的 category
            # basic_motion -> non_loop_motion
            category_mapping: Dict[str, str] = {
                "basic_motion": "non_loop_motion",
                "dance_motion": "dance_motion",
                "object": "object",
                "terrain": "terrain",
                "avatar": "avatar",
                "sfx": "sfx",
                "bgm": "bgm",
            }
            mapped_category = category_mapping.get(category, category)
            # 调用通用函数，传入 return_public_url=True
            # 使用类型转换，因为 mapped_category 保证是有效的 Literal 值
            return await search_external_asset_main(
                ctx, 
                cast(Literal["object", "terrain", "avatar", "loop_motion", "non_loop_motion", "dance_motion", "sfx", "bgm"], mapped_category),
                asset_id, 
                action, 
                text_query or "", 
                image_query, 
                task_name,  # type: ignore[arg-type]
                return_public_url=True
            )
