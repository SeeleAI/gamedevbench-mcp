"""Sprite player SDK integration guidance tool for MCP."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from remote_config.schemas.sprite_player_sdk_usage_config import SpritePlayerSdkUsageConfig

logger = logging.getLogger(__name__)

# 默认的精灵图播放器 SDK 使用方法文本
DEFAULT_SPRITE_PLAYER_SDK_TEXT = """Sprite Animation SDK:
a) Import Setup:
   <script type='importmap'>
   { "imports": { "SpriteAnimation": "https://static.seeles.ai/games-sdk/sprite-player.js" } }
   </script>
   import { SpriteStage, SpritePlayer } from 'SpriteAnimation';

b) Core API:
   const stage = new SpriteStage(ctx)           // ctx: CanvasRenderingContext2D
   const player = new SpritePlayer()            // Create sprite entity
   await player.loadSprite(name, configUrl)     // MUST await
   player.playAnimation(name)                   // Switch animation
   player.setPosition(x, y)                     // Set position
   player.setSize(w, h)                         // Set size
   player.setSpeedScale(1.0)                    // default 1.0  (optional)

c) Lifecycle & Rendering:
   stage.add(player)                            // Start tracking
   stage.remove(player)                         // Stop tracking

   // In your game loop:
   function gameLoop() {
     // ... your game rendering code ...

     stage.render();                            // Render all tracked entities
     requestAnimationFrame(gameLoop);
   }
   gameLoop();"""


def _get_sprite_player_sdk_text() -> str:
    """Get sprite player SDK usage text from Nacos config, fallback to default."""
    try:
        config = SpritePlayerSdkUsageConfig.current()
        if config and config.text and config.text.strip():
            return config.text
    except Exception as e:
        logger.warning(f"Failed to get SpritePlayerSdkUsageConfig from Nacos, using default: {e}")
    return DEFAULT_SPRITE_PLAYER_SDK_TEXT


def register_sprite_player_tool(mcp: FastMCP):
    """Register the sprite_player tool with the MCP server."""
    
    @mcp.tool(description="""
        Analyze a game task and return guidance for integrating 2D sprite sheet animations
        using the Sprite Animation SDK.
        
        Args:
            task_name: {{task_name_prompt}}, required
            
            analysis_text: Your analysis of sprite integration.
                          Consider:
                          - What sprites/animations are needed? (e.g., player: idle/walk/jump)
                          - When to load sprites? (init or lazy load)
                          - When to switch animations? (on input, state change)
                          - Where to update or render sprite playback in the game loop

                          Example:
                          "Sprites: player (idle, walk, jump), enemy (patrol, attack).
                          Load all in init. Switch on keyboard input. Render in main loop after background."
                          required
        
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": str  # SDK integration rules and usage instructions
            }
        """)
    async def sprite_player(
        ctx: Context,
        task_name: str,
        analysis_text: str
    ) -> Dict[str, Any]:
        try:
            # Validate task_name
            if not task_name or not task_name.strip():
                return {
                    "success": False,
                    "message": "Task name parameter is required and cannot be empty",
                    "data": {"error_type": "missing_parameter", "parameter": "task_name"}
                }
            
            # Validate analysis_text
            if not analysis_text or not analysis_text.strip():
                return {
                    "success": False,
                    "message": "Analysis text parameter is required and cannot be empty",
                    "data": {"error_type": "missing_parameter", "parameter": "analysis_text"}
                }
            
            # Get SDK usage text
            sdk_usage_text = _get_sprite_player_sdk_text()
            
            # Return the SDK usage text in the required format
            result_data = f"These are the rules for SDK integration: {sdk_usage_text}"
            
            logger.info(f"Sprite player SDK integration analysis completed for task: {task_name}")
            return {
                "success": True,
                "message": "Sprite player SDK integration analysis completed successfully",
                "data": result_data
            }
            
        except Exception as e:
            logger.error(f"Error in sprite_player: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Python error: {str(e)}",
                "data": None
            }
