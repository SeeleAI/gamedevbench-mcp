import asyncio
import logging
import traceback
from typing import Optional, Dict, Any, Literal, List

import aiohttp
import orjson
from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from pydantic import BaseModel

from config import config, RUN_PLATFORM_3JS
from util.asset_report import report_asset, asset_type_generate
from util.asset_util import get_property_list, get_unique_name, normalize_string, save_property, \
    get_image_url_by_asset_id, transform_data_url, PUBLIC_FIX
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id

logger = logging.getLogger(__name__)
ERROR_INSUFFICIENT_GPU_MEMORY = -20002

class GenerateImageInfo(BaseModel):
    prompt: str
    asset_id: str
    transparent_background: bool
    image_url: Optional[str] = None
    image_aspect_ratio: Optional[Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]] = None
    image_size: Optional[Literal["1K", "2K", "4K"]] = None

class GenerateSpriteInfo(BaseModel):
    prompt: str
    asset_id: str
    duration: int
    first_frame_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    fps: Optional[int] = 8
    image_max_size: Optional[int] = 256

def register_manage_image_tools(mcp: FastMCP, enable_generate_image: bool = True) -> None:
    if not enable_generate_image:
        return

    @mcp.tool(description="""Generate or edit images for game development via gateway service. Supports creating 2D sprites, UI elements, textures, icons, backgrounds and other game assets.

        Args:
            image_info: Batch description list. Each item contains:
                prompt: Text describing the asset's purpose and specific requirements. Examples:
                - "UI health potion icon, red glass bottle with glowing liquid, 128x128, flat design style, transparent background"
                - "stone floor texture for 3D terrain, seamless tiling, realistic PBR material, 1024x1024"
                asset_id: generated image asset id
                task_name: {{task_name_prompt}}
                image_url: When provided, edits the existing image referenced by this asset_id using the prompt (e.g., modify style, add/remove elements). When omitted, generates a new image from the prompt.
                image_aspect_ratio: Image aspect ratio, supported parameters:"1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"
                image_size: Image dimensions to be generated; supported parameters:"1K", "2K", "4K"
                transparent_background: When True, runs an additional background removal pass on the generated image before saving.
        
            task_name: {{task_name_prompt}}
        Returns:
            - success: bool True if all requested images are generated and saved
            - data: list of generated asset details (asset_id/public_url)
            - errors: list of failed items when partial success occurs
        """)
    async def generate_image(ctx: Context,
                             image_info: List[GenerateImageInfo],
                             task_name: Optional[str] = None, ) -> Dict[str, Any]:
        return await generate_image_iml(ctx, image_info, task_name)


async def generate_image_iml(ctx: Context,
                             image_info: List[GenerateImageInfo],
                             task_name: Optional[str] = None, ) -> Dict[str, Any]:
    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
    trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id

    if not image_info:
        return {"success": False, "message": "image_info must be a non-empty list"}

    generation_tasks = [
        _generate_single_image_entry(info, canvas_id, trace_id)
        for info in image_info
    ]
    task_results = await asyncio.gather(*generation_tasks, return_exceptions=True)

    success_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, task_result in enumerate(task_results):
        info = image_info[idx]
        if isinstance(task_result, BaseException):
            logger.exception("image generation task raised exception for asset_id=%s", info.asset_id)
            errors.append({
                "asset_id": info.asset_id,
                "message": str(task_result),
            })
            continue
        if not isinstance(task_result, dict):
            errors.append({
                "asset_id": info.asset_id,
                "message": "unexpected generation response",
            })
            continue
        if not task_result.get("success"):
            errors.append({
                "asset_id": info.asset_id,
                "message": task_result.get("message", "unknown error"),
            })
            continue
        success_items.append(task_result)

    if not success_items:
        return {
            "success": False,
            "message": "all image generations failed",
            "errors": errors,
        }

    update_result = await _bulk_update_generated_properties(success_items, canvas_id,object_type="image")
    if not update_result.get("success", False):
        if errors:
            update_result.setdefault("errors", errors)
        return update_result

    response: Dict[str, Any] = {
        "success": len(errors) == 0,
        "results": update_result.get("results", []),
    }
    if errors:
        response["errors"] = errors
        response.setdefault("message", "partial success")
    return response


async def _generate_single_image_entry(info: GenerateImageInfo,
                                       canvas_id: str,
                                       trace_id: str) -> Dict[str, Any]:
    prompt = info.prompt
    if not prompt:
        return {"success": False, "message": "prompt is required"}
    try:
        gen_result = await _gen_image_iml(
            prompt,
            canvas_id,
            info.image_url,
            trace_id,
            info.image_aspect_ratio,
            info.image_size,
        )
    except Exception as exc:
        logger.exception("image generation exception for asset_id=%s", info.asset_id)
        return {"success": False, "message": f"generation exception: {exc}"}

    if not gen_result.get("success", False):
        return {
            "success": False,
            "message": gen_result.get("message", "generate image failed"),
        }
    use_image_url = gen_result.get("data", {}).get("data", {}).get("image_url", "")
    if not use_image_url:
        return {
            "success": False,
            "message": "generate image response missing image_url",
        }

    if info.transparent_background:
        rembg_image_url = await rembg(use_image_url, canvas_id, trace_id)
        if rembg_image_url:
            use_image_url = rembg_image_url

    image_data = {"image_url": use_image_url}
    await transform_data_url(image_data)
    use_image_url_public = image_data.get("image_url" + PUBLIC_FIX) or use_image_url

    return {
        "success": True,
        "asset_id": info.asset_id,
        "prompt": prompt,
        "image_url": use_image_url,
        "image_url_public": use_image_url_public,
    }


async def rembg(use_image_url: str, canvas_id: str, trace_id: str = "") -> str | None:
    rembg_url = f"{config.syn_base_url}/gateway/api/image_rembg?abs_cuda_proxy_service_name=imagegen&abs_cuda_proxy_func_name=image_rembg"
    payload = {
        "image_url": use_image_url
    }
    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
        "x-canvas-id": canvas_id,
        "x-seele-canvas-trace-id": trace_id
    }
    try:
        timeout = aiohttp.ClientTimeout(total=200)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(rembg_url, json=payload, headers=headers) as resp:
                status = resp.status
                body_text: Optional[str] = None
                body_json = await resp.json(loads=orjson.loads)
                ok = 200 <= status < 300
                if not ok or body_json is None or body_json.get("code") != 0:
                    logger.warning(f"rembg request failed {status}: {body_json or body_text}")
                    return None
                return body_json.get("data", {}).get("image_url")
    except Exception as e:
        logger.warning(f"rembg request exception {e} {traceback.format_exc()}")
        return use_image_url


async def generate_sprite_iml(
        ctx: Context,
        sprite_info: List[GenerateSpriteInfo],
        task_name: Optional[str] = None,
) -> Dict[str, Any]:
    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
    trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id

    # 校验输入参数
    if not sprite_info:
        return {"success": False, "message": "sprite_info must be a non-empty list"}

    # 创建并发任务列表
    generation_tasks = [
        _generate_single_sprite_entry(info, canvas_id, trace_id, task_name)
        for info in sprite_info
    ]

    # 并发执行所有精灵图生成任务
    task_results = await asyncio.gather(*generation_tasks, return_exceptions=True)

    # 分类处理成功和失败的结果
    success_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, task_result in enumerate(task_results):
        info = sprite_info[idx]
        # 处理任务执行过程中抛出的异常
        if isinstance(task_result, BaseException):
            logger.exception("sprite generation task raised exception for asset_id=%s", info.asset_id)
            errors.append({
                "asset_id": info.asset_id,
                "message": str(task_result),
            })
            continue

        # 校验返回结果格式
        if not isinstance(task_result, dict):
            errors.append({
                "asset_id": info.asset_id,
                "message": "unexpected sprite generation response",
            })
            continue

        # 处理生成失败的情况
        if not task_result.get("success"):
            errors.append({
                "asset_id": info.asset_id,
                "message": task_result.get("message", "unknown error"),
            })
            continue

        # 收集成功的结果
        success_items.append(task_result)

    # 所有任务都失败的情况
    if not success_items:
        return {
            "success": False,
            "message": "all sprite generations failed",
            "errors": errors,
        }

    # 批量更新属性
    update_result = await _bulk_update_generated_properties(success_items, canvas_id,object_type="sprite")
    if not update_result.get("success", False):
        if errors:
            update_result.setdefault("errors", errors)
        return update_result

    # 构造最终返回结果
    response: Dict[str, Any] = {
        "success": len(errors) == 0,
        "results": update_result.get("results", []),
    }

    # 如果有失败项，添加错误信息和部分成功的提示
    if errors:
        response["errors"] = errors
        response.setdefault("message", "partial success")

    return response

async def _generate_single_sprite_entry(
    info: GenerateSpriteInfo,
    canvas_id: str,
    trace_id: str,
    task_name: Optional[str] = None,
) -> Dict[str, Any]:
    # 参数校验
    if not info.prompt.strip():
        return {"success": False, "message": "prompt is required", "asset_id": info.asset_id}
    if info.duration <= 0:
        return {"success": False, "message": "duration must be positive", "asset_id": info.asset_id}
    # if not info.first_frame_url:
    #     return {"success": False, "message": "first_frame_url is required", "asset_id": info.asset_id}

    # 带重试机制的精灵图生成
    async def _try_gen_sprite(max_retry: int = 1) -> Dict[str, Any]:
        retry_count = 0
        while retry_count <= max_retry:
            result = await _gen_sprite_iml(
                prompt=info.prompt,
                duration=info.duration,
                canvas_id=canvas_id,
                trace_id=trace_id,
                first_frame_url=info.first_frame_url,
                last_frame_url=info.last_frame_url,
                fps=info.fps,
                task_name=task_name
            )

            if result.get("success"):
                return result

            response_code = result.get("code", False)
            logger.warning(
                f"sprite failed | asset_id={info.asset_id} | code={response_code} | retry={retry_count}/{max_retry} | trace_id={trace_id}"
            )

            # GPU显存不足时重试
            if response_code == ERROR_INSUFFICIENT_GPU_MEMORY and retry_count < max_retry:
                retry_count += 1
                logger.warning(
                    f"GPU显存不足，开始第 {retry_count} 次重试 | asset_id={info.asset_id} | trace_id={trace_id}"
                )
                await asyncio.sleep(2)
                continue

            return result

    try:
        sprite_result = await _try_gen_sprite(max_retry=1)
    except Exception as exc:
        logger.exception("sprite generation exception for asset_id=%s", info.asset_id)
        return {
            "success": False,
            "message": f"generation exception: {exc}",
            "asset_id": info.asset_id
        }

    # 处理生成失败的情况
    if not sprite_result.get("success", False):
        return {
            "success": False,
            "message": sprite_result.get("message", "generate sprite failed"),
            "asset_id": info.asset_id
        }

    # 提取精灵图JSON URL
    sprite_json_url = sprite_result.get("data", {}).get("data", {}).get("sprite_json_url")
    if not sprite_json_url:
        return {
            "success": False,
            "message": "generate sprite response missing sprite_json_url",
            "asset_id": info.asset_id
        }

    # 转换数据URL
    sprite_data = {"image_url": sprite_json_url}
    await transform_data_url(sprite_data)
    sprite_json_url_public = sprite_data.get("image_url" + PUBLIC_FIX) or sprite_json_url

    # 返回成功结果
    return {
        "success": True,
        "asset_id": info.asset_id,
        "prompt": info.prompt,
        "image_url": sprite_json_url,
        "image_url_public": sprite_json_url_public,
    }

async def _update_generated_property(asset_id, prompt, image_url, image_url_public, canvas_id,
                                     object_type,return_public_url: bool = False) -> Dict[str, Any]:
    try:
        unique_asset_id = await get_unique_name(normalize_string(asset_id), canvas_id)
        property_list = await get_property_list(canvas_id)
    except Exception as e:
        return {"success": False, "message": str(e)}
    property_list.append({
        "property_id": unique_asset_id,
        "prompt": prompt,
        "object_type": object_type,
        "data": {
            "image_url": image_url,
            "image_url_public": image_url_public,
        }
    })
    save_result = await save_property(property_list, canvas_id)
    if not save_result.get("success", True):
        return {"success": False, "message": save_result.get("message")}
    await report_asset(canvas_id, unique_asset_id, image_url_public, image_url_public, asset_type_generate,
                       {"object_type":object_type})
    if return_public_url:
        # ThreeJS环境：返回public_url
        return {
            "success": True,
            "public_url": image_url_public,
        }
    else:
        # Unity环境：返回asset_id
        return {
            "success": True,
            "asset_id": unique_asset_id,
            # "data": {"image": image_url}
        }


async def _bulk_update_generated_properties(items: List[Dict[str, Any]],
                                            canvas_id: str,object_type:str,) -> Dict[str, Any]:
    if not items:
        return {"success": False, "message": "no generated items to update"}

    try:
        property_list = await get_property_list(canvas_id)
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    created_docs: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    for item in items:
        requested_asset_id = item.get("asset_id") or item.get("prompt") or "image"
        prompt = item.get("prompt", "")
        image_url = item.get("image_url")
        image_url_public = item.get("image_url_public") or image_url

        unique_asset_id = await get_unique_name(
            normalize_string(requested_asset_id),
            canvas_id,
            property_list,
        )
        property_doc = {
            "property_id": unique_asset_id,
            "prompt": prompt,
            "object_type": object_type,
            "data": {
                "image_url": image_url,
                "image_url_public": image_url_public,
            }
        }
        property_list.append(property_doc)
        created_docs.append(property_doc)
        if config.run_platform == RUN_PLATFORM_3JS:
            # ThreeJS环境：返回public_url
            results.append({
                "requested_asset_id": requested_asset_id,
                "public_url": image_url_public,
            })
        else:
            # Unity环境：返回asset_id
            results.append({
                "requested_asset_id": requested_asset_id,
                "asset_id": unique_asset_id,
            })

    save_result = await save_property(property_list, canvas_id)
    if not save_result.get("success", True):
        return {"success": False, "message": save_result.get("message"), "data": results}

    report_tasks = []
    for doc in created_docs:
        data = doc.get("data", {}) or {}
        public_url = data.get("image_url_public") or ""
        report_tasks.append(
            report_asset(
                canvas_id,
                doc.get("property_id") or "",
                public_url,
                public_url,
                asset_type_generate,
                {"object_type": "image"},
            )
        )
    if report_tasks:
        await asyncio.gather(*report_tasks, return_exceptions=True)
    return {"success": True, "results": results}




async def _gen_image_iml(prompt: str,
                         canvas_id: str,
                         edit_asset_id: Optional[str] = None,
                         trace_id: str = "",
                         image_aspect_ratio: Optional[str] = None,
                         image_size: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip():
        return {"success": False, "message": "prompt must be a non-empty string"}

    gemini_url = (
        f"{config.syn_base_url}"
        f"/gateway/api/gemini_image/generate"
        f"?abs_cuda_proxy_service_name=imagegen&abs_cuda_proxy_func_name=gemini_image_gen"
    )

    payload: Dict[str, Any] = {
        "image_urls": []
    }
    if image_aspect_ratio:
        payload["image_aspect_ratio"] = image_aspect_ratio
    if image_size:
        payload["image_size"] = image_size
    if edit_asset_id:
        url = gemini_url
        image_find_result = await get_image_url_by_asset_id(edit_asset_id, canvas_id)
        if not image_find_result.get("success", False):
            return image_find_result
        payload["image_urls"] = [image_find_result.get("image_url")]
    else:
        url = gemini_url

    payload["prompt"] = "Create an picture based on this description: " + prompt

    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
        "x-canvas-id": canvas_id,
        "x-seele-canvas-trace-id": trace_id
    }
    try:
        timeout = aiohttp.ClientTimeout(total=200)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                status = resp.status
                body_json: Any = None
                body_text: Optional[str] = None
                try:
                    body_json = await resp.json(loads=orjson.loads)
                except Exception:
                    try:
                        body_text = await resp.text()
                    except Exception:
                        body_text = None
                ok = 200 <= status < 300
                if not ok or body_json is None or body_json.get("code") != 0:
                    logger.warning(f"image request failed {status}: {body_json or body_text}")
                    return {
                        "success": False,
                        "status": status,
                        "message": f"HTTP {status}: {body_json if body_json is not None else body_text}",
                    }
                return {"success": True, "status": status,
                        "data": body_json if body_json is not None else {"text": body_text}}
    except Exception as e:
        logger.exception("image request exception")
        return {"success": False, "message": f"request failed: {e}"}

# 视频精灵图生成实现
async def _gen_sprite_iml(
        prompt: str,
        duration: int,
        canvas_id: str,
        trace_id: str = "",
        first_frame_url: Optional[str] = None,
        last_frame_url: Optional[str] = None,
        task_name: Optional[str] = None,
        fps: Optional[int] = 8,
        image_max_size: Optional[int] = 256,
) -> Dict[str, Any]:

    # 1. 参数校验
    if not isinstance(prompt, str) or not prompt.strip():
        return {"success": False, "code": -1, "message": "prompt must be a non-empty string"}
    if not isinstance(duration, int) or duration <= 0:
        return {"success": False, "code": -1, "message": "duration must be a positive integer"}

    video_sprite_url = (
        f"{config.syn_base_url}"
        f"/gateway/api/video_sprite"
        f"?abs_cuda_proxy_service_name=imagegen&abs_cuda_proxy_func_name=video_sprite"
    )

    payload: Dict[str, Any] = {
        "prompt": prompt,
        "duration": duration,
        "fps": fps,
        "image_max_size": image_max_size,
    }

    if first_frame_url:
        payload["first_frame_url"] = first_frame_url
    if last_frame_url:
        payload["last_frame_url"] = last_frame_url

    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
        "x-canvas-id": canvas_id,
        "x-seele-canvas-trace-id": trace_id
    }

    try:
        timeout = aiohttp.ClientTimeout(total=300)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(video_sprite_url, json=payload, headers=headers) as resp:
                status = resp.status
                body_json = None
                body_text = None

                try:
                    body_json = await resp.json(loads=orjson.loads)
                except Exception:
                    body_text = await resp.text()

                # ====== 失败判断 ======
                if status < 200 or status >= 300 or not isinstance(body_json, dict) or body_json.get("code") != 0:
                    logger.warning(f"video sprite request failed {status}: {body_json or body_text}")

                    return {
                        "success": False,
                        "status": status,
                        "code": body_json.get("code") if isinstance(body_json, dict) else None,
                        "message": body_json.get("message") if isinstance(body_json, dict)
                                   else f"HTTP {status}: {body_text}",
                        "data": body_json or {"text": body_text},
                    }

                return {
                    "success": True,
                    "status": status,
                    "data": body_json
                }

    except Exception as e:
        logger.exception("video sprite request exception")
        return {
            "success": False,
            "code": -500,
            "message": f"request exception: {e}"
        }


async def main(prompt: str, asset_id: str, edit_asset_id: Optional[str] = None) -> Dict[str, Any]:
    gen_result = await _gen_image_iml(prompt, config.test_canvas_id, edit_asset_id)
    if not gen_result.get("success", False):
        return gen_result
    image_url = gen_result.get("data", {}).get("data", {}).get("image_url", "")
    if not image_url:
        return gen_result
    return await _update_generated_property(asset_id, prompt, image_url, image_url, config.test_canvas_id,object_type="image")


if __name__ == "__main__":
    print(asyncio.run(main("苹果", "apple", "")))