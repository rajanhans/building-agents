"""Conversation items come as dicts (ours) or SDK objects (the model's). Read both the same way."""

from typing import Any


def field(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def kind(item: Any) -> str | None:
    return field(item, "type") or ("message" if field(item, "role") else None)
