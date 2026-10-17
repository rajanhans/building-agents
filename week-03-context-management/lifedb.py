"""The simulated life as a SQLite database: events + tasks.

Alex's current week comes from the course's life/ template, dated to the real calendar
(see simweek.py) and written to data/. A year of generated history before it gives us
a table big enough to flood a context window.
"""

import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from simweek import Week, build_week, sim_monday

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DB_PATH = HERE / "life.db"

SCHEMA = """
CREATE TABLE events (
    id       INTEGER PRIMARY KEY,
    date     TEXT NOT NULL,          -- YYYY-MM-DD
    start    TEXT NOT NULL,          -- HH:MM (24h)
    end      TEXT NOT NULL,          -- HH:MM (24h)
    title    TEXT NOT NULL,
    category TEXT NOT NULL,          -- work | course | job_search | networking | family | health | personal | social
    location TEXT NOT NULL DEFAULT ''
);
CREATE TABLE tasks (
    id        INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    course    TEXT NOT NULL DEFAULT '',
    due       TEXT NOT NULL,         -- YYYY-MM-DD
    est_hours REAL NOT NULL,
    priority  TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    status    TEXT NOT NULL CHECK (status IN ('todo', 'done'))
);
"""


def _history(rng: random.Random, monday: date):
    """A year of plausible past events for Alex: work, gym, kids, the AI course
    (started 7 weeks ago), networking (last 4 months). Everything before `monday`."""
    first, last = monday - timedelta(days=406), monday - timedelta(days=1)
    course_start, networking_start = monday - timedelta(days=48), monday - timedelta(days=133)
    d = first
    while d <= last:
        wd = d.weekday()  # 0 = Monday
        vacation = (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day == 1) or (d.month == 7 and d.day <= 10)
        school = d.month not in (7, 8)
        if wd < 5 and not vacation:
            yield d, "09:00", "17:30", "Work", "work", "Office" if wd in (0, 2, 4) else "Home office"
        if wd in (0, 3) and rng.random() < 0.7:
            yield d, "06:30", "07:30", "Gym", "health", "Fitness center"
        if wd == 0 and school and not vacation:
            yield d, "17:45", "18:30", "Pick up kids from soccer practice", "family", "Riverside Park fields"
        if wd in (1, 3) and d >= course_start:
            yield d, "19:30", "21:00", "AI course: live session", "course", "Zoom"
        if wd < 5 and d >= networking_start and rng.random() < 0.08:
            yield d, "20:00", "20:45", "Networking chat", "networking", "Zoom"
        if wd == 5 and school and rng.random() < 0.8:
            yield d, "09:00", "11:00", "Kids' soccer game", "family", "Riverside Park fields"
        if wd == 6 and rng.random() < 0.9:
            yield d, "17:00", "17:30", "Call with parents", "family", "Phone"
        d += timedelta(days=1)


def create_db(path: Path = DB_PATH, *, history: bool = True, seed: int = 7) -> Path:
    """(Re)build data/ and the database for the current week. Safe to call before every experiment."""
    week = build_week(DATA_DIR)
    path = Path(path)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    with open(DATA_DIR / "calendar.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO events VALUES (:id, :date, :start, :end, :title, :category, :location)",
                         csv.DictReader(f))
    with open(DATA_DIR / "tasks.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO tasks VALUES (:id, :title, :course, :due, :est_hours, :priority, :status)",
                         csv.DictReader(f))
    if history:
        rows = _history(random.Random(seed), week.monday)
        conn.executemany("INSERT INTO events (date, start, end, title, category, location) VALUES (?, ?, ?, ?, ?, ?)",
                         ((d.isoformat(), *rest) for d, *rest in rows))
    conn.commit()
    conn.close()
    return path


def connect(path: Path = DB_PATH, *, readonly: bool = False) -> sqlite3.Connection:
    """Read-only connections can't change anything, whatever SQL the model sends."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        # isolation_level=None: autocommit, unless WE open a transaction with BEGIN (dry-runs).
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def snapshot(conn: sqlite3.Connection) -> dict[str, set[tuple]]:
    return {t: {tuple(r) for r in conn.execute(f"SELECT * FROM {t}")} for t in ("events", "tasks")}


def diff(before: dict[str, set[tuple]], after: dict[str, set[tuple]]) -> str:
    """Human-readable change list: '- old row' / '+ new row'."""
    lines = []
    for table in before:
        for row in sorted(before[table] - after[table]):
            lines.append(f"  - {table}: {row}")
        for row in sorted(after[table] - before[table]):
            lines.append(f"  + {table}: {row}")
    return "\n".join(lines) or "  (no changes)"


def week() -> Week:
    """The simulated week: week.today, week.day(0..6) as ISO dates, week.label(n) for humans."""
    return Week(sim_monday())
