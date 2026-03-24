import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncIterator, Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from config import config, SERVER_START_LOCAL_HTTP_MODE, RUN_PLATFORM_3JS
from server_start_config import mcp_start_config
from tools import register_all_tools
from connection.connection_provider import get_current_connection
from util.context_util import get_context_x_seele_canvas_trace_id
from util.logging_context import set_trace_id, reset_trace_id
from util.metrics import instrument_tool

server_name = f"mcp-for-{config.run_platform}-server"

logger = logging.getLogger(server_name)



@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """
    Handle server startup and shutdown.
    
    主要管理 Unity 连接的生命周期（local 模式）。
    ThreeJS 的定时任务生命周期由 threejs_scheduler_lifespan() 独立管理。
    """
    if config.start_mode != SERVER_START_LOCAL_HTTP_MODE:
        logger.info(f"Starting in non-local mode; skipping {config.run_platform} connection")
        try:
            # Provide a no-op context so consumers can still access ctx.bridge safely
            yield {"bridge": None}
        finally:
            logger.info("Shutting down in non-local mode")
        return
    logger.info(f"MCP for {config.run_platform} Server starting up")
    try:
        _unity_connection = get_current_connection()
        logger.info("Connected to Unity on startup")
    except Exception as e:
        logger.warning(f"Could not connect to Unity on startup: {str(e)}")
        _unity_connection = None
    try:
        # Yield the connection object so it can be attached to the context
        # The key 'bridge' matches how tools like read_console expect to access it (ctx.bridge)
        yield {"bridge": _unity_connection}
    finally:
        if _unity_connection:
            _unity_connection.disconnect()
            _unity_connection = None
        logger.info("MCP for Unity Server shut down")

# Initialize MCP server
mcp_kv = {
}
if mcp_start_config["mcp_port"]:
    mcp_kv['port'] = mcp_start_config["mcp_port"]
if mcp_start_config["mcp_host"]:
    mcp_kv['host'] = mcp_start_config["mcp_host"]
if mcp_start_config["json_response"]:
    mcp_kv['json_response'] = mcp_start_config["json_response"]
if mcp_start_config["stateless_http"]:
    mcp_kv['stateless_http'] = mcp_start_config["stateless_http"]
mcp = FastMCP(
    server_name,
    lifespan=server_lifespan,
    **mcp_kv
)
all_local_prompts = {}

# Monkey-patch mcp.tool to auto-instrument all tools
_orig_tool = mcp.tool
def _instrumenting_tool(*t_args, **t_kwargs):
    def _outer(fn):
        name = t_kwargs.get("name") or getattr(fn, "__name__", "tool")
        @wraps(fn)
        async def _logged(*args, **kwargs):
            start_time = time.time()
            token = None
            for item in kwargs.items():
                key, value = item
                if isinstance(value, Context):
                    canvas_trace_id = get_context_x_seele_canvas_trace_id(value)
                    if canvas_trace_id:
                        token = set_trace_id(canvas_trace_id)
                    break
            logger.info(f"tool_start name={name} input_info:{kwargs}")
            try:
                result = await fn(*args, **kwargs)
                logger.info(f"tool_end name={name} status=ok result:{result}")
                return result
            except Exception as e:
                logger.info(f"tool_end name={name} status=error error={e} {traceback.format_exc()}")
                raise
            finally:
                logger.info(f"tool_duration name={name} cos:{time.time() - start_time}")
                if token:
                    reset_trace_id(token)

        wrapped = instrument_tool(name)(_logged)
        orig_kwargs = dict(t_kwargs)
        if "name" not in orig_kwargs:
            orig_kwargs["name"] = name
        all_local_prompts[name] = orig_kwargs.get("description", "")
        from tools.prompt_process import description_auto_replace
        description_auto_replace(name, orig_kwargs)
        return _orig_tool(*t_args, **orig_kwargs)(wrapped)
    return _outer
mcp.tool = _instrumenting_tool  # type: ignore

# Register all tools
register_all_tools(mcp)

# logger.info(f"all local prompt:{json.dumps(all_local_prompts, indent=4)}")

# Asset Creation Strategy

# 这个已经放在nacos上配置了，后面不需要在代码里维护
@mcp.prompt()
def asset_creation_strategy() -> str:
    """The agent must follow these strategies during runtime:"""
    return (
        "0. Efficiency principle: Use the most appropriate tool for each situation. Screenshots are valuable for visual verification but not necessary for every operation. Trust numerical data (console logs, bounding boxes) for debugging and use visual confirmation when it genuinely helps.\n\n"
        "1. When first interacting with a Unity project, it's recommended to use `manage_editor` to check the environment and obtain project information. If the project is not empty, use `manage_scene` to inspect existing scene content, then determine whether to create from scratch or edit on the existing foundation.\n\n"
        "2. When creating new projects, always include a camera and main light in your scenes.\\n\\n"
        "3. Do not add additional code explanation summaries unless requested by the user. After working on a file, just stop rather than providing an explanation of what you did.\\n\\n"
        "4. For multiple identical objects, create a prefab first then instantiate it. Use prefabs for all reusable GameObjects to ensure consistency and efficiency.\n\n"
        "5. After importing any asset or creating GameObjects, always check `world_bounding_box` to:\n"
        "   - Ensure correct positioning, scale, and rotation\n"
        "   - Verify no unwanted clipping between objects\n"
        "   - Confirm proper spatial relationships\n\n" 
        "6. Asset acquisition priority order:\n"
        "   - First: Always try search tools\n"
        "   - Second: Use generation tools only if search results don't meet requirements\n"
        "   - Last resort: Use internal scripts only if both search and generation tools fail or report errors\n"
        "7. Select appropriate tools based on tool descriptions to complete tasks.\\n\\n"
        "8. Always strictly follow tool calling patterns, ensuring all required parameters are provided. Never call tools that are not explicitly provided. If a tool fails, try alternative approaches.\\n\\n"
        "9. After obtaining assets through search, analyze and consider whether they meet current game requirements. If they don't match, use other tools to obtain suitable assets.\\n\\n"
        "10. Debugging and verification:\n"
        "    - For script errors: ALWAYS check `read_console` first for error messages\n"
        "    - For visual/spatial issues: Use `get_screenshot` to verify appearance\n"
        "11. Terrain generation complexity guidelines:\n"
        "    - **Complex type**: ONLY for scenes with explicit artificial structures (buildings, roads, urban elements)\n"
        "    - **Simple type**: Natural landscapes (mountains, rivers, forests, deserts) are always simple\n\n"
        "12. Execute complex code step-by-step: When using `manage_script`, break down complex operations into multiple small code blocks and verify results at each step.\\n\\n"
        "13. If uncertain about user requests related to scene content or asset structure, use tools to obtain relevant information. Do not guess or fabricate answers.\\n\\n"
        "14. When tool calls fail, attempt alternative approaches.\\n\\n"
        "15. All imported assets require position and scale checking using `world_bounding_box`. Take screenshots only when you need visual confirmation of the final result or spatial relationships.\n"
        "16. ALWAYS stop play mode before making scene modifications.\\n"
    )

# Run the server
def main_server():
    if config.start_mode == SERVER_START_LOCAL_HTTP_MODE:
        from async_http.http_register_manager import http_register_manager
        http_register_manager.start()
        logger.info(f"http_register_manager {http_register_manager.listening_port}")
    mcp.run(transport=mcp_start_config["mcp_transport"])
