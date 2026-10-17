"""Every technique, tested without an API key: the model is replaced by small fakes."""

import json
from types import SimpleNamespace as NS

import pytest

from context_toolkit import (CLEARED, GAP, Compactor, ContextBudget, FileMemory, clear_old_tool_results, desk,
                             est_tokens, grep_file, offload_if_large, run_subagents, sliding_window)
from context_toolkit.manager import ContextManager
from context_toolkit.subagents import ContractBroken


def msg(role, text):
    return {"role": role, "content": text}


def call(call_id, name):                       # the model's tool call: an SDK object, not a dict
    return NS(type="function_call", call_id=call_id, name=name, arguments="{}")


def result(call_id, text):
    return {"type": "function_call_output", "call_id": call_id, "output": text}


# ---------- budget ----------

@pytest.mark.parametrize("used, action", [(0, "OK"), (49, "OK"), (50, "CLEAR"), (69, "CLEAR"),
                                          (70, "COMPACT"), (84, "COMPACT"), (85, "RESET"), (120, "RESET")])
def test_ladder_thresholds(used, action):
    assert ContextBudget(window=110, reserve_output=10).action(used) == action


def test_desk_zones_and_opaque_fields():
    items = [msg("user", "hi"), call("c1", "list_events"), result("c1", "x" * 400),
             {"type": "reasoning", "encrypted_content": "z" * 10_000, "summary": []}]
    zones = desk("system", [{"name": "t"}], items)
    assert zones["tool results"] > zones["conversation"]
    assert zones["tool calls"] < 100                       # the encrypted blob is not counted


# ---------- sliding window ----------

def test_window_pins_brief_marks_gap_and_keeps_newest():
    msgs = [msg("user", "BRIEF")] + [msg("user" if i % 2 else "assistant", f"m{i} " + "x" * 80) for i in range(10)]
    out = sliding_window(msgs, budget=100)
    assert out[0]["content"] == "BRIEF" and out[1]["content"] == GAP
    assert out[-1] is msgs[-1]
    assert sum(m["content"] == GAP for m in sliding_window(out + [msg("user", "next")], budget=100)) == 1


def test_window_never_starts_with_an_orphan_tool_result():
    msgs = [msg("user", "BRIEF"), msg("user", "x" * 400), call("c1", "t"), result("c1", "y" * 40), msg("user", "q")]
    out = sliding_window(msgs, budget=40, count=lambda m: 30 if isinstance(m, dict) and m.get("type") else est_tokens(m))
    kinds = [getattr(m, "type", None) or m.get("type") or m.get("role") for m in out]
    assert "function_call_output" not in kinds[:3] or kinds[kinds.index("function_call_output") - 1] == "function_call"


# ---------- compaction ----------

def test_compaction_keeps_tail_verbatim_and_is_incremental():
    prompts = []
    def fake_llm(prompt):
        prompts.append(prompt)
        return f"summary #{len(prompts)}"
    comp = Compactor(fake_llm, threshold=50, keep_last=4)
    msgs = [msg("user" if i % 2 == 0 else "assistant", f"turn {i} " + "x" * 60) for i in range(9)]
    out = comp(msgs)
    assert out[1:] == msgs[-4:] and "summary #1" in out[0]["content"]
    out2 = comp(out + [msg("assistant", "a" * 60), msg("user", "b" * 60)])
    assert "<previous>summary #1</previous>" in prompts[1]          # the old summary goes in
    assert "summary #2" in out2[0]["content"]
    assert prompts[1].count("[Summary of the conversation so far]") == 0   # ...but not twice


def test_compaction_does_nothing_below_threshold():
    msgs = [msg("user", "hi")]
    assert Compactor(lambda p: pytest.fail("should not call the model"), threshold=1000)(msgs) == msgs


# ---------- tool results ----------

def test_clear_keeps_newest_and_never_memory():
    items = [call("c1", "list_events"), result("c1", "week 1"), call("m1", "memory"), result("m1", "notes"),
             call("c2", "list_events"), result("c2", "week 2"), call("c3", "list_events"), result("c3", "week 3")]
    assert clear_old_tool_results(items, keep=2) == 1
    outputs = {i["call_id"]: i["output"] for i in items if isinstance(i, dict)}
    assert outputs == {"c1": CLEARED, "m1": "notes", "c2": "week 2", "c3": "week 3"}
    assert sum(getattr(i, "type", None) == "function_call" for i in items) == 4     # the calls stay
    assert clear_old_tool_results(items, keep=2) == 0                               # idempotent


def test_offload_and_grep(tmp_path):
    small = offload_if_large("t", "short", tmp_path)
    assert small == "short"
    big = json.dumps([{"title": "Gym"}, {"title": "Work"}] * 200, indent=1)
    note = offload_if_large("list_events", big, tmp_path, max_tokens=100)
    assert "saved as 'list_events-1.txt'" in note and est_tokens(note) < 100
    assert grep_file("list_events-1.txt", "Gym", tmp_path).startswith("200 matching lines")
    with pytest.raises(ValueError):
        grep_file("../secret.txt", "x", tmp_path)


# ---------- memory ----------

def test_memory_write_view_search_delete(tmp_path):
    mem = FileMemory(tmp_path / "memories")
    assert mem.handle("view") == "(memory is empty)"
    mem.handle("write", "family.md", "Partner away Wed-Thu; I do drop-off at 8:00")
    assert mem.handle("view").startswith("## family.md\nPartner away")   # the drawer shows content, not just names
    assert "drop-off" in mem.handle("view", "/memories/family.md")
    assert mem.handle("search", query="DROP-OFF").startswith("family.md:")
    mem.handle("delete", "family.md")
    assert mem.handle("view") == "(memory is empty)"


@pytest.mark.parametrize("path", ["../outside.txt", "/../../etc/passwd", "a/../../x"])
def test_memory_path_guard(tmp_path, path):
    with pytest.raises(PermissionError):
        FileMemory(tmp_path / "memories").handle("write", path, "x")


# ---------- sub-agents ----------

def test_subagents_return_small_pages_in_order():
    pages = run_subagents(lambda week: {"week": week, "gym": week % 3}, [1, 2, 3, 4])
    assert [p["week"] for p in pages] == [1, 2, 3, 4]


def test_subagent_contract_is_enforced():
    with pytest.raises(ContractBroken):
        run_subagents(lambda job: "x" * 5_000, [1], max_tokens=300)


# ---------- the ladder as a hook ----------

def test_manager_clears_then_compacts():
    items = [msg("user", "task")] + [x for i in range(6) for x in (call(f"c{i}", "t"), result(f"c{i}", "y" * 400))]
    conv = NS(system="s", tools=[], input=items)
    compacted = []
    manager = ContextManager(ContextBudget(window=800, reserve_output=0),
                             compact=lambda its: compacted.append(len(its)) or its[-4:], keep=2)
    manager(conv, 1)
    assert manager.history[0][1] in ("COMPACT", "RESET")
    assert compacted and len(conv.input) == 4
