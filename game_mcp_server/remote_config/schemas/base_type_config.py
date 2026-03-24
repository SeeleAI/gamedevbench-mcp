from remote_config.schemas.base import ConfigBase


class JsonConfig(ConfigBase):
    pass


class TextConfig(ConfigBase):
    text: str = ""
