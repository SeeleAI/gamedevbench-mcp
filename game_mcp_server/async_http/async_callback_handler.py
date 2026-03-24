import asyncio
import logging
import threading
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from async_http.base_http_handler import BaseHttpHandler

CallbackInvoke = Callable[[Request], Awaitable[Any]]

logger = logging.getLogger(__name__)


class AsyncCallbackHandler(BaseHttpHandler):
    """Handle `/callback` requests by dispatching to registered coroutines."""

    _callback_invokes: dict[str, CallbackInvoke] = {}
    _lock = threading.RLock()

    @classmethod
    def register_callback_invoke(cls, task_id: str, invoke: CallbackInvoke) -> None:
        if not task_id:
            raise ValueError("task_id must be provided")
        if not callable(invoke):
            raise ValueError("invoke must be callable")
        with cls._lock:
            cls._callback_invokes[task_id] = invoke

    @classmethod
    async def register_and_wait(cls, task_id: str, timeout: float | None = None) -> Any:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        async def _callback(request: Request) -> None:
            try:
                payload = await cls._extract_payload(request)
            except Exception as exc:  # noqa: BLE001 - propagate to waiting future
                logger.error(
                    "Callback payload extraction failed for task_id: %s %s %s",
                    task_id,
                    exc,
                    traceback.format_exc(),
                )
                loop.call_soon_threadsafe(cls._set_future_exception, future, exc)
                return

            loop.call_soon_threadsafe(cls._set_future_result, future, payload)

        cls.register_callback_invoke(task_id, _callback)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except Exception:
            if not future.done():
                cls.remove_callback_invoke(task_id)
            raise

    @classmethod
    def remove_callback_invoke(cls, task_id: str) -> None:
        if not task_id:
            return
        if task_id not in cls._callback_invokes:
            return
        with cls._lock:
            cls._callback_invokes.pop(task_id, None)

    def get_path(self) -> str:
        return "/callback"

    async def handle_request(self, request: Request) -> JSONResponse:
        task_id = request.query_params.get("task_id")
        if not task_id:
            return JSONResponse(status_code=400, content={"code": -1, "message": "Missing task_id in query"})

        callback = self._pop_callback(task_id)
        if callback is None:
            return JSONResponse(content={"code": -1, "message": f"No callback registered for task_id: {task_id}"})

        try:
            await callback(request)
        except Exception as e:
            logger.error(f"Callback execution failed for task_id: {task_id} {e} {traceback.format_exc()}")

        return JSONResponse(content={"code": 0, "message": f"Callback finished for task_id: {task_id}"})

    @classmethod
    def _pop_callback(cls, task_id: str) -> CallbackInvoke | None:
        with cls._lock:
            return cls._callback_invokes.pop(task_id, None)

    @staticmethod
    async def _extract_payload(request: Request) -> Any:
        try:
            return await request.json()
        except Exception:
            return await request.body()

    @staticmethod
    def _set_future_result(future: asyncio.Future[Any], value: Any) -> None:
        if not future.done():
            future.set_result(value)

    @staticmethod
    def _set_future_exception(future: asyncio.Future[Any], exc: Exception) -> None:
        if not future.done():
            future.set_exception(exc)
