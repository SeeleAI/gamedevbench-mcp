import os
import asyncio

from server_start_config import mcp_start_config
from util.logging_context import init_logging

from dotenv import load_dotenv

load_dotenv()

if os.environ.get("RUN_PLATFORM") == "3js":
    os.environ["NACOS_NAMESPACE"] = "ce423158-c110-48fa-af05-a6e6f28d0038"

# Run the server
if __name__ == "__main__":
    mcp_start_config["mcp_transport"] = "streamable-http"
    mcp_start_config["mcp_port"] = 6500
    mcp_start_config["stateless_http"] = True
    init_logging()
    from remote_config import init_all_configs
    asyncio.run(init_all_configs())
    from server_logic import main_server

    main_server()
