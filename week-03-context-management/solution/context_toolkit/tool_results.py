"""Tool output: a sticky note, not the binder."""

import re
from pathlib import Path

from ._items import field, kind
from .budget import est_tokens

CLEARED = ("[cleared to save space: you already read this result and wrote down what you need in your notes. "
           "Call the tool again only if you need a detail that is not in your notes.]")


def offload_if_large(name: str, output: str, folder: Path, max_tokens: int = 500, preview_lines: int = 6) -> str:
    if est_tokens(output) <= max_tokens:
        return output
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    handle = f"{name}-{len(list(folder.glob('*.txt'))) + 1}.txt"
    (folder / handle).write_text(output, encoding="utf-8")
    preview = "\n".join(output.splitlines()[:preview_lines])
    return (f"[{est_tokens(output):,} tokens saved as '{handle}'. Use grep_file(handle, pattern) to search it.]\n"
            f"{preview}\n...")


def grep_file(handle: str, pattern: str, folder: Path, max_lines: int = 30) -> str:
    folder = Path(folder).resolve()
    path = (folder / handle).resolve()
    if path.parent != folder or not path.exists():
        raise ValueError(f"No saved output called '{handle}'.")
    hits = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if re.search(pattern, line, re.I)]
    return f"{len(hits)} matching lines\n" + "\n".join(hits[:max_lines])


def clear_old_tool_results(items: list, keep: int = 2, never: tuple = ("memory",)) -> int:
    """Replace all but the newest `keep` tool results (in place). The calls stay. Returns how many were cleared."""
    names = {field(i, "call_id"): field(i, "name") for i in items if kind(i) == "function_call"}
    results = [i for i in items if isinstance(i, dict) and kind(i) == "function_call_output"
               and names.get(i["call_id"]) not in never and i.get("output") != CLEARED]
    old = results[:-keep] if keep else results
    for item in old:
        item["output"] = CLEARED
    return len(old)
