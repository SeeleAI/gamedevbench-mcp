import asyncio
import logging
import threading
import traceback
import uuid
from contextlib import suppress
from typing import Any, Dict

import aiohttp

from async_http.async_callback_handler import AsyncCallbackHandler
from async_http.http_register_manager import http_register_manager
from config import config
from connection.connection_interface import ConnectionInterface
from port_discovery import PortDiscovery

logger = logging.getLogger(__name__)


class UnityHttpConnection(ConnectionInterface):
    def __init__(self, host: str = config.unity_host, port: int | None = None):
        self.host = host
        self.port = port
        if self.port is None:
            self.port = PortDiscovery.discover_unity_port()

    def connect(self) -> bool:
        return True

    def disconnect(self):
        pass

    def _get_target_url(self) -> str:
        return f"http://{self.host}:{self.port}/command"

    @staticmethod
    def _get_callback_url(task_id: str) -> str:
        return f"http://localhost:{http_register_manager.listening_port}/callback?task_id={task_id}"

    async def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        payload = {
            "command_type": command_type,
            "params": params,
            "callback_url": self._get_callback_url(task_id),
            "task_id": task_id,
        }

        wait_callback_task = asyncio.create_task(AsyncCallbackHandler.register_and_wait(task_id, config.callback_timeout))

        try:
            timeout = aiohttp.ClientTimeout(total=config.http_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._get_target_url(), json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Unexpected HTTP status from server: {resp.status}")
                        raise RuntimeError(f"Unexpected response from server: {resp.status}")
                    data = await resp.json()
                    logger.info(f"Received response from Unity: {data}")
                    if data.get("code") != 0:
                        return {"success": False, "msg": data.get("message")}
            result = await wait_callback_task
            return result.get("result", {})
        finally:
            try:
                if not wait_callback_task.done():
                    wait_callback_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await wait_callback_task
            except Exception as e:
                logger.warning(f"Error cancelling wait_callback_task: {e} {traceback.format_exc()}")
            AsyncCallbackHandler.remove_callback_invoke(task_id)

# Global Unity connection
_unity_connection = None
_connection_lock = threading.Lock()
def get_unity_connection_local() -> UnityHttpConnection:
    """Retrieve or establish a persistent Unity connection.

    Note: Do NOT ping on every retrieval to avoid connection storms. Rely on
    send_command() exceptions to detect broken sockets and reconnect there.
    """
    global _unity_connection
    if _unity_connection is not None:
        return _unity_connection

    # Double-checked locking to avoid concurrent socket creation
    with _connection_lock:
        if _unity_connection is not None:
            return _unity_connection
        logger.info("Creating new Unity connection")
        _unity_connection = UnityHttpConnection()
        if not _unity_connection.connect():
            _unity_connection = None
            raise ConnectionError("Could not connect to Unity. Ensure the Unity Editor and MCP Bridge are running.")
        logger.info("Connected to Unity on startup")
        return _unity_connection