"""
用于远端访问平台引擎的代理
"""
import asyncio
import logging
import random
import traceback
from typing import Dict, Any
import time

import aiohttp
import orjson
from click import Context

from config import config
from connection.connection_interface import ConnectionInterface
from util.context_util import get_context_canvas_id, get_context_x_seele_canvas_trace_id, get_context_header_value
from util.metrics import COMMAND_CALLS, COMMAND_LATENCY, APP_LABEL_VALUE

logger = logging.getLogger(__name__)


class ConnectionRemoteDelegate(ConnectionInterface):
    def __init__(self, ctx: Context):
        self.canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
        self.trace_id = get_context_x_seele_canvas_trace_id(ctx) or config.test_trace_id
        self.mate_header = get_context_header_value(ctx)

    def connect(self) -> bool:
        return True

    def disconnect(self):
        pass

    def get_req_url(self, command_type: str, params: Dict[str, Any] = None) -> str:
        return f"{config.syn_base_url}/gateway/env/{config.run_platform}/execute?abs_cuda_proxy_service_name={config.run_platform}&abs_cuda_proxy_func_name={command_type}"

    def transform_params(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return {
            "command": command_type,
            "params": params,
        }

    def transform_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        return response

    async def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        start = time.perf_counter()
        url = self.get_req_url(command_type, params)
        if "x-canvas-id" not in params:
            params["x-canvas-id"] = self.canvas_id
        if "x-seele-canvas-trace-id" not in params:
            params["x-seele-canvas-trace-id"] = self.trace_id
        payload = self.transform_params(command_type, params)
        headers = {
            "token": "seele_koko_pwd",
            "x-canvas-id": self.canvas_id,
            "x-seele-canvas-trace-id": self.trace_id,
        }

        if self.mate_header and isinstance(self.mate_header, dict):
            headers.update(self.mate_header)

        logger.info(f"Sending command: {command_type} headers:{headers} payload:{payload}")
        status = "ok"
        business_status = "ok"
        try:
            for i in range(2):
                timeout = aiohttp.ClientTimeout(total=600)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload, headers=headers) as resp:
                        data = await resp.json(content_type=None, loads=orjson.loads)
                        logger.info(f"Sending {command_type} command resp: status:{resp.status} data:{data}")
                        if resp.status == 200:
                            return_data = data if isinstance(data, dict) else {"success": True, "data": data}
                            return_data = self.transform_response(return_data)
                            if not return_data.get("success", False):
                                if return_data.get("code") == 503 and return_data.get(
                                        "message") == "Service Unavailable":
                                    logger.warning(
                                        f"command_type: {command_type} send command service unavailable, may be busy: {data} will retry")
                                    await asyncio.sleep(random.randint(1, 3))
                                    continue
                                business_status = "business_error"
                                logger.warning(f"command_type: {command_type} send command business error: {data}")
                            return return_data
                        status = "error"
                        business_status = "error"
                        return {"success": False, "message": f"status: {resp.status} data:{data}"}
        except Exception as e:
            logger.warning(f"Sending {command_type} command: fail {e} {traceback.format_exc()}")
            status = "error"
            business_status = "error"
            return {"success": False, "message": str(e)}
        finally:
            duration = time.perf_counter() - start
            COMMAND_CALLS.labels(
                command_type=command_type,
                status=status,
                business_status=business_status,
                type=config.run_platform,
                application=APP_LABEL_VALUE
            ).inc()
            COMMAND_LATENCY.labels(
                command_type=command_type,
                status=status,
                business_status=business_status,
                type=config.run_platform,
                application=APP_LABEL_VALUE
            ).observe(duration)
