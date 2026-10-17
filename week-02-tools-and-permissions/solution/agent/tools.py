"""The assistant's tools over the life database.

Every tool = a Pydantic input model (-> JSON schema for the model AND validation for us)
+ a function + an `effect` (read | write | destructive) that permissions.py uses.
"""

import ast
import operator
import re
import sqlite3
from datetime import date as _date
from typing import Annotated, Any, Callable, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import config, db
from .providers import ToolResult
from .reliability import TransientError, with_retries, with_timeout

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"


class FatalToolError(Exception):
    """Raise when the run must stop: continuing can't help (e.g. the database is gone)."""


# ---------------------------------------------------------------- argument types

def _check_date(v: str) -> str:
    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"'{v}' is not a date. Use YYYY-MM-DD, e.g. '2026-10-13' "
                         f"(today is {config.TODAY})") from None
    return v


def _check_time(v: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError(f"'{v}' is not a time. Use 24h HH:MM, e.g. '14:30'")
    return v


Date = Annotated[str, AfterValidator(_check_date), Field(description="YYYY-MM-DD")]
Time = Annotated[str, AfterValidator(_check_time), Field(description="HH:MM, 24-hour clock")]
Category = Literal["work", "course", "job_search", "networking", "family", "health", "personal", "social"]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are an error, not silently ignored


# ---------------------------------------------------------------- helpers

def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = db.ro()
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc):
            raise TransientError(str(exc)) from exc
        raise
    finally:
        conn.close()


def _table(rows: list, columns: list[str], *, limit: int = config.MAX_ROWS, hint: str = "") -> str:
    """Compact TSV, capped. The note tells the model HOW to get the rest."""
    if not rows:
        return "(no rows)"
    lines = ["\t".join(columns)] + ["\t".join(str(r[c]) for c in columns) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... showing {limit} of {len(rows)} rows. {hint}".rstrip())
    return "\n".join(lines)


def _minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _conflicts(day: str, start: str, end: str, ignore_id: int | None = None) -> list[sqlite3.Row]:
    rows = db.rw().execute("SELECT * FROM events WHERE date = ? AND start < ? AND end > ? ORDER BY start",
                           (day, end, start)).fetchall()
    return [r for r in rows if r["id"] != ignore_id]


def _describe(e: Any) -> str:
    return f"#{e['id']} '{e['title']}' {e['date']} {e['start']}-{e['end']}"


EVENT_COLS = ["id", "date", "start", "end", "title", "category", "location"]
TASK_COLS = ["id", "title", "course", "due", "est_hours", "priority", "status"]


# ---------------------------------------------------------------- read tools

class ListEventsIn(Args):
    start_date: Date
    end_date: Date


def list_events(start_date: str, end_date: str) -> str:
    rows = _query("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start", (start_date, end_date))
    return _table(rows, EVENT_COLS, hint="Narrow the date range, or use run_sql with COUNT/GROUP BY.")


class ListTasksIn(Args):
    status: Literal["todo", "done", "all"] = "todo"
    due_before: Date | None = Field(None, description="Only tasks due strictly before this date (YYYY-MM-DD)")


def list_tasks(status: str = "todo", due_before: str | None = None) -> str:
    sql, params = "SELECT * FROM tasks WHERE 1=1", []
    if status != "all":
        sql += " AND status = ?"
        params.append(status)
    if due_before:
        sql += " AND due < ?"
        params.append(due_before)
    rows = _query(sql + " ORDER BY due, priority", tuple(params))
    total = sum(r["est_hours"] for r in rows)
    # Return what the agent needs next: the total, so it doesn't have to add up decimals.
    return _table(rows, TASK_COLS) + f"\nTOTAL est_hours: {total:g} ({len(rows)} tasks)"


class FreeSlotsIn(Args):
    date: Date
    day_start: Time = "06:00"
    day_end: Time = "22:30"
    min_minutes: int = Field(30, ge=5, le=600, description="Shortest slot worth reporting")


def free_slots(date: str, day_start: str = "06:00", day_end: str = "22:30", min_minutes: int = 30) -> str:
    """Interval arithmetic belongs in code, not in the model's head (remember Tuesday's overlap)."""
    lo, hi = _minutes(day_start), _minutes(day_end)
    busy = sorted((max(_minutes(r["start"]), lo), min(_minutes(r["end"]), hi))
                  for r in _query("SELECT start, end FROM events WHERE date = ?", (date,)))
    slots, cursor = [], lo
    for start, end in busy:
        if end <= start:
            continue
        if start - cursor >= min_minutes:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if hi - cursor >= min_minutes:
        slots.append((cursor, hi))
    if not slots:
        return f"No free slot of {min_minutes}+ min on {date} between {day_start} and {day_end}."
    total = sum(e - s for s, e in slots)
    return "\n".join(f"{_hhmm(s)}-{_hhmm(e)} ({(e - s) / 60:g} h)" for s, e in slots) + \
        f"\nTOTAL free: {total / 60:g} h"


NOTES = sorted(p.name for p in (config.LIFE_DIR / "notes").glob("*.txt"))  # same names every week


def _check_note(v: str) -> str:
    if v not in NOTES:
        raise ValueError(f"Unknown note '{v}'. Choose one of: {', '.join(NOTES)}")
    return v


class ReadNoteIn(Args):
    # an enum in the schema: the model sees exactly which notes exist; the validator enforces it
    name: Annotated[str, AfterValidator(_check_note), Field(json_schema_extra={"enum": [*NOTES]})]


def read_note(name: str) -> str:
    return (config.DATA_DIR / "notes" / name).read_text(encoding="utf-8")


class RunSqlIn(Args):
    query: str = Field(description="One SQLite SELECT statement")


def run_sql(query: str) -> str:
    try:
        rows = _query(query)
    except sqlite3.Error as exc:
        # Model-fixable: say what went wrong AND what the schema is.
        raise ValueError(f"SQL error: {exc}. Tables: events({', '.join(EVENT_COLS)}); "
                         f"tasks({', '.join(TASK_COLS)})") from None
    columns = list(rows[0].keys()) if rows else []
    return _table(rows, columns, hint="Add a WHERE / LIMIT, or aggregate with COUNT / SUM / GROUP BY.")


_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


class CalculatorIn(Args):
    expression: str = Field(description="e.g. '(3 + 6 + 2.5) * 60'")


def calculator(expression: str) -> str:
    return str(round(_eval_node(ast.parse(expression, mode="eval").body), 6))


# ---------------------------------------------------------------- write tools

class _Slot(Args):
    date: Date
    start: Time
    end: Time

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")
        return self


class CreateEventIn(_Slot):
    title: str = Field(min_length=1, max_length=80)
    category: Category
    location: str = ""


def create_event(date: str, start: str, end: str, title: str, category: str, location: str = "") -> str:
    if clash := _conflicts(date, start, end):
        raise ValueError("Conflicts with " + ", ".join(map(_describe, clash)) +
                         ". Pick another time (see free_slots) or ask the user what to move.")
    cur = db.rw().execute("INSERT INTO events (date, start, end, title, category, location) "
                          "VALUES (?, ?, ?, ?, ?, ?)", (date, start, end, title, category, location))
    return f"Created #{cur.lastrowid} '{title}' {date} {start}-{end}"


def _event(event_id: int) -> sqlite3.Row:
    row = db.rw().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ValueError(f"No event with id {event_id}. Use list_events to find the right id.")
    return row


class MoveEventIn(_Slot):
    event_id: int


def move_event(event_id: int, date: str, start: str, end: str) -> str:
    old = _event(event_id)
    if clash := _conflicts(date, start, end, ignore_id=event_id):
        raise ValueError("Conflicts with " + ", ".join(map(_describe, clash)) + ". Pick another time.")
    db.rw().execute("UPDATE events SET date = ?, start = ?, end = ? WHERE id = ?", (date, start, end, event_id))
    return f"Moved {_describe(old)} -> {date} {start}-{end}"


class EventIdIn(Args):
    event_id: int


def cancel_event(event_id: int) -> str:
    old = _event(event_id)
    db.rw().execute("DELETE FROM events WHERE id = ?", (event_id,))
    return f"Cancelled {_describe(old)}"


class TaskIdIn(Args):
    task_id: int


def complete_task(task_id: int) -> str:
    row = db.rw().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"No task with id {task_id}. Use list_tasks to find the right id.")
    if row["status"] == "done":
        return f"Task #{task_id} '{row['title']}' was already done."  # idempotent: safe to repeat
    db.rw().execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    return f"Marked #{task_id} '{row['title']}' as done"


# ---------------------------------------------------------------- registry

def tool(fn: Callable[..., str], input_model: type[BaseModel], description: str, effect: str = READ) -> dict:
    def run(**kwargs: Any) -> str:
        args = input_model.model_validate(kwargs)
        return str(fn(**dict(args)))
    if effect == READ:
        run = with_retries(run)  # reads are idempotent: safe to retry. Writes are NOT retried.
    return {"fn": with_timeout(run), "effect": effect,
            "schema": {"name": fn.__name__, "description": description,
                       "input_schema": input_model.model_json_schema()}}


TOOLS: dict[str, dict[str, Any]] = {
    "list_events": tool(list_events, ListEventsIn,
        "List calendar events between two dates (inclusive), ordered by time. Shows each event's id, "
        "which you need to move or cancel it."),
    "list_tasks": tool(list_tasks, ListTasksIn,
        "List tasks (default: open ones), optionally only those due before a date. "
        "Includes the total estimated hours."),
    "free_slots": tool(free_slots, FreeSlotsIn,
        "Free time on one day between day_start and day_end (default 06:00-22:30), with overlapping "
        "events already merged. "
        "Use this instead of computing free time yourself."),
    "read_note": tool(read_note, ReadNoteIn,
        "Read one of Alex's notes: AI course syllabus, personal preferences, job-search pipeline."),
    "run_sql": tool(run_sql, RunSqlIn,
        "Read-only SQL over the full history for questions the other tools can't answer "
        "(counts, trends, past months). Tables: events(id, date, start, end, title, category, "
        "location), tasks(id, title, course, due, est_hours, priority, status)."),
    "calculator": tool(calculator, CalculatorIn,
        "Evaluate an arithmetic expression exactly: + - * / ** % and parentheses."),
    "create_event": tool(create_event, CreateEventIn,
        "Add an event to the calendar. Fails if it overlaps an existing event.", WRITE),
    "move_event": tool(move_event, MoveEventIn,
        "Move an existing event (by id) to a new date and time. Fails on overlap.", WRITE),
    "complete_task": tool(complete_task, TaskIdIn, "Mark a task (by id) as done.", WRITE),
    "cancel_event": tool(cancel_event, EventIdIn,
        "Delete an event (by id) from the calendar. Cannot be undone.", DESTRUCTIVE),
}


def tool_schemas(tools: dict[str, dict[str, Any]] = TOOLS) -> list[dict[str, Any]]:
    return [t["schema"] for t in tools.values()]


def execute_tool(call: Any, tools: dict[str, dict[str, Any]] = TOOLS) -> ToolResult:
    """One tool call -> one ToolResult. Errors go back to the model; FatalToolError ends the run."""
    entry = tools.get(call.name)
    if entry is None:
        return ToolResult(call.id, f"Unknown tool '{call.name}'. Available: {', '.join(tools)}", True)
    try:
        return ToolResult(call.id, entry["fn"](**call.input))
    except FatalToolError:
        raise
    except ValidationError as exc:
        problems = [f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors()]
        return ToolResult(call.id, "Invalid arguments. " + "; ".join(problems), True)
    except Exception as exc:
        return ToolResult(call.id, f"{type(exc).__name__}: {exc}", True)
