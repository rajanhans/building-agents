"""The whole ladder as one `before_call(conv, turn)` hook (stretch exercise)."""

from typing import Any, Callable

from .budget import ContextBudget, desk
from .tool_results import clear_old_tool_results


class ContextManager:
    def __init__(self, budget: ContextBudget, compact: Callable[[list], list] | None = None,
                 reset: Callable[[Any], None] | None = None, keep: int = 2):
        self.budget, self.compact, self.reset, self.keep = budget, compact, reset, keep
        self.history: list[tuple[int, str]] = []

    def __call__(self, conv: Any, turn: int) -> None:
        used = sum(desk(conv.system, conv.tools, conv.input).values())
        action = self.budget.action(used)
        if action in ("CLEAR", "COMPACT", "RESET"):
            clear_old_tool_results(conv.input, keep=self.keep)          # cheapest first, always
        if action in ("COMPACT", "RESET") and self.compact:
            conv.input[:] = self.compact(conv.input)
        if action == "RESET" and self.reset:
            self.reset(conv)
        self.history.append((used, action))
