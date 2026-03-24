import asyncio
import logging
import traceback
from typing import Any, Awaitable, Callable, Dict, Optional

from .env import parse_global_env
from .loader import to_dataclass
from .nacos_client import NacosClient
from .registry import get_binding_for_class, register_class, get_registered_classes

logger = logging.getLogger(__name__)

_CONFIGS: Dict[type, Any] = {}
_SUBSCRIBERS_ALL: list[Callable[[type, Any], Awaitable[None] | None]] = []
_SUBSCRIBERS_PER_SCOPE: Dict[type, list[Callable[[Any], Awaitable[None] | None]]] = {}
_POLL_TASKS: Dict[type, asyncio.Task] = {}
_LISTENERS: Dict[type, Any] = {}
_LOCK = asyncio.Lock()
_CLIENT: Optional[NacosClient] = None
_CLIENT_INIT_LOCK = asyncio.Lock()
_INIT_TASKS: Dict[type, bool] = {}
_INIT_LOCKS: Dict[type, asyncio.Lock] = {}


def get_all_configs() -> Dict[type, Any]:
    return dict(_CONFIGS)


def subscribe(schema_cls: Optional[type], callback: Callable):
    if schema_cls is None:
        _SUBSCRIBERS_ALL.append(callback)
    else:
        _SUBSCRIBERS_PER_SCOPE.setdefault(schema_cls, []).append(callback)


async def _notify(key, cfg: Any) -> None:
    for cb in _SUBSCRIBERS_ALL:
        res = cb(key, cfg)
        if asyncio.iscoroutine(res):
            await res
    for cb in _SUBSCRIBERS_PER_SCOPE.get(key, []):
        res = cb(cfg)
        if asyncio.iscoroutine(res):
            await res


async def _on_change(schema_cls, content: dict[str, str]) -> None:
    try:
        cfg = to_dataclass(schema_cls, content.get("content", ""))
        logger.info(f"Config updated for {schema_cls}: {cfg}")
        async with _LOCK:
            _CONFIGS[schema_cls] = cfg
        # notify outside of lock to avoid blocking updates
        await _notify(schema_cls, cfg)
    except Exception as e:
        logger.warning(f"Failed to update {schema_cls} config: {e} {traceback.format_exc()}")


async def bootstrap_from_env() -> bool:
    env = parse_global_env()
    if not env.server_addrs:
        return False
    global _CLIENT
    if _CLIENT is None:
        async with _CLIENT_INIT_LOCK:
            if _CLIENT is None:
                _CLIENT = NacosClient(
                    env.server_addrs,
                    namespace=env.namespace,
                    username=env.username,
                    password=env.password,
                )
                await _CLIENT.start()
    return True


async def shutdown() -> None:
    _POLL_TASKS.clear()
    # remove listeners if possible
    global _CLIENT
    if _CLIENT:
        try:
            for scope, entry in list(_LISTENERS.items()):
                try:
                    did, grp, listener = entry
                    await _CLIENT.remove_listener(did, grp, listener)
                except Exception as e:
                    logger.warning(f"Failed to remove listener {e} {traceback.format_exc()}")
        finally:
            _LISTENERS.clear()
            await _CLIENT.shutdown()
            _CLIENT = None


async def ensure_class_initialized(schema_cls: type, data_id: Optional[str] = None, group: Optional[str] = None) -> None:
    if not await bootstrap_from_env():
        return

    register_class(schema_cls)
    b_did, b_grp = get_binding_for_class(schema_cls)
    did = data_id or b_did
    grp = (group or b_grp) or "DEFAULT_GROUP"
    if not did or not grp:
        return

    if schema_cls in _LISTENERS:
        return

    # ensure only one initializer per scope runs
    init_lock = _INIT_LOCKS.setdefault(schema_cls, asyncio.Lock())
    async with init_lock:
        if schema_cls in _LISTENERS:
            return

    try:
        text = await _CLIENT.get_config_text(did, grp)
        if text is not None:
            cfg = to_dataclass(schema_cls, text)
            async with _LOCK:
                _CONFIGS[schema_cls] = cfg
            await _notify(schema_cls, cfg)
    except Exception as e:
        logger.warning(f"Exception encountered: {e} {traceback.format_exc()}")

    loop = asyncio.get_running_loop()
    def listener(content, _schema_cls=schema_cls, _loop=loop):
        asyncio.run(_on_change(_schema_cls, content))
    await _CLIENT.add_listener(did, grp, listener)
    _LISTENERS[schema_cls] = (did, grp, listener)


async def get_config_by_class(schema_cls: type, *, data_id: Optional[str] = None, group: Optional[str] = None):
    if schema_cls not in _CONFIGS and schema_cls not in _LISTENERS and schema_cls not in _INIT_TASKS:
        _INIT_TASKS[schema_cls] = True
        await ensure_class_initialized(schema_cls, data_id, group)
        _INIT_TASKS.pop(schema_cls, None)
    return _CONFIGS.get(schema_cls)


def get_config_cache_by_class(schema_cls: type):
    return _CONFIGS.get(schema_cls)


async def init_all_configs() -> None:
    """Initialize all registered config classes (based on bindings)."""
    # Ensure all schema classes with @nacos_binding are imported and registered
    # (otherwise classes only imported lazily by tools would be missed)
    from . import schemas  # noqa: F401
    if not await bootstrap_from_env():
        return
    for schema_cls in list(get_registered_classes().keys()):
        try:
            await ensure_class_initialized(schema_cls)
        except Exception as e:
            logger.warning(f"Exception encountered: {e} {traceback.format_exc()}")
    logger.info(f"Initialized configs: {list(_CONFIGS.keys())}")

