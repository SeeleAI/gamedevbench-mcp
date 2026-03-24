import json
import logging
from typing import Dict, Any, Optional, List

import aiohttp
import orjson
import asyncio

from config import config

logger = logging.getLogger(__name__)


class DifyClient:
    """Dify API client"""
    wait_sse_count = 0

    def __init__(self, api_key: str, canvas_id: str, timeout_s: int = 600) -> None:
        self.base_url = config.dify_base_url
        self.api_key = api_key
        self.canvas_id = canvas_id
        self.timeout_s = timeout_s

    @staticmethod
    async def wait_all_sse():
        while DifyClient.wait_sse_count > 0:
            logger.info(f"Waiting for {DifyClient.wait_sse_count} sse events")
            await asyncio.sleep(10)

    @staticmethod
    def _merge_headers(user_headers: Optional[Dict[str, str]], api_key: str) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if user_headers:
            headers.update(user_headers)
        return headers

    @staticmethod
    def _safe_json(obj: Any) -> Any:
        try:
            json.dumps(obj)
            return obj
        except Exception:
            return str(obj)

    def _get_user(self):
        return f"canvas_{self.canvas_id}"

    async def request(self, path: str, inputs: Optional[Dict[str, Any]] = None,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = self.base_url + "/" + path.lstrip("/")
        use_headers = self._merge_headers(headers, self.api_key)
        payload = {
            "inputs": inputs or {},
            "response_mode": "blocking",
            "user": self._get_user(),
        }
        body_text: Optional[str] = None
        body_json: Optional[Any] = None
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=use_headers, json=self._safe_json(payload)) as resp:
                    status = resp.status
                    try:
                        body_json = await resp.json(loads=orjson.loads)
                        body_json = body_json.get("data", {}).get("outputs", {})
                    except Exception:
                        try:
                            body_text = await resp.text()
                        except Exception:
                            body_text = None
                    logger.info(f"dify body_json:{body_json} body_text：{body_text}")
                    ok = 200 <= status < 300
                    result: Dict[str, Any] = {
                        "success": ok,
                        "status": status,
                        "data": body_json if body_json is not None else {"text": body_text},
                    }
                    if not ok:
                        result["message"] = f"HTTP error {status} body_json：{body_json} body_text：{body_text}"
                    return result
        except Exception as e:
            return {"success": False, "message": f"HTTP request failed: {e}"}

    async def run_workflow(self, inputs: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> \
    Dict[str, Any]:
        return await self.request("/workflows/run", inputs=inputs, headers=headers)

    async def start_workflow_stream(self, inputs: Optional[Dict[str, Any]] = None,
                                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Start a workflow in streaming mode and return the session and response stream.

        Returns: {"success": bool, "status": int, "session": ClientSession, "response": ClientResponse, "message"?: str}
        Caller is responsible for closing both session and response.
        """
        url = self.base_url + "/workflows/run"
        payload = {
            "inputs": inputs or {},
            "response_mode": "streaming",
            "user": self._get_user(),
        }
        extra_headers = {"Accept": "text/event-stream"}
        use_headers = self._merge_headers(headers, self.api_key)
        use_headers.update(extra_headers)
        logger.info(f"dify url: {url} payload:{payload} use_headers: {use_headers}")
        try:
            timeout = aiohttp.ClientTimeout(total=2000)
            session = aiohttp.ClientSession(timeout=timeout)
            resp = await session.post(url, headers=use_headers, json=self._safe_json(payload))
            status = resp.status
            if not (200 <= status < 300):
                try:
                    text = await resp.text()
                except Exception:
                    text = None
                await resp.release()
                await session.close()
                return {
                    "success": False,
                    "status": status,
                    "message": f"HTTP error {status} body: {text}",
                }
            return {"success": True, "status": status, "session": session, "response": resp}
        except Exception as e:
            try:
                await session.close()  # type: ignore
            except Exception:
                pass
            return {"success": False, "message": f"Streaming request failed: {e}"}

    async def listen_for_workflow_started_and_get_task_id(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Listen on an open SSE response until workflow_started, then close and return IDs.

        Returns: {"success": bool, "task_id": str, "workflow_run_id": str, "message"?: str}
        """
        try:
            status = response.status
            event_type: Optional[str] = None
            data_lines: List[str] = []

            while True:
                raw_line = await response.content.readline()
                if not raw_line:
                    break
                try:
                    line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                except Exception:
                    line = ""

                if line == "":
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            obj = orjson.loads(data_str)
                        except Exception:
                            obj = {}

                        evt = obj.get("event") if isinstance(obj, dict) else None
                        effective_event = evt or event_type

                        if effective_event == "workflow_started":
                            task_id = obj.get("task_id") if isinstance(obj, dict) else None
                            workflow_run_id = obj.get("workflow_run_id") if isinstance(obj, dict) else None
                            try:
                                response.close()
                            except Exception:
                                pass
                            return {
                                "success": True,
                                "status": status,
                                "task_id": task_id,
                                "workflow_run_id": workflow_run_id,
                            }

                    event_type = None
                    data_lines = []
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                    continue

            return {
                "success": False,
                "status": status,
                "message": "Stream ended before workflow_started event was received",
            }
        except Exception as e:
            try:
                response.close()
            except Exception:
                pass
            return {"success": False, "message": f"Streaming listen failed: {e}"}

    @staticmethod
    async def listen_for_workflow_started_no_close(response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Listen until workflow_started WITHOUT closing the response.

        Returns: {"success": bool, "task_id": str, "workflow_run_id": str, "message"?: str}
        """
        try:
            status = response.status
            event_type: Optional[str] = None
            data_lines: List[str] = []

            while True:
                raw_line = await response.content.readline()
                if not raw_line:
                    break
                try:
                    line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                except Exception:
                    line = ""

                if line == "":
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            obj = orjson.loads(data_str)
                        except Exception:
                            obj = {}

                        evt = obj.get("event") if isinstance(obj, dict) else None
                        effective_event = evt or event_type

                        if effective_event == "workflow_started":
                            task_id = obj.get("task_id") if isinstance(obj, dict) else None
                            workflow_run_id = obj.get("workflow_run_id") if isinstance(obj, dict) else None
                            return {
                                "success": True,
                                "status": status,
                                "task_id": task_id,
                                "workflow_run_id": workflow_run_id,
                            }

                    event_type = None
                    data_lines = []
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                    continue

            return {
                "success": False,
                "status": status,
                "message": "Stream ended before workflow_started event was received",
            }
        except Exception as e:
            return {"success": False, "message": f"Streaming listen failed: {e}"}

    @staticmethod
    async def _drain_sse_until_finished(session: aiohttp.ClientSession, response: aiohttp.ClientResponse, timeout_s: Optional[float] = None) -> None:
        """Drain SSE stream until completion, then release/close resources.

        Shield the read loop so it can finish gracefully even if outer tasks are cancelled during shutdown.
        Optionally enforce a timeout to avoid hanging indefinitely.
        """
        async def _read_loop() -> None:
            """Stream-safe SSE reader that avoids aiohttp readline limits."""
            event_type: Optional[str] = None
            data_lines: List[str] = []
            buffer = b""
            max_buffer_bytes = 2 * 1024 * 1024  # safety cap to avoid unbounded growth

            def _process_line(line: str) -> bool:
                nonlocal event_type, data_lines
                if line == "":
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            obj = orjson.loads(data_str)
                        except Exception:
                            logger.debug(
                                "SSE drain: failed to parse JSON from data (truncated)",
                                extra={"preview": data_str[:512] if isinstance(data_str, str) else None},
                                exc_info=True,
                            )
                            obj = {}
                        evt = obj.get("event") if isinstance(obj, dict) else None
                        logger.info(f"Event received: {evt} {event_type}")
                        effective_event = evt or event_type
                        if effective_event == "workflow_finished":
                            return True
                    event_type = None
                    data_lines = []
                    return False

                if line.startswith(":"):
                    return False
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    return False
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                    return False
                return False

            async for chunk in response.content.iter_any():
                if not chunk:
                    break

                buffer += chunk
                if len(buffer) > max_buffer_bytes:
                    logger.warning("SSE drain: buffer exceeded cap; dropping oldest data chunk")
                    buffer = buffer[-max_buffer_bytes:]

                while True:
                    newline_idx = buffer.find(b"\n")
                    if newline_idx == -1:
                        break
                    raw_line = buffer[:newline_idx + 1]
                    buffer = buffer[newline_idx + 1:]
                    try:
                        line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                    except Exception:
                        logger.warning("SSE drain: failed to decode line", exc_info=True)
                        line = ""
                    should_break = _process_line(line)
                    if should_break:
                        return

            if buffer:
                try:
                    line = buffer.decode("utf-8", errors="ignore").rstrip("\r\n")
                except Exception:
                    logger.warning("SSE drain: failed to decode trailing buffer", exc_info=True)
                    line = ""
                _process_line(line)

        try:
            DifyClient.wait_sse_count += 1
            if timeout_s is None:
                try:
                    await asyncio.shield(_read_loop())
                except asyncio.CancelledError:
                    logger.info("SSE drain: cancellation received; shield active, finishing gracefully")
                    pass
            else:
                try:
                    async with asyncio.timeout(timeout_s):
                        await asyncio.shield(_read_loop())
                except asyncio.TimeoutError:
                    logger.warning("SSE drain timed out; proceeding to cleanup")
                except asyncio.CancelledError:
                    logger.info("SSE drain: cancellation received during timeout window; proceeding to cleanup")
                    pass
        except Exception:
            logger.warning("SSE drain: unexpected error in shielded loop", exc_info=True)
            pass
        finally:
            DifyClient.wait_sse_count -= 1
            try:
                await response.release()
            except Exception:
                logger.warning("SSE drain: failed to release response", exc_info=True)
            try:
                await session.close()
            except Exception:
                logger.warning("SSE drain: failed to close session", exc_info=True)

    async def start_workflow_and_get_task_id(self, inputs: Optional[Dict[str, Any]] = None,
                                             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Convenience method: start streaming, wait for workflow_started, keep the connection alive.

        This will NOT close the SSE connection upon receiving workflow_started. Instead, it will spawn a
        background task to drain the stream until completion so the workflow is not interrupted.
        """
        start = await self.start_workflow_stream(inputs=inputs, headers=headers)
        if not start.get("success"):
            return start
        session: aiohttp.ClientSession = start["session"]
        response: aiohttp.ClientResponse = start["response"]
        try:
            got = await self.listen_for_workflow_started_no_close(response)
            # Drain in background; do not hold references
            try:
                asyncio.create_task(self._drain_sse_until_finished(session, response))
            except Exception:
                # If scheduling fails, ensure cleanup won't interrupt workflow here; leave as-is
                pass
            return got
        except Exception as e:
            # On failure before start, clean up
            try:
                await response.release()
            except Exception:
                pass
            try:
                await session.close()
            except Exception:
                pass
            return {"success": False, "message": f"Failed to start workflow stream: {e}"}

    async def get_workflow_status(self, workflow_run_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Query workflow run status by workflow_run_id.

        Returns raw status payload: {"success": bool, "status": int, "data": dict, "message"?: str}
        """
        url = self.base_url + "/workflows/run/" + workflow_run_id
        use_headers = self._merge_headers(headers, self.api_key)
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=use_headers) as resp:
                    status = resp.status
                    try:
                        body_json = await resp.json(loads=orjson.loads)
                    except Exception:
                        try:
                            body_text = await resp.text()
                        except Exception:
                            body_text = None
                            body_json = None
                        body_json = {"text": body_text}
                    ok = 200 <= status < 300
                    result: Dict[str, Any] = {
                        "success": ok,
                        "status": status,
                        "data": body_json or {},
                    }
                    if not ok:
                        result["message"] = f"HTTP error {status}"
                    return result
        except Exception as e:
            return {"success": False, "message": f"HTTP request failed: {e}"}


if __name__ == "__main__":
    async def main():
        # client = DifyClient("app-zqOsqETE7lORw5URLlMPpcXR")
        # result = await client.run_workflow(
        #     inputs={
        #         "property_id": str(uuid.uuid4()),
        #         "category": "avatar",
        #         "query": "apple",
        #         "canvas_id": config.test_canvas_id,
        #     })
        # print(result)
        client = DifyClient("app-1rVepq15BcOBvimkShcHYIDg", "test")
        result = await client.run_workflow({
            "query": "ttt"
        })
        print(f"result:{result}")
        # workflow_run_id = "a78b4e62-c194-4ba3-ac7d-f4102bcfbb4a" #result["workflow_run_id"]
        # return await client.get_workflow_status(workflow_run_id)


    print(asyncio.run(main()))
