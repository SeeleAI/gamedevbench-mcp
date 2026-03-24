import os
import asyncio

# 必须在导入 config 之前设置环境变量，因为 config.py 在模块级别会创建 ServerConfig 实例
# 而 ServerConfig 会在初始化时读取 RUN_PLATFORM 环境变量
os.environ["RUN_PLATFORM"] = "blender" # noqa: E402

from server_start_config import mcp_start_config
from util.logging_context import init_logging

# Run the server
if __name__ == "__main__":
    mcp_start_config["mcp_transport"] = "streamable-http"
    mcp_start_config["mcp_port"] = 6700
    mcp_start_config["stateless_http"] = True
    init_logging()
    from remote_config import init_all_configs
    asyncio.run(init_all_configs())
    from server_logic import main_server

    main_server()
