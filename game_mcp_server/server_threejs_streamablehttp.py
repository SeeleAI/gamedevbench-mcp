import os
import asyncio

# Must set RUN_PLATFORM before any import that loads config (e.g. logging_context, server_logic, tools)
os.environ["RUN_PLATFORM"] = "3js"
os.environ["NACOS_NAMESPACE"] = "ce423158-c110-48fa-af05-a6e6f28d0038"

from dotenv import load_dotenv
load_dotenv()

from server_start_config import mcp_start_config
from util.logging_context import init_logging

# Run the server
if __name__ == "__main__":
    mcp_start_config["mcp_transport"] = "streamable-http"
    mcp_start_config["mcp_port"] = 6600
    mcp_start_config["stateless_http"] = True
    init_logging()
    from remote_config import init_all_configs
    asyncio.run(init_all_configs())
    from server_logic import main_server

    main_server()
