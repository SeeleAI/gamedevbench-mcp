import logging
from typing import Any

from config import config
from remote_config.schemas.tool_prompt_config import ToolPromptConfig

logger = logging.getLogger(__name__)


def description_auto_replace(tool_name: str, orig_kwargs: dict[str, Any]):
    ori_desc = orig_kwargs.get("description", "")
    tool_prompt_config = ToolPromptConfig.current()
    if config.enable_replace_tool_description:
        prompt = tool_prompt_config.prompts.get(tool_name, "")
        if not prompt:
            logger.warning(f"tool_name={tool_name} not found in replace prompts, use original description")
            prompt = ori_desc
    else:
        prompt = ori_desc
    if tool_prompt_config.replace_prompts:
        for replace_prompt_key, replace_prompt_target in tool_prompt_config.replace_prompts.items():
            prompt = prompt.replace(replace_prompt_key, replace_prompt_target)
    orig_kwargs["description"] = prompt
    logger.info(f"description_auto_replace for tool_name={tool_name}, description={prompt}")
