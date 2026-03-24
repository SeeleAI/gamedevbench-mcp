from abc import abstractmethod, ABC
from typing import Dict, Any


class ConnectionInterface(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    async def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        pass
