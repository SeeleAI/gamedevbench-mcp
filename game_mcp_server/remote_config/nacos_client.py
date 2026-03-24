import logging
import traceback
from typing import Optional, Callable

import nacos  # nacos-sdk-python
logger = logging.getLogger(__name__)

class NacosClient:
    def __init__(self, server_addrs: str, namespace: Optional[str] = None, username: Optional[str] = None,
                 password: Optional[str] = None):
        # access_key/secret_key not universally supported in all sdk versions; prefer username/password when provided
        self._client = nacos.NacosClient(server_addrs, namespace=namespace, username=username, password=password)

    async def start(self) -> None:
        # sync client; nothing to do
        return None

    async def shutdown(self) -> None:
        # sdk does not expose shutdown for sync client
        return None

    async def get_config_text(self, data_id: str, group: str) -> Optional[str]:
        try:
            return self._client.get_config(data_id, group)
        except Exception:
            return None

    async def add_listener(self, data_id: str, group: str, listener: Callable[[str], None]) -> None:
        # The SDK may call with content or args dict; adapt in provider if needed
        self._client.add_config_watcher(data_id, group, listener)

    async def remove_listener(self, data_id: str, group: str, listener: Callable[[str], None]) -> None:
        try:
            self._client.remove_config_watcher(data_id, group, listener)
        except Exception as e:
            logger.warning(f"fail remove listener: {e} {traceback.format_exc()}")

