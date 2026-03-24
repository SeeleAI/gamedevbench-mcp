import asyncio
import logging
import random
import socket
import threading
from contextlib import closing

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from async_http.async_callback_handler import AsyncCallbackHandler
from async_http.base_http_handler import BaseHttpHandler

logger = logging.getLogger(__name__)


class HttpRegisterManager:
    """Start a lightweight FastAPI server."""

    _HOST = "0.0.0.0"
    _PORT_MIN = 61000
    _PORT_MAX = 62000

    def __init__(self) -> None:
        self._port = self._pick_free_port()
        if self._port is None:
            raise RuntimeError("AsyncHttpManager could not find an available port in 61000-62000 range")

        self._app = FastAPI()
        self._http_handlers: list[BaseHttpHandler] = [AsyncCallbackHandler()]

        self._configure_routes()
        # Register /remix and /threejs/deploy-template (same app as server_deploy uses)
        from http_logic.http_register import init_http_server
        init_http_server(self._app)

        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # public api
    # ------------------------------------------------------------------

    def start(self):
        self._start_server_thread()

    @property
    def listening_port(self) -> int:
        return self._port

    def shutdown(self, timeout: float = 5.0) -> None:
        if not self._server or not self._thread:
            return

        self._server.should_exit = True
        self._server.force_exit = True
        self._thread.join(timeout)
        if self._thread.is_alive():
            logger.warning("AsyncHttpManager server thread did not exit within %.1fs", timeout)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _configure_routes(self) -> None:
        for handler in self._http_handlers:
            @self._app.post(handler.get_path())
            async def route(request: Request, http_handler=handler) -> JSONResponse:
                return await http_handler.handle_request(request)

    def _start_server_thread(self) -> None:
        def run_server() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            config = uvicorn.Config(self._app, host=self._HOST, port=self._port, log_level="info", loop="asyncio")
            server = uvicorn.Server(config)
            self._server = server

            loop.run_until_complete(server.serve())
            loop.close()

        self._thread = threading.Thread(target=run_server, name="AsyncHttpManager", daemon=True)
        self._thread.start()

    @classmethod
    def _pick_free_port(cls) -> int | None:
        candidates = list(range(cls._PORT_MIN, cls._PORT_MAX + 1))
        random.shuffle(candidates)
        for port in candidates:
            if cls._is_port_free(port):
                return port
        return None

    @staticmethod
    def _is_port_free(port: int) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False


http_register_manager = HttpRegisterManager()
