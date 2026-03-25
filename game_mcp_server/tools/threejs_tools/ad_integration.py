"""Ad integration analysis tool for MCP game projects."""
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
from remote_config.schemas.ad_integration_sdk_usage_config import AdIntegrationSdkUsageConfig

logger = logging.getLogger(__name__)

# 默认的广告集成 SDK 使用方法文本
DEFAULT_AD_INTEGRATION_SDK_TEXT = """Game Ad Integration SDK:
a) Importmap Setup:
   <script type='importmap'>
   { "imports": { "ThreeGameAdSDK": "https://static.seeles.ai/games-sdk/threejs_ad_integration_sdk.js" } }
   </script>
   import ThreeGameAdSDK from 'ThreeGameAdSDK';
   const adSdk = new ThreeGameAdSDK();

b) Required API calls:
   **CRITICAL: await adSdk.showAd(type) MUST complete before continuing**
   const result = await adSdk.showAd(type);  // returns true if ad completed, false otherwise
   await adSdk.endAdSession('end');

   Ad types:
   - 'start': Game start/restart
   - 'pause': Player pauses
   - 'next': Between levels
   - 'reward': Rewarded actions (revive, unlock, booster, etc.)

   Example:
   const result = await adSdk.showAd('reward');
   if (result) giveExtraLife();

c) Session lifecycle:
   Start session: Game loads, restart/retry, next level, reward request, pause
   End session: Death/loss, win/complete, quit to menu, game over

   Restart pattern: await endAdSession('end'), then await showAd(type)"""


def _get_ad_integration_sdk_text() -> str:
    """Get ad integration SDK usage text from Nacos config, fallback to default."""
    try:
        config = AdIntegrationSdkUsageConfig.current()
        if config and config.text and config.text.strip():
            return config.text
    except Exception as e:
        logger.warning(f"Failed to get AdIntegrationSdkUsageConfig from Nacos, using default: {e}")
    return DEFAULT_AD_INTEGRATION_SDK_TEXT


def register_ad_integration_tool(mcp: FastMCP):
    """Register the ad_integration tool with the MCP server."""
    
    @mcp.tool(description="""
        Analyze the current game structure and identify appropriate points for ad integration.
        
        This tool helps you reason about game flow and returns ad SDK integration rules based on your analysis.
        Before calling this tool, you must decompose the game structure and analyze ad insertion points.
        Pass your analysis as the analysis_text parameter.
        
        Args:
            task_name: {{task_name_prompt}}, required
            
            analysis_text: Your detailed analysis of the game structure and ad integration logic.
                          You should construct this text by thinking about:
                          - Game structure decomposition: What are the core game mechanics? (e.g., initialization, game loop, game over, levels)
                          - Game flow: What are the key game states and transitions? (e.g., init → start → play → end → restart)
                          - Ad insertion points: When and where should ads be inserted?
                            * Game start/restart: When does the game actually begin or restart? (use type='start')
                            * Pause: When does the player pause the game? (use type='pause')
                            * Between levels: When transitioning between levels? (use type='next')
                            * Rewarded actions: When should rewarded ads be shown? (revive, unlock, booster, etc.) (use type='reward')
                          - Ad integration logic: How should ads be integrated? (e.g., call showAd() at appropriate points, handle result, call endAdSession() on game end)
                          - Reasoning: Why these points are suitable for ad insertion?
                          
                          Example structure:
                          "Game Structure:
                          - Game type: [game type]
                          - Core mechanics: [list mechanics]
                          - Game flow: [describe flow]
                          
                          Ad Integration Analysis:
                          - Ad insertion points: [when/where, which type to use]
                          - Integration logic: [how to integrate]
                          - Reasoning: [why]"
                          required
        
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": str  # SDK integration rules and usage instructions
            }
        """)
    async def ad_integration(
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
            sdk_usage_text = _get_ad_integration_sdk_text()
            
            # Return the SDK usage text in the required format
            result_data = f"These are the rules for SDK integration: {sdk_usage_text}"
            
            logger.info(f"Ad integration analysis completed for task: {task_name}")
            return {
                "success": True,
                "message": "Ad integration analysis completed successfully",
                "data": result_data
            }
            
        except Exception as e:
            logger.error(f"Error in ad_integration: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Python error: {str(e)}",
                "data": None
            }
