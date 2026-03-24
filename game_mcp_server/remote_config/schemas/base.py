from typing import Optional, Type, TypeVar, Callable, Any

from pydantic import BaseModel, ConfigDict


T = TypeVar("T", bound="ConfigBase")


class ConfigBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Provider-independent cache accessor to avoid circular imports
    _get_cache_fn: Callable[[Type], Any] | None = None

    @classmethod
    def set_get_cache_fn(cls, fn: Callable[[Type], Any]) -> None:
        cls._get_cache_fn = fn

    @classmethod
    def current(cls: Type[T]) -> Optional[T]:
        """Return the latest cached config instance for this schema class (no init)."""
        # Lazy import to avoid circular dependency: provider -> loader -> base
        from ..registry import register_class
        register_class(cls)
        getter = cls._get_cache_fn
        cfg = getter(cls) if getter else None
        if isinstance(cfg, cls):
            return cfg
        return None
