import json
import logging
import traceback
import uuid
from typing import Dict, Any, List, Literal, Optional, cast

import aiohttp
import orjson
from mcp.server.fastmcp import FastMCP, Context

from config import config
from llm.open_ai_helper import OpenAIHelper
from llm.openai_config import azure_gpt5_mini_config
from remote_config.schemas import MotionRewritePromptConfig, DifyConfig
from util.asset_report import report_search_assets
from util.asset_util import get_unique_name, normalize_string, get_image_url_by_asset_id, update_property_item, \
    get_unique_names, transform_data_url, get_property_list, get_target_property_from_list, \
    save_property
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.dify_client import DifyClient
from util.s3_util import S3Client

logger = logging.getLogger(__name__)
def register_manage_seele_asset_tools(
        mcp: FastMCP,
        enable_generate_assets: bool = True,
        enable_search_external_asset: bool = True,
) -> None:
    if enable_generate_assets:
        @mcp.tool(description="""Create an asynchronous generation or edit asset job from text (or image).

        This method only enqueues/starts the generation workflow (job-creating). You must call the job
        status/result query interface later to retrieve outputs after the workflow finishes.

        Args:
        - category: 'terrain_outdoor' | 'object' | 'avatar' | 'motion'
        - prompt: English AIGC prompt describing desired asset (supports detailed modifiers)
        - action: 'edit' | 'generate' (edit supports only 'terrain_outdoor' | 'object' | 'avatar'; generate supports all listed categories)
        - asset_id: 
            - When action='edit', provide the asset_id of the resource to edit (use an ID returned by a previous generate or search)
            - When action='generate', use single words or short phrases to naturally describe the asset; ensure ID uniqueness by appending a numeric suffix
        - task_name:  {{task_name_prompt}}
        - image_url: Image-conditioned input for generation (image-to-asset). When provided, the model uses the image as a conditioning signal to generate the asset. Supports HTTP(S) URL and image asset_id. Supported for 'terrain_outdoor', 'object', and 'avatar'
        - complexity: Optional 'simple' | 'complex' (only for 'terrain_outdoor'; default 'simple')
        
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
                category: Literal["terrain_outdoor", "object", "avatar", "motion"],
                prompt: str,
                action: Literal["edit", "generate"],
                asset_id: str,
                task_name: str = None,
                image_url: Optional[str] = None,
                complexity: Optional[Literal["simple", "complex"]] = None,
        ) -> Dict[str, Any]:
            return await generate_assets_main(ctx, category, prompt, action, asset_id, task_name, image_url, complexity)
            

    if enable_search_external_asset:
        @mcp.tool(description="""Embedding-based search tool for pre-made game assets from external databases. It is optimized for single-item queries, allowing users to select the best match from variations candidates.

        Args:
        - category: 'object' | 'terrain' | 'avatar' | 'loop_motion' | 'non_loop_motion' | 'sfx' | 'bgm'
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
        - search_results: list of result objects
            - each search_results: { asset_id: Unique asset identifier, tags: string (tags/keywords) }
        """)
        async def search_external_asset(ctx: Context,
                                        category: Literal[
                                            "object", "terrain", "avatar", "loop_motion", "non_loop_motion", "sfx", "bgm"],
                                        asset_id: str,
                                        action: Literal["text", "image"],
                                        text_query: Optional[str] = "",
                                        image_query: Optional[str] = None,
                                        task_name: str = None) -> Dict[str, Any]:
            return await search_external_asset_main(ctx, category, asset_id, action, text_query, image_query, task_name)
            
            
            
async def search_external_asset_main(ctx: Context,
                                        category: Literal[
                                            "object", "terrain", "avatar", "loop_motion", "non_loop_motion", "dance_motion", "sfx", "bgm"],
                                        asset_id: str,
                                        action: Literal["text", "image"],
                                        text_query: Optional[str] = "",
                                        image_query: Optional[str] = None,
                                        task_name: str = None,
                                        return_public_url: bool = False) -> Dict[str, Any]:

    # Runtime validation
    allowed = {"object", "terrain", "avatar", "loop_motion", "non_loop_motion", "dance_motion", "sfx", "bgm"}
    if category not in allowed:
        return {"success": False, "message": f"invalid category: {category}. expected one of {sorted(allowed)}"}
    allow_action = {"text", "image"}
    if action not in allow_action:
        return {"success": False, "message": f"invalid action: {action}. expected one of {sorted(allow_action)}"}

    count = 3
    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
    trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
    canvas_seele_trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
    logger.info(
        f"searching external asset: {asset_id} category: {category} action: {action} query: {text_query}")

    if action == "image":
        allow_image_search = {"avatar", "object", "terrain"}
        if category not in allow_image_search:
            return {"success": False,
                    "message": f"invalid category: {category}. when action is image, expected one of {sorted(allow_image_search)}"}
        if not image_query:
            return {"success": False, "message": "image_query is required when action='image'"}
        image_find_result = await get_image_url_by_asset_id(image_query, canvas_id)
        if not image_find_result.get("success", False):
            return image_find_result
        text_query = image_find_result.get("image_url")
        if text_query.startswith("s3"):
            text_query = S3Client().generate_presigned_url(text_query)
        category = category + "_image"
    type_2_path = {
        "object": "/app/innerapi/search/getAsset",
        "terrain": "/app/innerapi/search/getAsset",
        "avatar": "/app/innerapi/search/getAsset",
        "non_loop_motion": "/app/innerapi/search/getAsset",
        "dance_motion": "/app/innerapi/search/getAsset",
        "loop_motion": "/app/innerapi/search/getAsset",
        "sfx": "/app/innerapi/search/getAsset",
        "bgm": "/app/innerapi/search/getAsset",
        "avatar_image": "/app/innerapi/search/getAssetImage",
        "object_image": "/app/innerapi/search/getAssetImage",
        "terrain_image": "/app/innerapi/search/getAssetImage",
    }
    type_2_search_category = {
        "object": "THING",
        "terrain": "TERRAIN",
        "avatar": "AVATAR",
        "non_loop_motion": "MOTION",
        "dance_motion": "DANCE",
        "loop_motion": "LOOP_MOTION",
        "sfx": "SFX",
        "bgm": "BGM",
        "avatar_image": "AVATAR",
        "object_image": "THING",
        "terrain_image": "TERRAIN",
    }
    if "motion" in category:
        text_query = await _motion_rewrite(text_query, category, trace_id)
        logger.info(f"rewrite motion query: {text_query}")
    try:
        property_ids = await get_unique_names(asset_id, canvas_id, max(1, int(count)))
    except Exception as e:
        return {"success": False, "message": str(e)}
    return await req_search(type_2_path[category],
{
        "category": type_2_search_category[category],
        "text_prompt": text_query,
        "canvas_id": canvas_id,
        "x_seele_canvas_trace_id": trace_id,
    },
    property_ids, canvas_id,canvas_seele_trace_id, return_public_url)



async def generate_assets_main(ctx: Context,
                category: Literal["terrain_outdoor", "object", "avatar", "motion"],
                prompt: str,
                action: Literal["edit", "generate"],
                asset_id: str,
                task_name: str = None,
                image_url: Optional[str] = None,
                complexity: Optional[Literal["simple", "complex"]] = None,) -> Dict[str, Any]:
    # Runtime validation
    allowed = {"terrain_outdoor", "object", "avatar", "motion"}
    if category not in allowed:
        return {"success": False, "message": f"invalid category: {category}. expected one of {sorted(allowed)}"}
    allow_action = {"edit", "generate"}
    if action not in allow_action:
        return {"success": False, "message": f"invalid action: {action}. expected one of {sorted(allow_action)}"}
    allow_edit = {"terrain_outdoor", "object", "avatar"}
    if action == "edit" and category not in allow_edit:
        return {"success": False, "message": f"edit only supported for {allow_edit}"}

    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
    trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
    try:
        property_id = await get_unique_name(normalize_string(asset_id), canvas_id)
    except Exception as e:
        return {"success": False, "message": str(e)}
    logger.info(
        f"generate_assets asset_id: {asset_id}, property_id: {property_id} category {category} canvas_id: {canvas_id}")
    args = {
        "prompt": prompt,
        "complexity": complexity or "simple",
        "dimensions": [1, 1, 1],
        "property_id": property_id,
        "need_update_property": 0,
    }
    dify_config = DifyConfig.current()
    if action == "edit":
        args["edit_asset_id"] = asset_id
        if category == "avatar":
            use_api_key = dify_config.human_gen_key
        else:
            use_api_key = dify_config.thing_gen_key
        return await _dify_thing_gen_creat_task(use_api_key, {
            "type": "edit",
            "args_data": json.dumps(args),
            "canvas_id": canvas_id,
            "x_seele_canvas_trace_id": trace_id,
        }, property_id, canvas_id)
    else:
        if image_url:
            img = await get_image_url_by_asset_id(image_url, canvas_id)
            if not img.get("success", False):
                return img
            args["image_path"] = img.get("image_url")
            gen_type = "image"
            if category == "avatar":
                api_key = dify_config.human_gen_key
            else:
                api_key = dify_config.thing_gen_key
        else:
            if category == "terrain_outdoor":
                gen_type = "terrain_gen"
                api_key = dify_config.thing_gen_key
            elif category == "motion":
                gen_type = "motion"
                api_key = dify_config.motion_gen_key
            elif category == "avatar":
                gen_type = "text"
                api_key = dify_config.human_gen_key
            else:
                gen_type = "text"
                api_key = dify_config.thing_gen_key
        return await _dify_thing_gen_creat_task(api_key, {
            "type": gen_type,
            "args_data": json.dumps(args),
            "canvas_id": canvas_id,
            "x_seele_canvas_trace_id": trace_id,
            "seele_canvas_trace_id": trace_id,
            "prompt": prompt,
            "property_id": property_id,
            "need_update_property": 0,
        }, property_id, canvas_id)



async def _motion_rewrite(query: str, category: str, trace_id: str) -> str:
    ai_helper = OpenAIHelper(config=azure_gpt5_mini_config, trace_id=trace_id, use_json=False,
                             system_prompt=MotionRewritePromptConfig.current().text)
    ai_helper.set_text(f"query: {query}\ncategory: {category}\n")
    try:
        result = await ai_helper.send_request()
        return ai_helper.get_resp_content(result)
    except Exception as e:
        logger.warning(f"rewrite motion fail {e} {traceback.format_exc()}")
        return query


async def req_search(path: str, inputs: dict, property_ids: List[str], canvas_id: str, canvas_seele_trace_id:str,return_public_url: bool = False) -> Dict[str, Any]:
    """Call inner search API via aiohttp with token header.

    Args:
    - inputs: request body to forward; will be augmented with a generated property_id

    Returns:
    - property_id: string (generated request id)
    - tags: string (tags/keywords) on success
    - on error: {success: False, message: str}
    """
    url = f"{config.app_base_url}{path}"
    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
        "x-canvas-id": canvas_id,
        "canvas-seele-trace-id":canvas_seele_trace_id
    }
    inputs = dict(inputs or {})
    inputs["property_ids"] = property_ids
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=inputs, headers=headers) as resp:
                ok = 200 <= resp.status < 300
                try:
                    body = await resp.json(loads=orjson.loads)
                except Exception as e:
                    text = await resp.text()
                    logger.warning(f"Failed to get response from {url} {resp.status}: {text} e:{e}")
                    return {"success": False, "message": f"HTTP {resp.status}: {text}"}
                if not ok:
                    logger.warning(f"Failed to get response from {url}: {resp.status}: {body}")
                    return {"success": False, "message": f"HTTP {resp.status}: {body}"}
                data = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"{canvas_id} search finish data:{data}")
                search_results = []
                try:
                    property_list = await get_property_list(canvas_id)
                except Exception as e:
                    return {"success": False, "message": str(e)}
                for item in data:
                    property_id = item.get("property_id")
                    tags = item.get("tags")
                    target_property = get_target_property_from_list(property_id, property_list)
                    # 确保 data 字段存在，transform_data_url 会原地修改它，添加 *_public 字段
                    if "data" not in target_property or target_property["data"] is None:
                        target_property["data"] = {}
                    await transform_data_url(target_property["data"])
                    await report_search_assets(canvas_id, [target_property])
                    logger.info(f"target_property transform:{target_property}")
                    if return_public_url:
                        # ThreeJS环境：返回public_url
                        data_dict = target_property.get("data", {}) or {}
                        public_url = (data_dict.get("three_js_model_file_url_public") or
                                     data_dict.get("model_url_public") or
                                     data_dict.get("fbx_url_public") or 
                                     data_dict.get("sfx_url_public") or 
                                     data_dict.get("bgm_url_public") or 
                                     data_dict.get("image_url_public") or 
                                     data_dict.get("audio_url_public"))
                        search_results.append({
                            "public_url": public_url,
                            "tags": tags
                        })
                    else:
                        # Unity环境：返回asset_id
                        search_results.append({
                            "asset_id": property_id,
                            "tags": tags
                        })
                save_result = await save_property(property_list, canvas_id)
                if not save_result.get("success", True):
                    return save_result
                result_info = {"success": True, "search_results": search_results}
                # image_asset_id = await _save_model_front_image(canvas_id, data, property_id)
                # if image_asset_id:
                #     result_info["image_asset_id"] = image_asset_id
                return result_info
    except Exception as e:
        return {"success": False, "message": f"request failed: {e}"}


async def _dify_thing_gen_creat_task(
        api_key: str,
        inputs: dict,
        property_id: str,
        canvas_id: str, ):
    try:
        gen_type = inputs.get("type")
        if not gen_type:
            logger.warning(f"input type not found in inputs: {inputs}")
            return {"success": False, "message": "input type is required"}
        client = DifyClient(api_key=api_key, canvas_id=canvas_id)
        start_workflow_result = await client.start_workflow_and_get_task_id(inputs=inputs)
        if not start_workflow_result.get("success"):
            logger.warning(f"failed to start workflow: {start_workflow_result}")
            return start_workflow_result
        workflow_run_id = start_workflow_result.get("workflow_run_id")
        if not workflow_run_id:
            return {"success": False, "message": f"not find workflow_run_id result is:{start_workflow_result}"}
        save_result = await update_property_item(canvas_id, {
            "property_id": property_id,
            "object_type": gen_type,
            "data": {
                "workflow_run_id": workflow_run_id,
                "status": "running",
                "estimated_time": 300,
                "api_key": api_key,
            },
        })
        if not save_result.get("success", True):
            return save_result
        return {
            "success": True,
            "asset_id": property_id,
        }
    except Exception as e:
        return {"success": False, "message": f"error: {e}"}


async def _dify_thing_gen(
        api_key: str,
        inputs: dict,
        property_id: str,
        canvas_id: str,
) -> Dict[str, Any]:
    client = DifyClient(api_key=api_key, canvas_id=canvas_id)
    inputs["property_id"] = property_id
    try:
        result = await client.run_workflow(inputs=inputs)
        if not result["success"]:
            logger.warning(f"gen fail result {result}")
            return result
        output = result.get("data", {}).get("output", {})
        if not output:
            logger.warning(f"gen fail , not find output {result}")
            return {"success": False, "message": "request failed"}
        if isinstance(output, str):
            output = json.loads(output)
        result_info = {
            "success": True,
            "asset_id": output.get("property_id"),
        }
        logger.info(f"gen result info: {result_info}")
        image_asset_id = await _save_model_front_image(canvas_id, output, property_id)
        if image_asset_id:
            result_info["image_asset_id"] = image_asset_id
        return result_info
    except Exception as e:
        return {"success": False, "message": f"error: {e}"}


async def _save_model_front_image(canvas_id: str, output: dict, property_id: str):
    try:
        if not isinstance(output, dict):
            return None
        front_view_url = output.get("front_view_url") or output.get("preview_url")
        if not front_view_url:
            return None
        from util.asset_util import get_property_list, save_property  # local import to avoid circulars
        try:
            property_list = await get_property_list(canvas_id)
            property_id = await get_unique_name(property_id + "_image", canvas_id, property_list)
        except Exception as e:
            return None
        if not property_list:
            return None
        property_list.append({
            "property_id": property_id,
            "prompt": "",
            "object_type": "image",
            "data": {
                "image_url": front_view_url,
            },
        })
        save_result = await save_property(property_list, canvas_id)
        if save_result.get("success", True):
            return property_id
        return None
    except Exception as e:
        logger.warning(f"_save_model_front_image failed: {e}")
    return None


# ----- test -----
async def aa_text_generate_outdoor_scene_assets(
        ctx: Context,
        prompt: str,
        complexity: Literal["simple", "complex"],
        dimensions: List[float],
) -> Dict[str, Any]:
    property_id = str(uuid.uuid4())
    return await _dify_thing_gen(DifyConfig.current().dify_thing_gen_key, {
        "type": "text",
        "args_data": json.dumps({
            "prompt": prompt,
            "property_id": property_id,
        }),
        "canvas_id": config.test_canvas_id,
        "x_seele_canvas_trace_id": config.test_trace_id,
    }, property_id, config.test_canvas_id)


async def search_assets(ctx: Context,
                        query: str,
                        category: Literal[
                            "object", "terrain", "avatar", "motion", "dance", "sfx", "bgm", "avatar_image", "object_image",
                            "terrain_image"],
                        asset_id: str,
                        image_asset_id: str) -> Dict[str, Any]:
    """Unified asset search for models, motions, and sounds.

    Args:
    - query: English text for search
    - category: 'object' | 'terrain' | 'avatar' | 'motion' | 'dance' | 'sfx' | 'bgm'
    - asset_id: Unique asset identifier (only [a-z0-9_] allowed)
    - image_asset_id: Image asset_id (URL also supported).

    Returns:
    - asset_id: Unique asset identifier
    - tags: string (tags/keywords related to results)

    Category notes:
    - object: vehicles/furniture/props
    - terrain: environments (indoor/outdoor)
    - avatar: humanoids
    - motion/dance: general motions and dance motions
    - sfx/bgm: sound effects / background music
    """
    # Runtime validation
    allowed = {"object", "terrain", "avatar", "motion", "dance", "sfx", "bgm", "avatar_image", "object_image",
               "terrain_image"}
    # if not isinstance(query, str) or not query.strip():
    #     return {"success": False, "message": "query must be a non-empty string"}
    if category not in allowed:
        return {"success": False, "message": f"invalid category: {category}. expected one of {sorted(allowed)}"}
    if image_asset_id and category in ["avatar_image", "object_image", "terrain_image"]:
        image_find_result = await get_image_url_by_asset_id(image_asset_id, config.test_canvas_id)
        if not image_find_result.get("success", False):
            return image_find_result
        query = image_find_result.get("image_url")
        if query.startswith("s3"):
            query = S3Client().generate_presigned_url(query)
    type_2_path = {
        "object": "/app/innerapi/search/getAsset",
        "terrain": "/app/innerapi/search/getAsset",
        "avatar": "/app/innerapi/search/getAsset",
        "basic_motion": "/app/innerapi/search/getAsset",
        "dance_motion": "/app/innerapi/search/getAsset",
        "sfx": "/app/innerapi/search/getAsset",
        "bgm": "/app/innerapi/search/getAsset",
        "avatar_image": "/app/innerapi/search/getAssetImage",
        "object_image": "/app/innerapi/search/getAssetImage",
        "terrain_image": "/app/innerapi/search/getAssetImage",
    }
    type_2_search_category = {
        "object": "THING",
        "terrain": "TERRAIN",
        "avatar": "AVATAR",
        "basic_motion": "MOTION",
        "dance_motion": "DANCE",
        "sfx": "SFX",
        "bgm": "BGM",
        "avatar_image": "AVATAR",
        "object_image": "THING",
        "terrain_image": "TERRAIN",
    }
    # if category in ["basic_motion", "dance_motion"]:
    #     query = await _motion_rewrite(query, trace_id)
    #     logger.info(f"rewrite motion query: {query}")
    # property_id = await get_unique_name(normalize_string(asset_id), canvas_id)
    property_ids = [str(uuid.uuid4()),str(uuid.uuid4())]
    return await req_search(type_2_path[category], {
        "category": type_2_search_category[category],
        "text_prompt": query,
        "canvas_id": config.test_canvas_id,
        "x_seele_canvas_trace_id": config.test_trace_id,
    }, property_ids, config.test_canvas_id)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d [%(asctime)s,%(msecs)03d] [%(levelname)s] [%(name)s:%(funcName)s] [%(filename)s:%(lineno)d] [%(message)s]",
                        datefmt='%Y-%m-%d %H:%M:%S')
    # print(asyncio.run(req_search("/app/innerapi/search/getModel", {
    #     "category": "avatar",
    #     "text_prompt": "apple",
    #     "canvas_id": config.test_canvas_id,
    #     "x_seele_canvas_trace_id": config.test_trace_id,
    # }, "test02", config.test_canvas_id)))
    # print(asyncio.run(aa_text_generate_outdoor_scene_assets(None, "apple", "complex", [1, 1, 1])))
    # print(asyncio.run(search_assets(None, "run", "object", "jump", "")))
    # property_id = str(uuid.uuid4())
    # print(asyncio.run(_dify_thing_gen_creat_task(config.dify_thing_gen_key, {
    #     "type": "text",
    #     "args_data": json.dumps({
    #         "prompt": "apple",
    #         "complexity": "simple",
    #         "dimensions": [1, 1, 1],
    #         "property_id": property_id,
    #         "need_update_property": 0,
    #     }),
    #     "canvas_id": config.test_canvas_id,
    #     "x_seele_canvas_trace_id": config.test_trace_id,
    # }, property_id, config.test_canvas_id)))



