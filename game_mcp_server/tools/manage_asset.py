"""
Defines the manage_asset tool for interacting with Unity assets.
"""
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry


def register_manage_asset_tools(mcp: FastMCP):
    """Registers the manage_asset tool with the MCP server."""

    @mcp.tool(description="""Performs asset operations (reimport, create, modify, delete, etc.) in Unity.

        Args:
            action: Operation to perform (e.g., 'reimport', 'create', 'modify', 'delete', 'duplicate', 'move', 'rename', 'search', 'get_info', 'create_folder', 'get_components').
            path: Asset path (e.g., "Materials/MyMaterial.mat") or search scope.
            task_name: {{task_name_prompt}}
            asset_type: Asset type (e.g., 'Material', 'Folder') - required for 'create'.
            properties: Dictionary of properties for 'create'/'modify'.
                MATERIAL PROPERTIES BY RENDERING PIPELINE:
                - Built-in Pipeline: {"_Color": [1, 0, 0, 1], "_MainTex": "texture_path", "shader": "Standard"}
                - URP Pipeline: {"_BaseColor": [1, 0, 0, 1], "_BaseMap": "texture_path", "shader": "Universal Render Pipeline/Lit"}
                - HDRP Pipeline: {"_BaseColor": [1, 0, 0, 1], "_BaseColorMap": "texture_path", "shader": "HDRP/Lit"}
                COMMON MATERIAL PROPERTIES:
                - Color: "_Color" (Built-in), "_BaseColor" (URP/HDRP)
                - Main Texture: "_MainTex" (Built-in), "_BaseMap" (URP), "_BaseColorMap" (HDRP)
                - Metallic: "_Metallic" (all pipelines)
                - Smoothness: "_Glossiness" (Built-in), "_Smoothness" (URP/HDRP)
                - Normal Map: "_BumpMap" (Built-in), "_BumpMap" (URP), "_NormalMap" (HDRP)
                ANIMATORCONTROLLER PROPERTIES (step-wise operations, one per call):
                - add_parameter: {"name": "Speed", "type": "Float", "defaultValue": 0} (types: Float, Int, Bool, Trigger)
                - remove_parameter: {"name": "Speed"}
                - add_state: {"name": "Walking", "motion": "Assets/animations/walk.anim", "layer": "Base Layer"}
                - remove_state: {"name": "Walking", "layer": 0}
                - set_default_state: {"name": "Walking", "layer": "Base Layer"}
                - add_transition: {"from": "Idle", "to": "Walking", "parameter": "Speed", "condition": "Greater", "threshold": 0.1, "duration": 0.25}
                - add_layer: {"name": "Upper Body", "weight": 0.5, "blendingMode": "Additive"}
                example properties for Texture: {"width": 1024, "height": 1024, "format": "RGBA32"}.
                example properties for PhysicsMaterial: {"bounciness": 1.0, "staticFriction": 0.5, "dynamicFriction": 0.5}.
            destination: Target path for 'duplicate'/'move'.
            search_pattern: Asset name.
            filter_*: Filters for search (type, date).
            page_*: Pagination for search.

        Returns:
            Dictionary with operation results ('success', 'data', 'error').
        """)
    async def manage_asset(
        ctx: Context,
        action: str,
        path: str = None,
        task_name: str = None,
        asset_type: str = None,
        properties: Dict[str, Any] = None,
        destination: str = None,
        generate_preview: bool = False,
        search_pattern: str = None,
        filter_type: str = None,
            filter_date_after: str = None,
            page_size: int = None,
            page_number: int = None
        ) -> Dict[str, Any]:
        
        # Ensure properties is a dict if None
        if properties is None:
            properties = {}
            
        # Prepare parameters for the C# handler
        params_dict = {
            "action": action.lower(),
            "path": path,
            "assetType": asset_type,
            "properties": properties,
            "destination": destination,
            "generatePreview": generate_preview,
            "searchPattern": search_pattern,
            "filterType": filter_type,
            "filterDateAfter": filter_date_after,
            "pageSize": page_size,
            "pageNumber": page_number
        }
        
        # Remove None values to avoid sending unnecessary nulls
        params_dict = {k: v for k, v in params_dict.items() if v is not None}
        # Use centralized async retry helper to avoid blocking the event loop
        result = await async_send_command_with_retry(ctx, "manage_asset", params_dict)
        # Return the result obtained from Unity
        return result if isinstance(result, dict) else {"success": False, "message": str(result)}
