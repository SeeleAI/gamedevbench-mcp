import asyncio
from typing import Optional, Dict, Any, List
from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from config import config
from util.asset_util import transform_data_url, PUBLIC_FIX
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id

# 导入完全相同的通用函数
from ..manage_image import GenerateImageInfo, generate_image_iml, GenerateSpriteInfo, generate_sprite_iml
import logging

logger = logging.getLogger(__name__)

ERROR_INSUFFICIENT_GPU_MEMORY = -20002


def register_manage_image_tools(mcp: FastMCP, enable_generate_image: bool = True) -> None:
    if not enable_generate_image:
        return

    @mcp.tool(description="""Generate or edit images for game development via gateway service. Supports creating 2D sprites, UI elements, textures, icons, backgrounds and other game assets.

        Use this tool when the task needs visual assets that can be imported into the current
        game project, including Godot scenes, UI, item icons, textures, decals, and concept images.

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
                remove_background: When True, runs an additional background removal pass on the generated image before saving.
        
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

    @mcp.tool(description="""Generate or edit 2D sprite sheets for game development via gateway service. Supports creating frame-based loopable sprite animations for characters, visual effects, props, UI animations and other 2D game assets, with background-removed sprite sheet and accompanying JSON metadata generated automatically.
   
        Args:
            sprite_info: Batch description list. Each item contains:
                prompt: Text describing the 2D sprite animation's visual style, motion behavior and intended in-game usage. Examples:
                - "Looping fireball effect, 2D pixel game style, glowing orange flames, smooth seamless loop, 8-bit color palette"
                - "2D cartoon character side walking animation, consistent proportions, natural limb movement, clean loop transition"
                asset_id: Unique identifier for the generated sprite sheet asset
                task_name: {{task_name_prompt}}
                duration: Integer length of the sprite animation in seconds (1-3 inclusive), controls total animation cycle length
                first_frame_url: Required reference image URL for the animation's starting frame, enforces pose/silhouette/composition consistency
                last_frame_url: Optional reference image URL for the animation's ending frame, optimizes loop transition smoothness (defaults to None)
                fps: Frames per second of the sprite animation (defaults to 10), controls smoothness and total frame count
            task_name: {{task_name_prompt}}
        Returns:
            - success: bool True if all requested sprite sheets are generated and saved, False if all fail
            - results: list of generated sprite sheet asset details (requested_asset_id/asset_id/public_url)
            - errors: list of failed items with asset_id and error message when partial success occurs
            - message: prompt text for success/partial success/failure status
            """)
    async def generate_sprite(
            ctx: Context,
            sprite_info: List[GenerateSpriteInfo],
            task_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await generate_sprite_iml(ctx, sprite_info, task_name)
