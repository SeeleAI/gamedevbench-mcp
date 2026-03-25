import base64
import os
from typing import Dict, Any
from urllib.parse import urlparse, unquote

from mcp.server.fastmcp import FastMCP, Context

from connection.connection_provider import async_send_command_with_retry


def register_manage_script_tools(mcp: FastMCP):
    """Register all script management tools with the MCP server."""

    def _split_uri(uri: str) -> tuple[str, str]:
        """Split an incoming URI or path into (name, directory) suitable for Unity.

        Rules:
        - unity://path/Assets/... → keep as Assets-relative (after decode/normalize)
        - file://... → percent-decode, normalize, strip host and leading slashes,
          then, if any 'Assets' segment exists, return path relative to that 'Assets' root.
          Otherwise, fall back to original name/dir behavior.
        - plain paths → decode/normalize separators; if they contain an 'Assets' segment,
          return relative to 'Assets'.
        """
        raw_path: str
        if uri.startswith("unity://path/"):
            raw_path = uri[len("unity://path/") :]
        elif uri.startswith("file://"):
            parsed = urlparse(uri)
            host = (parsed.netloc or "").strip()
            p = parsed.path or ""
            # UNC: file://server/share/... -> //server/share/...
            if host and host.lower() != "localhost":
                p = f"//{host}{p}"
            # Use percent-decoded path, preserving leading slashes
            raw_path = unquote(p)
        else:
            raw_path = uri

        # Percent-decode any residual encodings and normalize separators
        raw_path = unquote(raw_path).replace("\\", "/")
        # Strip leading slash only for Windows drive-letter forms like "/C:/..."
        if os.name == "nt" and len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]

        # Normalize path (collapse ../, ./)
        norm = os.path.normpath(raw_path).replace("\\", "/")

        # If an 'Assets' segment exists, compute path relative to it (case-insensitive)
        parts = [p for p in norm.split("/") if p not in ("", ".")]
        idx = next((i for i, seg in enumerate(parts) if seg.lower() == "assets"), None)
        assets_rel = "/".join(parts[idx:]) if idx is not None else None

        effective_path = assets_rel if assets_rel else norm
        # For POSIX absolute paths outside Assets, drop the leading '/'
        # to return a clean relative-like directory (e.g., '/tmp' -> 'tmp').
        if effective_path.startswith("/"):
            effective_path = effective_path[1:]

        name = os.path.splitext(os.path.basename(effective_path))[0]
        directory = os.path.dirname(effective_path)
        return name, directory

    @mcp.tool(description=(
        "Replace a C# script content by URI or Assets-relative path.\n\n"
        "PHYSICS RULES checklist:\n"
        "1. Read the Rigidbody first: mass, drag, constraints or freezeRotation, centerOfMass, collider dimensions, collision detection mode. Use the values you find.\n"
        "2. ForceMode.Force and ForceMode.Impulse divide by mass and already apply Time.fixedDeltaTime. Make sure the magnitude exceeds the friction baseline (mu * mass * g) and never multiply by delta time manually.\n"
        "3. ForceMode.Acceleration and ForceMode.VelocityChange ignore mass; use them only when the driven axis is unconstrained and the inertia tensor is finite. Otherwise fall back to Force / Impulse or to MovePosition / MoveRotation.\n"
        "4. Steering strategy:\n"
        "   a. Default: set or smoothly adjust Rigidbody.angularVelocity toward your target yaw rate so rotation is direct and predictable. Keep a non-zero minimum so low-speed steering stays responsive, and avoid adding torque or modifying lateral velocity elsewhere.\n"
        "   b. Optional: use Rigidbody.MoveRotation or transform rotation interpolation when you want transform-driven steering without physics torque.\n"
        "   c. Only select AddTorque when simulating real yaw torque is absolutely required. In that case compute torque ≈ inertia * target angular acceleration, clamp it to sensible limits, and treat any lateral correction as gentle damping—never apply large forces that instantly cancel the yaw.\n"
        "5. Align numbers with the scene. If the script assumes a heavy body, update the mass and colliders or choose mass-independent modes. Include drag, downforce, and collider thickness to avoid tunneling.\n"
        "6. After coding, double-check ForceMode choices vs constraints, confirm no extra delta time multipliers, verify low speed control, and ensure forces and torques scale sensibly with the observed mass and friction.\n\n"
        "Args: uri (Assets/Scripts/XX.cs,a complete path is required, and the path may have multiple layers),script_contents(C# script code content),task_name({{task_name_prompt}}).\n"
        "Rules: Target must resolve under Assets/.\n"
    ))
    async def edit_script(
        ctx: Context,
        uri: str,
        script_contents: str = "",
        task_name: str = None,
    ) -> Dict[str, Any]:
        """Create a new C# script at the given path."""
        name, directory = _split_uri(uri)
        if not directory or directory.split("/")[0].lower() != "assets":
            return {"success": False, "code": "path_outside_assets", "message": "URI must resolve under 'Assets/'."}
        params = {"action": "replace", "name": name, "path": directory}
        if script_contents:
            params["encodedContents"] = base64.b64encode(script_contents.encode("utf-8")).decode("utf-8")
            params["contentsEncoded"] = True
        resp = await async_send_command_with_retry(ctx, "manage_script", params)
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}


    @mcp.tool(description=(
        "Create a new C# script at the given project path.\n\n"
        "PHYSICS RULES before writing movement code:\n"
        "1. Read the existing Rigidbody first. Note mass, drag, constraints or freezeRotation, centerOfMass, collider thickness, and collisionDetectionMode. Use real values, not assumptions.\n"
        "2. ForceMode.Force and ForceMode.Impulse divide by mass and already include Time.fixedDeltaTime. Estimate whether your magnitude exceeds mu * mass * g and never multiply by delta time manually.\n"
        "3. ForceMode.Acceleration and ForceMode.VelocityChange ignore mass, but only use them when the driven axis is fully free and the inertia tensor is finite. Otherwise fall back to Force, Impulse, MovePosition, or MoveRotation.\n"
        "4. Torque must respect inertia. Scale torque with inertia, keep a non-zero baseline so steering responds at low speed, and fall back to Force or rotation helpers if axes are constrained.\n"
        "5. Align numbers with the scene. If your script assumes a heavy body, either update the mass and colliders or choose mass-independent modes. Account for drag, downforce, and collision thickness to avoid tunneling.\n"
        "6. After coding, double-check: ForceMode matches constraints, no extra delta time multipliers, forces scale with mass and friction, and low-speed behavior remains controllable.\n\n"
        "Args: path (e.g., 'Assets/Scripts/My.cs',a complete path is required, and the path may have multiple layers), contents (string), script_type, namespace,task_name({{task_name_prompt}}).\n"
        "Rules: path must be under Assets/. Contents will be Base64-encoded over transport.\n"
    ))
    async def create_script(
        ctx: Context,
        path: str,
        contents: str = "",
        script_type: str | None = None,
        namespace: str | None = None,
        task_name: str = None,
    ) -> Dict[str, Any]:
        """Create a new C# script at the given path."""
        name = os.path.splitext(os.path.basename(path))[0]
        directory = os.path.dirname(path)
        # Local validation to avoid round-trips on obviously bad input
        norm_path = os.path.normpath((path or "").replace("\\", "/")).replace("\\", "/")
        if not directory or directory.split("/")[0].lower() != "assets":
            return {"success": False, "code": "path_outside_assets", "message": f"path must be under 'Assets/'; got '{path}'."}
        if ".." in norm_path.split("/") or norm_path.startswith("/"):
            return {"success": False, "code": "bad_path", "message": "path must not contain traversal or be absolute."}
        if not name:
            return {"success": False, "code": "bad_path", "message": "path must include a script file name."}
        if not norm_path.lower().endswith(".cs"):
            return {"success": False, "code": "bad_extension", "message": "script file must end with .cs."}
        params: Dict[str, Any] = {
            "action": "create",
            "name": name,
            "path": directory,
            "namespace": namespace,
            "scriptType": script_type,
        }
        if contents:
            params["encodedContents"] = base64.b64encode(contents.encode("utf-8")).decode("utf-8")
            params["contentsEncoded"] = True
        params = {k: v for k, v in params.items() if v is not None}
        resp = await async_send_command_with_retry(ctx, "manage_script", params)
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}

    @mcp.tool(description=(
        "Delete a C# script by URI or Assets-relative path.\n\n"
        "Args: uri (Assets/Scripts/XX.cs,a complete path is required, and the path may have multiple layers),task_name({{task_name_prompt}}).\n"
        "Rules: Target must resolve under Assets/.\n"
    ))
    async def delete_script(ctx: Context, uri: str,task_name: str = None) -> Dict[str, Any]:
        """Delete a C# script by URI."""
        name, directory = _split_uri(uri)
        if not directory or directory.split("/")[0].lower() != "assets":
            return {"success": False, "code": "path_outside_assets", "message": "URI must resolve under 'Assets/'."}
        params = {"action": "delete", "name": name, "path": directory}
        resp = await async_send_command_with_retry(ctx, "manage_script", params)
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}

    @mcp.tool(description=(
        "Validate a C# script and return diagnostics.\n\n"
        "Args: uri(Assets/Scripts/XX.cs,a complete path is required, and the path may have multiple layers), task_name({{task_name_prompt}}), level=('basic'|'standard').\n"
        "- basic: quick syntax checks.\n"
        "- standard: deeper checks (performance hints, common pitfalls).\n"
    ))
    async def validate_script(
        ctx: Context, uri: str, level: str = "basic",task_name: str = None,
    ) -> Dict[str, Any]:
        """Validate a C# script and return diagnostics."""
        name, directory = _split_uri(uri)
        if not directory or directory.split("/")[0].lower() != "assets":
            return {"success": False, "code": "path_outside_assets", "message": "URI must resolve under 'Assets/'."}
        if level not in ("basic", "standard"):
            return {"success": False, "code": "bad_level", "message": "level must be 'basic' or 'standard'."}
        params = {
            "action": "validate",
            "name": name,
            "path": directory,
            "level": level,
        }
        resp = await async_send_command_with_retry(ctx, "manage_script", params)
        if isinstance(resp, dict) and resp.get("success"):
            diags = resp.get("data", {}).get("diagnostics", []) or []
            warnings = sum(d.get("severity", "").lower() == "warning" for d in diags)
            errors = sum(d.get("severity", "").lower() in ("error", "fatal") for d in diags)
            return {"success": True, "data": {"warnings": warnings, "errors": errors}}
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}


    @mcp.tool(description=(
        "Get SHA256 and metadata for a Unity C# script without returning file contents.\n\n"
        "Args: uri (Assets/Scripts/XX.cs,a complete path is required, and the path may have multiple layers), task_name({{task_name_prompt}}).\n"
        "Returns: {sha256, lengthBytes, lastModifiedUtc, uri, path}."
    ))
    async def get_sha(ctx: Context, uri: str,task_name: str = None,) -> Dict[str, Any]:
        """Return SHA256 and basic metadata for a script."""
        try:
            name, directory = _split_uri(uri)
            params = {"action": "get_sha", "name": name, "path": directory}
            resp = await async_send_command_with_retry(ctx, "manage_script", params)
            if isinstance(resp, dict) and resp.get("success"):
                data = resp.get("data", {})
                return {
                    "success": True,
                    "data": {
                        "sha256": data.get("sha256"),
                        "lengthBytes": data.get("lengthBytes"),
                    },
                }
            return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}
        except Exception as e:
            return {"success": False, "message": f"get_sha error: {e}"}

    @mcp.tool(description=("""Get a Unity C# script file contents.
        Args:
        - uri: uri (Assets/Scripts/XX.cs,a complete path is required, and the path may have multiple layers)
        - task_name: {{task_name_prompt}}.
        Returns: 
        - contents: script contents
        - uri
        - path
        """
    ))
    async def get_script_content(ctx: Context, uri: str,task_name: str | None = None,) -> Dict[str, Any]:
        """Get the content of a C# script."""
        name, directory = _split_uri(uri)
        params = {"action": "read", "name": name, "path": directory}
        resp = await async_send_command_with_retry(ctx, "manage_script", params)
        return resp if isinstance(resp, dict) else {"success": False, "message": str(resp)}
