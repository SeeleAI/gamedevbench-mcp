import logging
import os

from mcp.server import FastMCP

from config import config, SERVER_START_REMOTE_MODE
from util.logging_context import init_logging
from server_start_config import mcp_start_config

config.start_mode = SERVER_START_REMOTE_MODE


async def run_streamable_http_async(mcp: FastMCP) -> None:
    """Run the server using StreamableHTTP transport."""
    import uvicorn
    from prometheus_fastapi_instrumentator import Instrumentator
    from server_logic import server_lifespan
    
    logger = logging.getLogger(__name__)
    tools = await mcp.list_tools()
    logger.info(f"mcp tool {len(tools)} {tools}")

    from tools import reset_tool_when_config_change
    await reset_tool_when_config_change(mcp)
    starlette_app = mcp.streamable_http_app()

    Instrumentator().instrument(starlette_app).expose(starlette_app, endpoint="/actuator/prometheus")
    from http_logic.http_register import init_http_server
    init_http_server(starlette_app)
    server_config = uvicorn.Config(
        starlette_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(server_config)
    
    # 手动管理 lifespan 上下文
    # 1. server_lifespan: 管理 Unity 连接（如果需要）
    # 2. threejs_scheduler_lifespan: 独立管理 ThreeJS 定时任务生命周期
    from util.schedule.lifespan import threejs_scheduler_lifespan
    
    async with server_lifespan(mcp), threejs_scheduler_lifespan():
        logger.info("Server lifespan context entered, starting uvicorn server")
        try:
            await server.serve()
        finally:
            from util.env_client import env_client
            await env_client.close()


# Run the server
if __name__ == "__main__":
    mcp_start_config["mcp_transport"] = "streamable-http"
    mcp_start_config["mcp_port"] = os.environ.get("SERVER_PORT", 8080)
    mcp_start_config["mcp_host"] = os.environ.get("SERVER_HOST", "0.0.0.0")
    mcp_start_config["stateless_http"] = True
    init_logging()
    import anyio

    from remote_config import init_all_configs
    anyio.run(init_all_configs)
    from server_logic import mcp

    anyio.run(run_streamable_http_async, mcp)
