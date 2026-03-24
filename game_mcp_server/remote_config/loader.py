import json
import logging
import traceback
from typing import Any, Type
from .schemas.base_type_config import JsonConfig, TextConfig as BaseTextConfig

logger = logging.getLogger(__name__)

def _json_to_model(schema_cls: Type[JsonConfig], payload_text: str):
    if not issubclass(schema_cls, JsonConfig):
        raise TypeError("schema_cls must inherit JsonConfig")
    # Use Pydantic's JSON validator with orjson
    try:
        return schema_cls.model_validate_json(payload_text or "{}")
    except Exception as e:
        logger.warning(f"Failed to parse JSON with orjson: {e} {traceback.format_exc()}")
        data: Any
        try:
            data = json.loads(payload_text or "{}")
        except Exception as e:
            logger.warning(f"Failed to parse JSON: {e} {traceback.format_exc()}")
            data = {"text": payload_text or ""}
        else:
            if isinstance(data, str):
                data = {"text": data}
            elif not isinstance(data, dict):
                data = {"text": payload_text or ""}
        if isinstance(data, str):
            data = {"text": data}
        return schema_cls.model_validate(data)


def to_dataclass(schema_cls: Type, payload_text: str):
    if issubclass(schema_cls, JsonConfig):
        return _json_to_model(schema_cls, payload_text)
    if issubclass(schema_cls, BaseTextConfig):
        return schema_cls(text=payload_text or "")
    # default fallback
    try:
        return _json_to_model(schema_cls, payload_text)  # type: ignore[arg-type]
    except Exception:
        if hasattr(schema_cls, "text"):
            return schema_cls(text=payload_text or "")
        raise


def json_to_dataclass(schema_cls: Type, payload_text: str):
    return _json_to_model(schema_cls, payload_text)  # type: ignore[arg-type]


