from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import JsonConfig


@nacos_binding(data_id="dify-config.json")
class DifyConfig(JsonConfig):
    thing_gen_key: str
    human_gen_key: str
    motion_gen_key: str
