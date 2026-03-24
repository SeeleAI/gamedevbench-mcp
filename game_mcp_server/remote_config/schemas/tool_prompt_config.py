from typing import Any, Dict

from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import JsonConfig


@nacos_binding(data_id="tool_prompt.json")
class ToolPromptConfig(JsonConfig):
    prompts: Dict[str, str]
    replace_prompts: Dict[str, str]






@nacos_binding(data_id="tool_switch.json")
class ToolSwitchConfig(JsonConfig):
    switch: Dict[str, Any]