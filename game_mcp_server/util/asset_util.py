import asyncio
import logging
import re
from typing import Optional, List
from util.s3_util import S3Client, PUBLIC_BUCKET
import aiohttp
import orjson

from config import config

logger = logging.getLogger(__name__)
PUBLIC_FIX = "_public"


async def get_canvas_config(canvas_id: str, retry_time: int = 1):
    url = f"{config.app_base_url}/app/innerapi/tool/canvasConfig"
    logger.info(f"url:{url}")
    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
    }
    inputs = {
        "canvasId": canvas_id,
    }

    async def retry(fail_message: str):
        if retry_time > 0:
            logger.info(f"get canvas config fail:{fail_message} will retry")
            await asyncio.sleep(0.5)
            return await get_canvas_config(canvas_id, retry_time - 1)
        logger.info(f"get canvas config fail:{fail_message}")
        return {"success": False, "message": fail_message}

    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=inputs, headers=headers) as resp:
                ok = 200 <= resp.status < 300
                try:
                    body = await resp.json(loads=orjson.loads)
                except Exception:
                    text = await resp.text()
                    return await retry(f"HTTP {resp.status}: {text}")
                if not ok:
                    return await retry(f"HTTP {resp.status}: {body}")
                data = body.get("data", {}) if isinstance(body, dict) else {}
                return {"success": True, "data": data}
    except Exception as e:
        return await retry(f"request failed: {e}")


async def get_property_list(canvas_id: str):
    canvas_config = await get_canvas_config(canvas_id)
    if not canvas_config.get("success"):
        raise Exception(f"request config fail:{canvas_config.get('message')}")
    property_list = canvas_config.get("data", {}).get("property", [])
    return property_list


async def get_target_property(canvas_id: str, property_id: str):
    property_list = await get_property_list(canvas_id)
    return get_target_property_from_list(property_id, property_list)


def get_target_property_from_list(property_id: str, property_list: List[dict]):
    for item in property_list:
        if item.get("property_id") == property_id:
            return item
    return None


def normalize_string(value: str, max_length: Optional[int] = None) -> str:
    """
    Normalize a string so the result contains only lowercase letters, digits, and underscores.
    - Lowercases input
    - Replaces any non [a-z0-9_] characters with '_'
    - Collapses repeated underscores and trims leading/trailing underscores
    - If max_length is provided (>0), result is truncated to that length
    """
    if not isinstance(value, str):
        value = str(value)
    s = value.lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if max_length and max_length > 0:
        s = s[:max_length]
    return s


async def get_unique_name(tag: str, canvas_id: str, property_list: List | None = None) -> str:
    """基于批量方法生成单个唯一ID，复用相同逻辑。"""
    names = await get_unique_names(tag, canvas_id, 1, property_list)
    return names[0] if names else normalize_string(tag)


async def get_unique_names(tag: str, canvas_id: str, count: int, property_list: List | None = None) -> List[str]:
    """Generate multiple unique property_ids based on the given tag.

    Only reads the canvas property list once to avoid repeated config/network reads.
    """
    if count <= 0:
        return []

    if property_list is None:
        property_list = await get_property_list(canvas_id)
    existing_ids: List[str] = []
    if isinstance(property_list, list):
        for property_item in property_list:
            pid = property_item.get("property_id")
            if isinstance(pid, str):
                existing_ids.append(pid)

    base_tag = normalize_string(tag)
    results: List[str] = []
    ext_number = 0
    while len(results) < count:
        candidate = base_tag if ext_number == 0 else f"{base_tag}_{ext_number}"
        if candidate not in existing_ids and candidate not in results:
            results.append(candidate)
        ext_number += 1
    return results


async def update_property_item(canvas_id: str, property_item: dict):
    property_id = property_item["property_id"]
    if not property_id:
        raise Exception("property_id is None")
    try:
        property_list = await get_property_list(canvas_id)
    except Exception as e:
        return {"success": False, "message": f"request failed: {e}"}
    # Ensure list type
    if not isinstance(property_list, list):
        property_list = []

    updated = False
    for idx, item in enumerate(property_list):
        if item.get("property_id") == property_id:
            property_list[idx] = property_item
            updated = True
            break

    if not updated:
        property_list.append(property_item)

    return await save_property(property_list, canvas_id)


async def save_property(property_list, canvas_id: str):
    url = f"{config.app_base_url}/app/innerapi/tool/saveProperty"
    headers = {
        "token": "seele_koko_pwd",
        "Content-Type": "application/json",
        "x-canvas-id": canvas_id,
    }
    inputs = {
        "canvasId": canvas_id,
        "propertyList": property_list,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=inputs, headers=headers) as resp:
                ok = 200 <= resp.status < 300
                try:
                    body = await resp.json(loads=orjson.loads)
                except Exception:
                    text = await resp.text()
                    return {"success": False, "message": f"HTTP {resp.status}: {text}"}
                if not ok:
                    return {"success": False, "message": f"HTTP {resp.status}: {body}"}
                data = body.get("data", {}) if isinstance(body, dict) else {}
                return data
    except Exception as e:
        return {"success": False, "message": f"request failed: {e}"}


async def get_image_url_by_asset_id(asset_id: str, canvas_id: str):
    if asset_id.startswith("http") or asset_id.startswith("s3"):
        return {"success": True, "image_url": asset_id}
    else:
        image_info = await get_target_property(canvas_id, asset_id)
        if image_info is None:
            return {"success": False, "message": f"image_name:{asset_id} not found"}
        if image_info.get("object_type") != "image":
            return {"success": False,
                    "message": f"image_name:{asset_id} not an image, it is a {image_info['object_type']}"}
        image_url = image_info.get("data", {}).get("image_url")
        return {"success": True, "image_url": image_url}


async def transform_data_url(data: dict):
    s3_client = S3Client()
    need_transform_keys = []
    for k, v in data.items():
        if k.endswith("url") and isinstance(v, str):
            if (k + PUBLIC_FIX) in data:
                continue
            need_transform_keys.append(k)
    for k in need_transform_keys:
        url = data.get(k)
        if not url:
            continue
        if url.startswith("s3:"):
            public_url = await asyncio.to_thread(s3_client.move_and_get_accessible_url, url, PUBLIC_BUCKET, "assets")
            data[k + PUBLIC_FIX] = public_url
        else:
            data[k + PUBLIC_FIX] = url
    return data


if __name__ == "__main__":
    # print(get_canvas_config("57b6ddf8-d476-4201-99a9-76e373b0d712"))
    # print(asyncio.run(
    #     get_target_property("28728117-0da6-43db-bdd5-68096ab74cfd", "human_character_01")))
    print(asyncio.run(
        get_target_property("5a9c8c09-5120-4efd-9a51-0e2ad33cce45", "bullet_asset")))
