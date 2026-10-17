"""Alex's read tools from week 2, as a module (same code as the week 2 notebook).

    TOOLS          the tidy tools: capped, compact outputs
    BINDER_TOOLS   one tool that returns everything as JSON, like an honest but careless API.
                   Its outputs are the "binders" that fill the desk in this week's experiments.
"""

import json
import re
import sqlite3
from datetime import date as _date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

import lifedb
from agent_core import FatalToolError, tool

MAX_ROWS = 40
EVENT_COLS = ["id", "date", "start", "end", "title", "category", "location"]
TASK_COLS = ["id", "title", "course", "due", "est_hours", "priority", "status"]


def _check_date(v: str) -> str:
    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"'{v}' is not a date. Use YYYY-MM-DD (today is {lifedb.week().today})") from None
    return v


def _check_time(v: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError(f"'{v}' is not a time. Use 24h HH:MM, e.g. '14:30'")
    return v


Date = Annotated[str, AfterValidator(_check_date), Field(description="YYYY-MM-DD")]
Time = Annotated[str, AfterValidator(_check_time), Field(description="HH:MM, 24-hour clock")]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


def db_rows(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    if not lifedb.DB_PATH.exists():
        raise FatalToolError(f"database not found at {lifedb.DB_PATH}")
    conn = lifedb.connect(lifedb.DB_PATH, readonly=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def table(rows, columns, limit=MAX_ROWS, hint=""):
    if not rows:
        return "(no rows)"
    lines = ["\t".join(columns)] + ["\t".join(str(r[c]) for c in columns) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... showing {limit} of {len(rows)} rows. {hint}".rstrip())
    return "\n".join(lines)


def _minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _hhmm(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


class ListEventsIn(Args):
    start_date: Date
    end_date: Date


def list_events(start_date: str, end_date: str) -> str:
    rows = db_rows("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start", (start_date, end_date))
    return table(rows, EVENT_COLS, hint="Narrow the date range, or use run_sql with COUNT/GROUP BY.")


def list_events_raw(start_date: str, end_date: str) -> str:
    rows = db_rows("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start", (start_date, end_date))
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1)      # everything: a binder


class ListTasksIn(Args):
    status: Literal["todo", "done", "all"] = "todo"
    due_before: Date | None = Field(None, description="Only tasks due strictly before this date")


def list_tasks(status: str = "todo", due_before: str | None = None) -> str:
    sql, params = "SELECT * FROM tasks WHERE 1=1", []
    if status != "all":
        sql, params = sql + " AND status = ?", params + [status]
    if due_before:
        sql, params = sql + " AND due < ?", params + [due_before]
    rows = db_rows(sql + " ORDER BY due", tuple(params))
    return table(rows, TASK_COLS) + f"\nTOTAL est_hours: {sum(r['est_hours'] for r in rows):g} ({len(rows)} tasks)"


class FreeSlotsIn(Args):
    date: Date
    day_start: Time = "06:00"
    day_end: Time = "22:30"
    min_minutes: int = Field(30, ge=5, le=600, description="Shortest slot worth reporting")


def free_slots(date: str, day_start: str = "06:00", day_end: str = "22:30", min_minutes: int = 30) -> str:
    lo, hi = _minutes(day_start), _minutes(day_end)
    busy = sorted((max(_minutes(r["start"]), lo), min(_minutes(r["end"]), hi))
                  for r in db_rows("SELECT start, end FROM events WHERE date = ?", (date,)))
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
    return "\n".join(f"{_hhmm(s)}-{_hhmm(e)} ({(e - s) / 60:g} h)" for s, e in slots) + \
        f"\nTOTAL free: {sum(e - s for s, e in slots) / 60:g} h"


NOTES = sorted(p.name for p in (lifedb.HERE.parent / "life" / "notes").glob("*.txt"))


def _check_note(v: str) -> str:
    if v not in NOTES:
        raise ValueError(f"Unknown note '{v}'. Choose one of: {', '.join(NOTES)}")
    return v


class ReadNoteIn(Args):
    # an enum in the schema: the model sees exactly which notes exist; the validator enforces it
    name: Annotated[str, AfterValidator(_check_note), Field(json_schema_extra={"enum": [*NOTES]})]


def read_note(name: str) -> str:
    return (lifedb.DATA_DIR / "notes" / name).read_text(encoding="utf-8")


class RunSqlIn(Args):
    query: str = Field(description="One SQLite SELECT statement")


def run_sql(query: str) -> str:
    try:
        rows = db_rows(query)
    except sqlite3.Error as exc:
        raise ValueError(f"SQL error: {exc}. Tables: events({', '.join(EVENT_COLS)}); "
                         f"tasks({', '.join(TASK_COLS)})") from None
    return table(rows, list(rows[0].keys()) if rows else [], hint="Aggregate with COUNT / SUM / GROUP BY.")


TOOLS = {
    "list_events": tool(list_events, input_model=ListEventsIn, description=
        "List calendar events between two dates (inclusive), ordered by time. Shows each event's id."),
    "list_tasks": tool(list_tasks, input_model=ListTasksIn, description=
        "List tasks (default: open ones), optionally only those due before a date. Includes the total estimated hours."),
    "free_slots": tool(free_slots, input_model=FreeSlotsIn, description=
        "Free time on one day between day_start and day_end (default 06:00-22:30), overlapping events merged."),
    "read_note": tool(read_note, input_model=ReadNoteIn, description=
        "Read one of Alex's notes: AI course syllabus, personal preferences, job-search pipeline."),
    "run_sql": tool(run_sql, input_model=RunSqlIn, description=
        "Read-only SQL over Alex's calendar and tasks. Tables: events(id, date, start, end, title, category, "
        "location) with date YYYY-MM-DD and times HH:MM; tasks(id, title, course, due, est_hours, priority, status)."),
}

BINDER_TOOLS = {
    "list_events_raw": tool(list_events_raw, input_model=ListEventsIn, description=
        "List calendar events between two dates (inclusive), with all their details, as JSON."),
}
