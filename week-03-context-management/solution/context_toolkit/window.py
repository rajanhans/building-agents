"""Sliding window: keep the newest, pin the brief, say what was dropped."""

from typing import Any, Callable

from ._items import field, kind
from .budget import est_tokens

GAP = "[Earlier messages were removed to save space.]"


def sliding_window(messages: list, budget: int, pin_first: int = 1,
                   count: Callable[[Any], int] = est_tokens) -> list:
    messages = [m for m in messages if field(m, "content") != GAP]
    pinned = messages[:pin_first]
    budget -= sum(count(m) for m in pinned)
    kept: list = []
    for m in reversed(messages[pin_first:]):
        if count(m) > budget:
            break
        kept.insert(0, m)
        budget -= count(m)
    while kept and kind(kept[0]) == "function_call_output":   # its call fell off: the API would reject it
        kept.pop(0)
    dropped = len(messages) - len(pinned) - len(kept)
    return pinned + ([{"role": "user", "content": GAP}] if dropped else []) + kept
