"""
用于远端访问平台引擎的代理
"""
import logging
from typing import Dict, Any

from click import Context

from config import config
from connection.connection_remote_delegate import ConnectionRemoteDelegate

logger = logging.getLogger(__name__)


class BlenderConnectionRemoteDelegate(ConnectionRemoteDelegate):
    def __init__(self, ctx: Context):
        super().__init__(ctx)

    def connect(self) -> bool:
        return True

    def disconnect(self):
        pass

    def get_req_url(self, command_type: str, params: Dict[str, Any] = None) -> str:
        return f"{config.syn_base_url}/gateway/api/blender/{command_type}?abs_cuda_proxy_service_name=blender_mcp&abs_cuda_proxy_func_name={command_type}"

    def transform_params(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if "canvas_id" not in params:
            params["canvas_id"] = self.canvas_id
        return params

    async def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        result = await super().send_command(command_type, params)
        if result.get("code") == 0:
            del result["code"]
        return result