"""Catch-up file: the same code as the notebook's concept cells, up to Part 6.
If a part failed for you, run `from checkpoint import *` in the next part's checkpoint cell.
Generated from the notebook: do not edit by hand."""

import json, os, re, time, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

import agent_core, lifedb, life_tools
from agent_core import run_agent, tool
from providers import load_api_key, open_conversation

PROVIDER, MODEL = "openai", "gpt-6-luna"
load_api_key(PROVIDER)
from openai import OpenAI
client = OpenAI()

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")   # harmless SDK noise
DB = lifedb.create_db()          # Alex's week (dated to this week) + a year of history
WEEK = lifedb.week()
SYSTEM = (
    "You are a personal assistant for Alex, a 44-year-old software developer with a full-time job and two kids, "
    f"who is retraining to become an AI engineer. Today is {WEEK.today}. "
    "Use the tools to look at Alex's calendar, tasks and notes; never guess. Reply briefly."
)

print(f"Ready: {MODEL}, Alex's week {WEEK.label(0)} – {WEEK.label(6)}")


def est_tokens(x) -> int:
    """Rough count: about 4 characters per token."""
    if hasattr(x, "model_dump"):
        x = x.model_dump(exclude_none=True)
    if isinstance(x, dict):                       # opaque blobs (encrypted reasoning/compaction): not readable text
        x = {k: v for k, v in x.items() if k not in ("encrypted_content", "id", "status")}
    text = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)


def zone_of(item) -> str:
    kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
    if kind == "function_call_output":
        return "tool results"
    if kind in ("function_call", "reasoning"):
        return "tool calls"
    return "conversation"


def desk(conv) -> dict:
    """Tokens per zone of everything the model will read on its next call."""
    zones = {"system prompt": est_tokens(conv.system), "tool definitions": est_tokens(conv.tools),
             "conversation": 0, "tool calls": 0, "tool results": 0}
    for item in conv.input:
        zones[zone_of(item)] += est_tokens(item)
    return zones


def show_desk(conv, api_tokens=None, width=40):
    zones = desk(conv)
    total = sum(zones.values())
    for zone, n in zones.items():
        print(f"{zone:17} {n:7,} tok  {n / total:4.0%} {'█' * round(width * n / total)}")
    print(f"{'total (estimate)':17} {total:7,} tok" + (f"   (the API counted {api_tokens:,} on the last call)" if api_tokens else ""))


class ContextBudget:
    def __init__(self, window=6_000, reserve_output=1_000):
        self.window, self.reserve_output = window, reserve_output   # keep room for the answer

    def pressure(self, used: int) -> float:
        return used / (self.window - self.reserve_output)

    def action(self, used: int) -> str:
        p = self.pressure(used)
        if p < 0.50: return "OK"
        if p < 0.70: return "CLEAR old tool results"
        if p < 0.85: return "COMPACT older history"
        return "RESET: notes to memory, fresh desk"


BUDGET = ContextBudget()

REVIEW = (f"Review my last 8 weeks, one week at a time (each Monday to Sunday, the first one starting "
          f"{WEEK.day(-56)}). For each week: hours spent in AI course sessions, number of networking chats, "
          "number of gym sessions. Look up exactly one week per tool call, and before the next lookup write "
          "that week's three numbers in one short line (your notes). "
          "Then tell me in two sentences which week was the least balanced.")


def ground_truth(weeks=8):
    for k in range(weeks, 0, -1):
        start, end = WEEK.day(-7 * k), WEEK.day(-7 * k + 6)
        rows = life_tools.db_rows("SELECT title FROM events WHERE date BETWEEN ? AND ?", (start, end))
        course = 1.5 * sum(r["title"].startswith("AI course") for r in rows)
        chats = sum(r["title"] == "Networking chat" for r in rows)
        gym = sum(r["title"] == "Gym" for r in rows)
        print(f"week of {start}: course {course:4.1f} h · networking {chats} · gym {gym}")


OFFLOAD_DIR = Path("desk_files")


def offload_if_large(name: str, output: str, max_tokens: int = 150) -> str:
    if est_tokens(output) <= max_tokens:
        return output
    OFFLOAD_DIR.mkdir(exist_ok=True)
    handle = f"{name}-{len(list(OFFLOAD_DIR.glob('*.txt'))) + 1}.txt"
    (OFFLOAD_DIR / handle).write_text(output, encoding="utf-8")
    preview = "\n".join(output.splitlines()[:6])
    return (f"[{est_tokens(output):,} tokens saved as '{handle}'. Use grep_file(handle, pattern) to search it.]\n"
            f"{preview}\n...")


class GrepIn(BaseModel):
    handle: str = Field(description="The handle of a saved output, e.g. 'list_events-1.txt'")
    pattern: str = Field(description="Regular expression, e.g. 'Gym' or 'AI course'")


def grep_file(handle: str, pattern: str) -> str:
    path = (OFFLOAD_DIR / handle).resolve()
    if path.parent != OFFLOAD_DIR.resolve() or not path.exists():
        raise ValueError(f"No saved output called '{handle}'.")
    hits = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if re.search(pattern, line, re.I)]
    return f"{len(hits)} matching lines\n" + "\n".join(hits[:30])


def offloaded(tools: dict) -> dict:
    wrapped = {name: {**e, "fn": (lambda _fn=e["fn"], _name=name, **kw: offload_if_large(_name, _fn(**kw)))}
               for name, e in tools.items()}
    wrapped["grep_file"] = tool(grep_file, input_model=GrepIn, description=
        "Search a saved tool output (by its handle) for lines matching a regex pattern. "
        "Returns how many lines match, and the lines. Search several things at once with |, e.g. 'Gym|AI course'.")
    return wrapped


CLEARED = ("[cleared to save space: you already read this result and wrote down what you need in your notes. "
           "Call the tool again only if you need a detail that is not in your notes.]")


def clear_old_tool_results(conv, keep: int = 2, never=("memory",)) -> None:
    """Replace all but the newest `keep` tool results. The calls stay on the desk."""
    names = {i.call_id: i.name for i in conv.input if getattr(i, "type", None) == "function_call"}
    results = [i for i in conv.input if isinstance(i, dict) and i.get("type") == "function_call_output"
               and names.get(i["call_id"]) not in never]
    for item in results[:-keep] if keep else results:
        item["output"] = CLEARED


def run_review(tools, manage=None, label=""):
    log = []
    def before_call(conv, turn):
        if manage:
            manage(conv)
        log.append(sum(desk(conv).values()))
    r = run_agent(REVIEW, tools, system=SYSTEM, model=MODEL, max_turns=30, verbose=False,
                  extra={"parallel_tool_calls": False}, before_call=before_call)
    return {"label": label, "log": log, "result": r}


def bars(run, scale=150):
    limit = BUDGET.window - BUDGET.reserve_output
    print(f"\n{run['label']}  (peak {max(run['log']):,} tokens, {run['result'].turns} steps)")
    for i, n in enumerate(run["log"], 1):
        print(f"  step {i:2} {n:6,} {'█' * (n // scale)}{'  ⚠ over the desk' if n > limit else ''}")


CHAT_SYSTEM = (
    "You are Alex's personal assistant. Alex is a 44-year-old developer with a full-time job and two kids, "
    f"retraining as an AI engineer. This chat runs through the week that starts on {WEEK.today}; "
    "every message starts with its day and time. Keep answers short: at most 80 words."
)

ALEX_WEEK = [
    ("Mon 07:45", "Morning! Context for this week: my partner is travelling Wednesday and Thursday, so I'm on my own "
                  "with the kids. No calls between 18:00 and 20:00 on those days."),
    ("Mon 12:30", "Lunch break. In what order should I tackle my capstone tasks? The RAG pipeline scares me."),
    ("Mon 21:10", "Coffee chat with Priya went great. She'll refer me to Kestrel Labs if I send her my resume by Friday."),
    ("Tue 12:10", "Give me 3 good questions to ask the Northwind recruiter tonight."),
    ("Tue 21:15", "Recruiter screen done! Next step: a take-home assignment, due next Wednesday, about 5 hours of work."),
    ("Wed 07:10", "Dentist in an hour. Honestly, what should I prioritise today?"),
    ("Wed 22:00", "Mock interview feedback: my STAR stories are too long. I should aim for 2 minutes each."),
    ("Thu 06:40", "Skipping the gym this morning to work on the RAG pipeline. Bad idea?"),
    ("Thu 21:30", "The RAG pipeline works! Retrieval accuracy went from 62% to 81% after I added reranking."),
    ("Thu 22:15", "Draft 3 bullet points for tomorrow's demo intro, please."),
]

PROBES = [
    ("(Fri 08:00) Remind me: on which evenings was I unavailable for calls this week, and from when to when?",
     lambda a: "18" in a and "20" in a),
    ("(Fri 08:05) By when do I need to send my resume to Priya?", lambda a: "friday" in a or "today" in a),
    ("(Fri 08:10) When is the Northwind take-home due, and how long will it take?",
     lambda a: "wednesday" in a and ("5" in a or "five" in a)),
    ("(Fri 08:15) What was the feedback from my mock interview?", lambda a: "2 minutes" in a or "two minutes" in a),
    ("(Fri 08:20) What retrieval accuracy did my RAG pipeline reach?", lambda a: "81" in a),
]


class ChatSession:
    """A chatbot: the desk is the list of messages. A strategy may tidy it before every call."""

    def __init__(self, strategy=None, extra=None, native=False):
        self.messages, self.strategy, self.extra, self.native, self.log = [], strategy, extra or {}, native, []

    def say(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        if self.strategy:
            self.messages = self.strategy(self.messages)
        r = client.responses.create(model=MODEL, instructions=CHAT_SYSTEM, input=self.messages,
                                    max_output_tokens=2000, reasoning={"effort": "low"}, **self.extra)
        cached = getattr(r.usage.input_tokens_details, "cached_tokens", 0) or 0
        self.log.append({"input": r.usage.input_tokens, "cached": cached})
        if self.native:
            self.messages += r.output          # keep the API's own items (needed for server-side compaction)
            last = max((i for i, m in enumerate(self.messages) if getattr(m, "type", None) == "compaction"), default=0)
            self.messages = self.messages[last:]   # everything before the newest compaction item is folded into it
        else:
            self.messages.append({"role": "assistant", "content": r.output_text})
        return r.output_text


def play_and_probe(session, label):
    for when, text in ALEX_WEEK:
        session.say(f"({when}) {text}")
    score, answers = 0, []
    for question, check in PROBES:
        answer = session.say(question)
        ok = check(answer.lower())
        score += ok
        answers.append(f"  {'✅' if ok else '❌'} {question}\n     → {answer.strip()[:150]}")
    peak = max(x["input"] for x in session.log)
    total = sum(x["input"] for x in session.log)
    print(f"── {label}: probes {score}/5 · biggest desk {peak:,} tok · {total:,} input tokens in total")
    print("\n".join(answers))
    return {"label": label, "score": score, "peak": peak, "total": total}


GAP = "[Earlier messages were removed to save space.]"


def sliding_window(messages, budget=500, pin_first=1):
    messages = [m for m in messages if m.get("content") != GAP]          # old markers out
    pinned = messages[:pin_first]
    budget -= sum(est_tokens(m) for m in pinned)
    kept = []
    for m in reversed(messages[pin_first:]):
        if est_tokens(m) > budget:
            break
        kept.insert(0, m)
        budget -= est_tokens(m)
    # (agents) never keep a tool result whose call fell off: the API rejects it
    while kept and isinstance(kept[0], dict) and kept[0].get("type") == "function_call_output":
        kept.pop(0)
    dropped = len(messages) - len(pinned) - len(kept)
    return pinned + ([{"role": "user", "content": GAP}] if dropped else []) + kept


SUMMARY_PROMPT = """Summarise this conversation so the assistant can continue WITHOUT the original messages.
Keep: 1) Alex's goals and constraints 2) decisions and why 3) exact facts: numbers, dates, names, deadlines
4) what is done and what is still open. Drop chit-chat. At most 150 words."""
SUMMARY_TAG = "[Summary of the conversation so far]"


class Compactor:
    def __init__(self, threshold=600, keep_last=4):
        self.summary, self.threshold, self.keep_last = "", threshold, keep_last

    def __call__(self, messages):
        if sum(est_tokens(m) for m in messages) < self.threshold:
            return messages
        head, tail = messages[:-self.keep_last], messages[-self.keep_last:]
        head = [m for m in head if not m["content"].startswith(SUMMARY_TAG)]   # the old summary goes in below
        transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in head)
        r = client.responses.create(
            model=MODEL, max_output_tokens=2000, reasoning={"effort": "low"},
            input=f"{SUMMARY_PROMPT}\n<previous>{self.summary}</previous>\n<transcript>\n{transcript}\n</transcript>")
        self.summary = r.output_text.strip()
        return [{"role": "user", "content": f"{SUMMARY_TAG}\n{self.summary}"}] + tail


class FileMemory:
    def __init__(self, root="memories"):
        self.root = Path(root).resolve()
        self.root.mkdir(exist_ok=True)

    def _path(self, p: str) -> Path:                   # block "../../somewhere/else"
        full = (self.root / p.strip().lstrip("/").removeprefix("memories/")).resolve()
        if not full.is_relative_to(self.root):
            raise PermissionError(f"'{p}' is outside the memory folder")
        return full

    def handle(self, command: str, path: str = "", text: str = "", query: str = "") -> str:
        if command == "view":
            target = self._path(path or ".")
            if target.is_dir():                        # the whole drawer: every note, with its content
                notes = [f"## {f.relative_to(self.root)}\n{f.read_text(encoding='utf-8')[:1000]}"
                         for f in sorted(target.rglob("*")) if f.is_file()]
                return "\n\n".join(notes) or "(memory is empty)"
            return target.read_text(encoding="utf-8") if target.exists() else f"No memory file '{path}'."
        if command == "write":
            target = self._path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return f"Saved {target.relative_to(self.root)}"
        if command == "search":
            hits = [f"{f.relative_to(self.root)}: {line}" for f in self.root.rglob("*") if f.is_file()
                    for line in f.read_text(encoding="utf-8").splitlines() if query.lower() in line.lower()]
            return "\n".join(hits) or "(no matches)"
        if command == "delete":                        # the right to be forgotten
            self._path(path).unlink(missing_ok=True)
            return f"Deleted {path}"
        raise ValueError("command must be view, write, search or delete")


class MemoryIn(BaseModel):
    command: Literal["view", "write", "search", "delete"]
    path: str = Field("", description="A file in the memory folder, e.g. 'family.md'. Empty with view = list all files.")
    text: str = Field("", description="For write: the complete new content of the file")
    query: str = Field("", description="For search: the text to look for")


MEMORY = FileMemory()


def memory(command, path="", text="", query=""):
    return MEMORY.handle(command, path, text, query)


MEMORY_TOOL = {"memory": tool(memory, input_model=MemoryIn, description=
    "Alex's long-term memory (a folder of notes). ALWAYS view it first: view with no path shows every note. "
    "Write down anything you will need "
    "in a later conversation: the desk is cleared after every conversation.")}


PRICE = {"input": 0.10, "cached": 0.01, "output": 0.50}      # gpt-6-luna, $ per 1M tokens


def cost(r) -> float:
    uncached = r.input_tokens - r.cached_tokens
    return (uncached * PRICE["input"] + r.cached_tokens * PRICE["cached"] + r.output_tokens * PRICE["output"]) / 1e6


def stamp(conv, turn):
    conv.system = f"Current time: {time.time():.3f}\n" + SYSTEM     # changes every call: breaks the cache


WEEK_PAGE = {
    "type": "object",
    "properties": {"course_hours": {"type": "number"}, "networking_chats": {"type": "integer"},
                   "gym_sessions": {"type": "integer"}, "note": {"type": "string"}},
    "required": ["course_hours", "networking_chats", "gym_sessions", "note"],
    "additionalProperties": False,
}


def run_subagent(k: int) -> dict:
    start, end = WEEK.day(-7 * k), WEEK.day(-7 * k + 6)
    binder = life_tools.list_events_raw(start, end)                                # the messy work
    intern = open_conversation(PROVIDER, MODEL, f"Events of the week {start} to {end}:\n{binder}", effort="low",
                               system="Count: hours of 'AI course' sessions (1.5 h each), number of 'Networking chat' "
                                      "events, number of 'Gym' events. note: one short sentence about the week.")
    page = {"week": start, **intern.complete_json(WEEK_PAGE)}
    assert est_tokens(page) <= 150, "the contract: one small page"
    return page
