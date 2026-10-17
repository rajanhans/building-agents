"""Measure the desk before you manage it."""

import json
from typing import Any

from ._items import kind

OPAQUE = ("encrypted_content", "id", "status")   # not text the model reads


def est_tokens(x: Any) -> int:
    """Rough count: about 4 characters per token. Use the API's usage numbers for exact counts."""
    if hasattr(x, "model_dump"):
        x = x.model_dump(exclude_none=True)
    if isinstance(x, dict):
        x = {k: v for k, v in x.items() if k not in OPAQUE}
    text = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)


def zone_of(item: Any) -> str:
    k = kind(item)
    if k == "function_call_output":
        return "tool results"
    if k in ("function_call", "reasoning"):
        return "tool calls"
    return "conversation"


def desk(system: str, tools: list, items: list) -> dict[str, int]:
    zones = {"system prompt": est_tokens(system), "tool definitions": est_tokens(tools),
             "conversation": 0, "tool calls": 0, "tool results": 0}
    for item in items:
        zones[zone_of(item)] += est_tokens(item)
    return zones


class ContextBudget:
    """The escalation ladder: cheapest first."""

    def __init__(self, window: int = 400_000, reserve_output: int = 16_000):
        self.window, self.reserve_output = window, reserve_output

    def pressure(self, used: int) -> float:
        return used / (self.window - self.reserve_output)

    def action(self, used: int) -> str:
        p = self.pressure(used)
        if p < 0.50:
            return "OK"
        if p < 0.70:
            return "CLEAR"
        if p < 0.85:
            return "COMPACT"
        return "RESET"
