"""The loop from weeks 1-2, packaged as a module. Week 2 added:

  * `tool()`        - one Pydantic model gives both the JSON schema AND the validation
  * `run_tools()`   - read-only tool calls run in parallel, writes run one at a time
  * FatalToolError  - a tool can stop the whole run when continuing makes no sense

Week 3 adds one hook: `before_call(conv, turn)` runs before every model call, so you can
inspect or tidy the desk (the conversation) between steps. `Result.conv` keeps the
conversation and `Result.steps` the token usage of every call.

It talks to the model only through providers.py.
Read it: `import inspect; print(inspect.getsource(agent_core.run_tools))`
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from providers import ToolResult, open_conversation

PROVIDER = "openai"
MODEL = "gpt-6-luna"

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"


class FatalToolError(Exception):
    """Raise from a tool when the run must stop (e.g. the database is gone)."""


# ---------------------------------------------------------------- tools

def tool(fn: Callable, *, description: str, input_model: type[BaseModel], effect: str = READ,
         name: str | None = None) -> dict:
    """Build a registry entry. The Pydantic model is the single source of truth:
    the model sees its JSON schema, and our code validates every call against it.
    The tool's name (what the model calls) is the function's name, unless you pass `name`."""
    def run(**kwargs: Any) -> str:
        args = input_model.model_validate(kwargs)       # raises ValidationError on bad input
        return str(fn(**dict(args)))
    return {
        "fn": run,
        "effect": effect,
        "schema": {"name": name or fn.__name__, "description": description,
                   "input_schema": input_model.model_json_schema()},
    }


def tool_schemas(tools: dict) -> list[dict]:
    for key, entry in tools.items():          # the model calls a tool by the schema's name, we look it up by key
        if entry["schema"]["name"] != key:
            raise ValueError(f"Tool registry key '{key}' doesn't match the tool's name "
                             f"'{entry['schema']['name']}', which is what the model will call. "
                             f"Use the same name, e.g. tool(..., name='{key}').")
    return [t["schema"] for t in tools.values()]


def _format_validation_error(exc: ValidationError) -> str:
    problems = [f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors()]
    return "Invalid arguments. " + "; ".join(problems)


def execute_tool(call: Any, tools: dict) -> ToolResult:
    """One tool call -> one ToolResult. Errors go back to the model,
    except FatalToolError, which propagates and ends the run."""
    entry = tools.get(call.name)
    if entry is None:
        return ToolResult(call.id, f"Unknown tool '{call.name}'. Available: {', '.join(tools)}", True)
    try:
        return ToolResult(call.id, entry["fn"](**call.input))
    except FatalToolError:
        raise
    except ValidationError as exc:
        return ToolResult(call.id, _format_validation_error(exc), True)
    except Exception as exc:
        return ToolResult(call.id, f"{type(exc).__name__}: {exc}", True)


def run_tools(calls: list, tools: dict, *, parallel: bool = True) -> list[ToolResult]:
    """Run all tool calls from one model reply. Results keep the order of the calls.

    Only an all-read batch runs in parallel: writes may depend on each other and
    approval prompts must not interleave on the user's screen."""
    all_reads = all(tools.get(c.name, {}).get("effect") == READ for c in calls)
    if parallel and all_reads and len(calls) > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda c: execute_tool(c, tools), calls))
    return [execute_tool(c, tools) for c in calls]


# ---------------------------------------------------------------- loop

@dataclass
class Result:
    answer: str
    stop: str
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    seconds: float = 0.0
    cached_tokens: int = 0
    steps: list[dict] = field(default_factory=list)   # per call: input / cached / output tokens
    conv: Any = None                                   # the conversation: the desk after the run


def _short(x: Any, n: int = 200) -> str:
    s = str(x).replace("\n", " | ")
    return s if len(s) <= n else s[:n] + "..."


def run_agent(task: str, tools: dict, *, system: str, provider: str = PROVIDER, model: str = MODEL,
              effort: str | None = None, max_turns: int = 10, parallel: bool = True,
              verbose: bool = True, client: Any = None, extra: dict | None = None,
              before_call: Callable[[Any, int], None] | None = None) -> Result:
    conv = open_conversation(provider, model, task, tools=tool_schemas(tools), system=system,
                             effort=effort, client=client, extra=extra)
    res = Result("", "", 0, conv=conv)
    t0 = time.perf_counter()

    for turn in range(1, max_turns + 1):
        res.turns = turn
        if before_call:
            before_call(conv, turn)        # look at / tidy the desk before the model reads it
        step = conv.ask()
        res.input_tokens += step.input_tokens
        res.output_tokens += step.output_tokens
        res.cached_tokens += step.cached_tokens
        res.steps.append({"turn": turn, "input": step.input_tokens, "cached": step.cached_tokens,
                          "output": step.output_tokens})
        if verbose:
            print(f"\n── turn {turn} · stop={step.stop} · in={step.input_tokens} "
                  f"(cached {step.cached_tokens}) out={step.output_tokens}")
            if step.text:
                print("  💬", _short(step.text, 300))
            for c in step.tool_calls:
                print(f"  🔧 {c.name}({json.dumps(c.input, ensure_ascii=False)})")

        if step.stop == "tool_use":
            res.tool_calls += [c.name for c in step.tool_calls]
            try:
                results = run_tools(step.tool_calls, tools, parallel=parallel)
            except FatalToolError as exc:
                res.answer, res.stop = f"[run stopped: {exc}]", "fatal"
                break
            if verbose:
                for x in results:
                    print("  ❌" if x.is_error else "  ✅", _short(x.content))
            conv.add_tool_results(results)
            continue

        res.answer, res.stop = {
            "max_tokens": (step.text + "\n[cut off: max_tokens]", "max_tokens"),
            "refusal": ("[the model declined this request]", "refusal"),
        }.get(step.stop, (step.text, step.stop))
        break
    else:
        res.answer, res.stop = f"[stopped after {max_turns} turns]", "max_turns"

    res.seconds = time.perf_counter() - t0
    return res


def first_tool(task: str, tools: dict, *, system: str, provider: str = PROVIDER, model: str = MODEL,
               client: Any = None) -> str:
    """Which tool does the model reach for FIRST? One call, nothing executed. For evals."""
    conv = open_conversation(provider, model, task, tools=tool_schemas(tools), system=system,
                             effort="low", client=client)
    step = conv.ask()
    return step.tool_calls[0].name if step.tool_calls else "(no tool)"
