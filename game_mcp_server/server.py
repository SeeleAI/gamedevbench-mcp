import asyncio

from util.logging_context import init_logging

# Run the server
if __name__ == "__main__":
    init_logging()
    from remote_config import init_all_configs
    asyncio.run(init_all_configs())
    from server_logic import main_server
    main_server()
