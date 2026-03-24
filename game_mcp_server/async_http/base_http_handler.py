from abc import ABC, abstractmethod

from fastapi import Request
from fastapi.responses import JSONResponse


class BaseHttpHandler(ABC):
    @abstractmethod
    def get_path(self) -> str:
        pass

    @abstractmethod
    async def handle_request(self, request: Request) -> JSONResponse:
        pass
