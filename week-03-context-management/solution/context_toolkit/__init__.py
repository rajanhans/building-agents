"""What's on the desk? Context management techniques from week 3, as a package.

    budget        measure the desk per zone; the escalation ladder
    window        sliding window: pin the brief, cut at safe boundaries, mark the gap
    compaction    the one-page summary (incremental; the summariser is a parameter)
    tool_results  offload at the door + grep; clear old tool results
    memory        the drawer: FileMemory with a path guard
    subagents     send an intern: isolated work with a size contract
    manager       the whole ladder as one `before_call` hook (stretch)
"""

from .budget import ContextBudget, desk, est_tokens
from .compaction import SUMMARY_PROMPT, Compactor
from .memory import FileMemory
from .subagents import run_subagents
from .tool_results import CLEARED, clear_old_tool_results, grep_file, offload_if_large
from .window import GAP, sliding_window

__all__ = ["CLEARED", "GAP", "SUMMARY_PROMPT", "Compactor", "ContextBudget", "FileMemory", "clear_old_tool_results",
           "desk", "est_tokens", "grep_file", "offload_if_large", "run_subagents", "sliding_window"]
