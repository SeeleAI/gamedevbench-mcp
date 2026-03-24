from .provider import (
    bootstrap_from_env,
    shutdown,
    subscribe,
    get_all_configs,
    get_config_by_class,
    get_config_cache_by_class,
    init_all_configs,
)
from .registry import (
    nacos_binding,
    register_class,
    bind_class,
    get_binding_for_class,
    get_registered_classes,
)
from .schemas.base import ConfigBase
from .schemas.base_type_config import JsonConfig, TextConfig

__all__ = [
    "bootstrap_from_env",
    "shutdown",
    "subscribe",
    "get_all_configs",
    "get_config_by_class",
    "get_config_cache_by_class",
    "init_all_configs",
    "nacos_binding",
    "register_class",
    "bind_class",
    "get_binding_for_class",
    "get_registered_classes",
    "ConfigBase",
    "JsonConfig",
    "TextConfig",
]

# Wire provider cache getter to schema base to avoid cross-imports
from .provider import get_config_cache_by_class as _provider_get_cache
ConfigBase.set_get_cache_fn(_provider_get_cache)


