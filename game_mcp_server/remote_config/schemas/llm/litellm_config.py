from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import JsonConfig

from dataclasses import asdict, dataclass


@dataclass
class LiteLLMConfigItem:
    """单个LiteLLM Config 配置项"""

    model: str
    api_key: str
    endpoint: str
    default_path: str


    def to_dict(self):
        return asdict(self)


@nacos_binding(data_id="litellm_config.json")
class LiteLLMConfig(JsonConfig):
    configs: list[LiteLLMConfigItem]
