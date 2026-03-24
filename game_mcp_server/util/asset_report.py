import asyncio
import logging
from typing import Any, Mapping, MutableMapping, Optional, Dict, List

import aiohttp
import orjson

from config import config
from util.asset_util import PUBLIC_FIX

logger = logging.getLogger(__name__)

asset_type_generate = "generate"
asset_type_retrieve = "retrieve"

_ALLOWED_ASSET_TYPES = {asset_type_generate, asset_type_retrieve}


async def report_generated_asset(canvas_id: str, property_doc: Dict[str, Any]):
    asset_id = property_doc.get("property_id", "")
    data = property_doc.get("data", {})
    model_url = data.get("model_url" + PUBLIC_FIX, "")
    image_url = (data or {}).get("front_view_url" + PUBLIC_FIX, "")
    metadata = {
        "object_type": property_doc.get("object_type", ""),
    }
    await report_asset(canvas_id, asset_id, image_url, model_url, asset_type_generate, metadata)


async def report_search_asset(
        canvas_id: str,
        search_result: Dict[str, Any],
) -> None:
    property_id = search_result.get("property_id", "")
    data = search_result.get("data", {})
    image_url = data.get("front_view_url", "")
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
        url = ""
    metadata = {
        "object_type": search_result.get("object_type", ""),
    }
    await report_asset(canvas_id, property_id, image_url, url, asset_type_retrieve, metadata, enable=False)


async def report_search_assets(
        canvas_id: str,
        search_results: List[Dict[str, Any]],
) -> None:
    if not search_results:
        return
    tasks = [
        report_search_asset(canvas_id, item)
        for item in search_results
        if isinstance(item, dict)
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def report_asset(
        canvas_id: str,
        assets_id: str,
        image_url: str,
        assets_url: str,
        asset_type: str,
        metadata: Optional[Mapping[str, Any]] = None,
        enable: bool = True
) -> Optional[MutableMapping[str, Any]]:
    """
    Report asset information to Seele backend.

    Args:
        canvas_id: Canvas identifier.
        assets_id: Unique asset id inside the canvas.
        image_url: CDN url that points to preview image.
        assets_url: CDN url for the asset itself.
        asset_type: Asset source marker, allowed values: "generate" or "retrieve".
        metadata: Optional extended metadata map.
        enable: download enable

    Returns:
        Response data on success, otherwise None.
    """
    try:
        if asset_type not in _ALLOWED_ASSET_TYPES:
            logger.warning("report_asset receive invalid type %s", asset_type)
            return None

        meta_payload: Mapping[str, Any] = metadata or {}
        if not isinstance(meta_payload, Mapping):
            logger.warning("report_asset metadata must be mapping, got %s", type(metadata))
            return None

        url = f"{config.app_base_url}/app/innerapi/tool/assets/synchronize"
        headers = {
            "token": "seele_koko_pwd",
            "Content-Type": "application/json",
            "x-canvas-id": canvas_id,
        }
        payload = {
            "canvasId": canvas_id,
            "assetsId": assets_id,
            "imageUrl": image_url,
            "assetsUrl": assets_url,
            "type": asset_type,
            "metadata": dict(meta_payload),
            "enable": enable,
        }

        logger.info(f"report asset {payload}")
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                ok = 200 <= resp.status < 300
                try:
                    body = await resp.json(loads=orjson.loads)
                except Exception:
                    text = await resp.text()
                    logger.warning("report_asset failed to parse response %s: %s", resp.status, text)
                    return None
                if not ok:
                    logger.warning("report_asset request failed %s: %s", resp.status, body)
                    return None
                logger.info(f"report asset finish {body}")
                return body
    except Exception as exc:
        logger.exception("report_asset unexpected error: %s", exc)
        return None
