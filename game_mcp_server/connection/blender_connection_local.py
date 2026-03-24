import json
import logging
import os
from typing import Dict, Any, Optional

import aiohttp
import orjson

from connection.connection_interface import ConnectionInterface

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 27980
DEFAULT_PATH = "/mcp"
DEFAULT_TIMEOUT = 120.0

logger = logging.getLogger(__name__)


class BlenderConnection(ConnectionInterface):

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, path: str = DEFAULT_PATH):
        self.host = host
        self.port = port
        self.path = path
        self.base_url = f"http://{self.host}:{self.port}{self.path}"

    def connect(self) -> bool:
        """No-op for HTTP connection; kept for interface compatibility."""
        return True

    def disconnect(self):
        """No persistent connection to close for HTTP transport."""
        pass

    async def send_command(self, command_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a command to Blender HTTP endpoint and return the response"""

        payload = {
            "method": command_type,
            "params": params or {}
        }

        logger.info(f"Sending Blender HTTP command: {command_type} payload: {json.dumps(payload)}")

        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, json=payload) as resp:
                    body = await resp.json(content_type=None, loads=orjson.loads)
                    logger.info(f"Blender HTTP response status:{resp.status} body:{body}")
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}: {body}")

                    if isinstance(body, dict):
                        if body.get("status") == "error":
                            return {"success": False, "message": body.get("message", "Unknown error from Blender")}
                        if "result" in body:
                            return {"success": True, "data": body["result"]}
                    return body if isinstance(body, dict) else {"result": body}
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error communicating with Blender: {str(e)}")
            raise Exception(f"HTTP client error communicating with Blender: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Blender: {str(e)}")
            raise


# Global connection for resources (since resources can't access context)
_blender_connection = None


def get_blender_connection_local():
    """Get or create a persistent Blender connection"""
    global _blender_connection

    # Create a new connection if needed
    if _blender_connection is None:
        host = os.getenv("BLENDER_HOST", DEFAULT_HOST)
        port = int(os.getenv("BLENDER_PORT", DEFAULT_PORT))
        _blender_connection = BlenderConnection(host=host, port=port)
        if not _blender_connection.connect():
            logger.error("Failed to connect to Blender")
            _blender_connection = None
            raise Exception("Could not connect to Blender. Make sure the Blender addon is running.")
        logger.info("Created new persistent connection to Blender")

    return _blender_connection
