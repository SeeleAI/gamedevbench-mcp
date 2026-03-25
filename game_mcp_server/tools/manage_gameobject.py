from typing import Dict, Any, List

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry


def register_manage_gameobject_tools(mcp: FastMCP):
    """Register all GameObject management tools with the MCP server."""

    @mcp.tool(description="""Tool for managing GameObjects and their components.

        Features:
        1. GameObject Operations: Create, modify, delete, and find GameObjects
        2. Component Operations: Add and remove components on GameObjects, and retrieve detailed component information

        IMPORTANT COMPILATION DEPENDENCIES:
        - add_component: Requires Unity compilation to be complete (not currently compiling).
        - If Unity is compiling or has compilation errors, these operations will fail with clear error messages.
        - Use manage_editor(action='get_state') to check compilation status before component operations.

        CANVAS UI SAFETY:
        - EventSystem is auto-created if missing.

        Args:
            action: Operation (e.g., 'create', 'modify', 'delete', 'find', 'add_component', 'remove_component', 'get_components').
            task_name: {{task_name_prompt}}
            target: GameObject identifier (name or path string) for modify/delete/component actions.
            search_method: How to find objects ('by_name', 'by_id', 'by_path', etc.). Used with 'find' and some 'target' lookups.
            name: GameObject name - used for both 'create' (initial name) and 'modify' (rename).
            tag: Tag name - used for both 'create' (initial tag) and 'modify' (change tag).
            parent: Parent GameObject reference - used for both 'create' (specifies which GameObject the newly created object will be parented under) and 'modify' (changes the parent of the target GameObject).
            layer: Layer name - used for both 'create' (initial layer) and 'modify' (change layer).
            component_properties: Dict mapping Component names to their properties to set.
                                  Example: {"Rigidbody": {"mass": 10.0, "useGravity": True}},
                                  Unity Rigidbody notes:
                                  1. Inspect the current Rigidbody before editing: mass, drag, constraints or freezeRotation, centerOfMass, collider size, collisionDetectionMode.
                                  2. Match your control method to those settings. Use AddForce with ForceMode.Force or Impulse on constrained axes, and reserve Acceleration or VelocityChange for axes that are completely free with finite inertia. Move helpers (MovePosition or MoveRotation) are valid alternatives when constraints block acceleration modes.
                                  3. Steering strategy:
                                     a. Prefer angular-velocity steering: set or lerp Rigidbody.angularVelocity toward the target yaw rate, keep a positive minimum so low-speed input still works, and do not add torque or edit lateral velocity elsewhere.
                                     b. Alternatively use transform-based steering: interpolate transform.rotation or use Rigidbody.MoveRotation toward the target heading without layering extra yaw forces.
                                     c. Use torque steering (AddTorque with ForceMode.Force/Impulse) only when you explicitly want physical yaw torque; if you choose it, compute torque ≈ inertia * desiredAngularAcceleration, keep it bounded, and make lateral corrections mild (damping-like) instead of instantly cancelling yaw.
                                  4. Always read the Rigidbody first and adapt magnitudes to that context. Size any propulsion force against friction (μ * mass * g), and remember ForceMode.Force / Impulse already multiply by Time.fixedDeltaTime—never multiply by delta time manually.
                                  5. After edits confirm collider thickness and collision detection still support the expected speeds so objects cannot tunnel, and ensure only one steering method remains active.
                                  isKinematic disables physics simulation for the object.
                                  To set references:
                                  - Use asset path string for Prefabs/Materials, e.g., {"MeshRenderer": {"material": "Assets/Materials/MyMat.mat"}}
                                  - Use a dict for scene objects/components, e.g.:
                                    {"MyScript": {"otherObject": {"find": "Player", "method": "by_name"}}} (assigns GameObject)
                                    {"MyScript": {"playerHealth": {"find": "Player", "component": "HealthComponent"}}} (assigns Component)
                                  Example set nested property:
                                  - Access shared material: {"MeshRenderer": {"sharedMaterial.color": [1, 0, 0, 1]}}
            components_to_add: List of component names to add.
            primitive_type: For 'create' action, specifies the type of primitive to create.
                           Valid values: 'Sphere', 'Capsule', 'Cylinder', 'Cube', 'Plane', 'Quad'.
                           Note: For UI elements like Canvas, Button, Text, Image, or other components
                           like Light, Camera, AudioSource, use components_to_add instead.
            Action-specific arguments (e.g., position, rotation, scale for create/modify;
                     component_name for component actions;
                     search_term, find_all for 'find').
            includeNonPublicSerialized: If True, includes private fields marked [SerializeField] in component data.

            Action-specific details:
            - For 'get_components':
                Required: target, search_method
                Optional: includeNonPublicSerialized (defaults to True)
                Returns all components on the target GameObject with their serialized data.
                The search_method parameter determines how to find the target ('by_name', 'by_id', 'by_path').

        Returns:
            Dictionary with operation results ('success', 'message', 'data').
            For 'get_components', the 'data' field contains a dictionary of component names and their serialized properties.
        """)
    async def manage_gameobject(
        ctx: Context,
        action: str,
        task_name: str = None,
        target: str = None,  # GameObject identifier by name or path
        search_method: str = None,
        # --- Combined Parameters for Create/Modify ---
        name: str = None,  # Used for both 'create' (new object name) and 'modify' (rename)
        tag: str = None,  # Used for both 'create' (initial tag) and 'modify' (change tag)
        parent: str = None,  # Used for both 'create' (initial parent) and 'modify' (change parent)
        position: List[float] = None,
        rotation: List[float] = None,
        scale: List[float] = None,
        components_to_add: List[str] = None,  # List of component names to add
        primitive_type: str = None,
        save_as_prefab: bool = False,
        prefab_path: str = None,
        prefab_folder: str = "Assets/Prefabs",
        # --- Parameters for 'modify' ---
        set_active: bool = None,
        layer: str = None,  # Layer name
        components_to_remove: List[str] = None,
        component_properties: Dict[str, Dict[str, Any]] = None,
        # --- Parameters for 'find' ---
        search_term: str = None,
        find_all: bool = False,
        search_in_children: bool = False,
        # -- Component Management Arguments --
        component_name: str = None,
        includeNonPublicSerialized: bool = None, # Controls serialization of private [SerializeField] fields
    ) -> Dict[str, Any]:
        
        try:
            # --- Early check for attempting to modify a prefab asset ---
            # ----------------------------------------------------------

            # Prepare parameters, removing None values
            params = {
                "action": action,
                "target": target,
                "searchMethod": search_method,
                "name": name,
                "tag": tag,
                "parent": parent,
                "position": position,
                "rotation": rotation,
                "scale": scale,
                "componentsToAdd": components_to_add,
                "primitiveType": primitive_type,
                "saveAsPrefab": save_as_prefab,
                "prefabPath": prefab_path,
                "prefabFolder": prefab_folder,
                "setActive": set_active,
                "layer": layer,
                "componentsToRemove": components_to_remove,
                "componentProperties": component_properties,
                "searchTerm": search_term,
                "findAll": find_all,
                "searchInChildren": search_in_children,
                "searchInactive": True,
                "componentName": component_name,
                "includeNonPublicSerialized": includeNonPublicSerialized
            }
            params = {k: v for k, v in params.items() if v is not None}
            
            # --- Handle Prefab Path Logic ---
            if action == "create" and params.get("saveAsPrefab"): # Check if 'saveAsPrefab' is explicitly True in params
                if "prefabPath" not in params:
                    if "name" not in params or not params["name"]:
                        return {"success": False, "message": "Cannot create default prefab path: 'name' parameter is missing."}
                    # Use the provided prefab_folder (which has a default) and the name to construct the path
                    constructed_path = f"{prefab_folder}/{params['name']}.prefab"
                    # Ensure clean path separators (Unity prefers '/')
                    params["prefabPath"] = constructed_path.replace("\\", "/")
                elif not params["prefabPath"].lower().endswith(".prefab"):
                    return {"success": False, "message": f"Invalid prefab_path: '{params['prefabPath']}' must end with .prefab"}
            # Ensure prefab_folder itself isn't sent if prefabPath was constructed or provided
            # The C# side only needs the final prefabPath
            params.pop("prefab_folder", None) 
            # --------------------------------
            
            # Use centralized retry helper
            response = await async_send_command_with_retry(ctx, "manage_gameobject", params)

            # Check if the response indicates success
            # If the response is not successful, raise an exception with the error message
            if isinstance(response, dict) and response.get("success"):
                return {"success": True, "message": response.get("message", "GameObject operation successful."), "data": response.get("data")}
            return response if isinstance(response, dict) else {"success": False, "message": str(response)}

        except Exception as e:
            return {"success": False, "message": f"Python error managing GameObject: {str(e)}"} 