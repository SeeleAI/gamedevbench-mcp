from typing import Dict, Optional, Type, Callable, Tuple, TypeVar


_CLASS_BINDINGS: Dict[Type, Tuple[Optional[str], Optional[str]]] = {}


def register_class(schema_cls: Type) -> None:
    if schema_cls not in _CLASS_BINDINGS:
        _CLASS_BINDINGS[schema_cls] = (None, None)


def bind_class(schema_cls: Type, data_id: str, group: str) -> None:
    _CLASS_BINDINGS[schema_cls] = (data_id, group)


C = TypeVar("C", bound=type)

def nacos_binding(data_id: str, group: Optional[str] = "DEFAULT_GROUP") -> Callable[[C], C]:
    def decorator(cls: C) -> C:
        register_class(cls)
        if data_id and group:
            bind_class(cls, data_id, group)
        return cls
    return decorator


def get_binding_for_class(schema_cls: Type) -> Tuple[Optional[str], Optional[str]]:
    return _CLASS_BINDINGS.get(schema_cls, (None, None))


def get_registered_classes() -> Dict[Type, Tuple[Optional[str], Optional[str]]]:
    return dict(_CLASS_BINDINGS)


