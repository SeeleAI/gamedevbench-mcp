from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import TextConfig



@nacos_binding(data_id="screenshots_prompt.md")
class ScreenshotsPromptConfig(TextConfig):
    pass
