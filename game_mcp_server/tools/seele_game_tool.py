import logging
from typing import Dict, Any

import aiohttp
import orjson
from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from config import config
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id
from util.metrics import BUSINESS_CALLS, APP_LABEL_VALUE

logger = logging.getLogger(__name__)


def register_seele_game_tools(mcp: FastMCP) -> None:
    @mcp.tool(description="""Build and deliver the game for runtime preview after completing all development tasks.
    
    Call this ONLY when:
    - All user requirements have been implemented
    - The project needs to be built as a playable runtime (not just editor preview)
    - User needs to test gameplay, interactions, or runtime-specific features
    - User explicitly requests to play/test the game (e.g., "let me play", "I want to try it")    
    
    DO NOT call this for editor-only changes (e.g., simple asset placement, scene editing).
    
    Args:
        message: Inform user as Seele that their game has been generated and is preparing for preview.
                 Should convey: 
                 1) Requirements have been successfully generated
                 2) Game is being prepared for experience/testing  
                 3) Preparation takes about 1-2 minutes
                 Example: "I've successfully generated all the game content you requested! The game is now being prepared for you to play. This preparation process typically takes 1-2 minutes. Once ready, you can click the button below to start experiencing your game."
                 Note: Speak as Seele (multimodal game AI model), emphasize "generation" not technical implementation.
        game_title: A short, descriptive title for the generated game (e.g., "Space Adventure").
       
    Returns:
        - success: bool — True if build and delivery succeeded
        - message: str
        """)
    async def deliver_preview_game(ctx: Context,
                                   message: str, game_title: str = None ) -> Dict[str, Any]:

        canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id

        turn_id = trace_id.split("|")[1]
        url = f"{config.app_base_url}/app/innerapi/tool/unity-export"
        headers = {
            "token": "seele_koko_pwd",
            "x-canvas-id": canvas_id,
            "x-seele-canvas-trace-id": trace_id,
        }
        payload = {
            "canvasId": canvas_id,
            "turnId": turn_id,
            "message": message,
            "game_title": game_title,
        }

        status = "ok"
        try:
            timeout = aiohttp.ClientTimeout(total=900)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json(content_type=None, loads=orjson.loads)
                    logger.info(f"{trace_id} Delivering preview for {game_title} status: {resp.status} data:{data}")
                    if resp.status == 200:
                        result_data = data.get("data", {"success": False})
                        if not result_data.get("success"):
                            status = "error"
                            logger.warning(f"Deliver preview game failed: {data}")
                        return result_data
                    status = "error"
                    return {"success": False, "message": f"status: {resp.status} data:{data}"}
        except Exception as e:
            logger.info(f"{trace_id} Failed to deliver preview game: {e}")
            status = "error"
            return {"success": False, "message": str(e)}
        finally:
            BUSINESS_CALLS.labels(
                name="deliver_preview_game",
                status=status,
                application=APP_LABEL_VALUE
            ).inc()
