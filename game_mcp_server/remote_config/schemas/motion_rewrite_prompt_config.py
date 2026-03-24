from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import TextConfig


@nacos_binding(data_id="motion_rewrite_prompt.md")
class MotionRewritePromptConfig(TextConfig):
    pass
