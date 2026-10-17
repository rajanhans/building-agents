"""Alex's simulated week, dated to follow the real calendar.

The template in this folder (calendar.csv, tasks.csv, notes/) is written for the week of
Monday 2026-10-12. `build_week()` shifts every date by whole weeks so that the simulated
Monday is the Monday of the *current* week (or the coming Monday on Saturdays and Sundays),
and writes the dated copy into a week's `data/` folder.

Shifting by whole weeks keeps every weekday, so the exercises and their answers never change.
Set LIFE_TODAY=YYYY-MM-DD (e.g. in .env) to pin the simulated week to a fixed date.

Each week's folder has a copy of this file; edit the one in `life/` and copy it over.
"""

import csv
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent
TEMPLATE_MONDAY = date(2026, 10, 12)
_PLACEHOLDER = re.compile(r"\{\{([+-]\d+)(?::(short))?\}\}")


def find_template_dir(start: Path) -> Path:
    """The course's `life/` folder, searched upward from `start`."""
    for folder in [start, *start.parents]:
        if (folder / "life" / "calendar.csv").exists():
            return folder / "life"
    raise FileNotFoundError("Can't find the course's life/ folder (calendar.csv, tasks.csv, notes/).")


def sim_monday(today: date | None = None) -> date:
    """Monday of the current week; on Saturday and Sunday, the coming Monday."""
    if today is None:
        pinned = os.environ.get("LIFE_TODAY")
        today = date.fromisoformat(pinned) if pinned else date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(days=7) if today.weekday() >= 5 else monday


@dataclass(frozen=True)
class Week:
    monday: date

    def day(self, offset: int) -> str:
        """ISO date of Monday + offset days, e.g. week.day(4) -> Friday."""
        return (self.monday + timedelta(days=offset)).isoformat()

    def label(self, offset: int, short: bool = False) -> str:
        d = self.monday + timedelta(days=offset)
        return f"{d:%a %b} {d.day}" if short else f"{d:%A, %B} {d.day}"

    @property
    def today(self) -> str:
        """How the assistant is told what day it is, e.g. 'Monday 2026-10-12'."""
        return f"Monday {self.monday.isoformat()}"

    def shift(self, iso: str) -> str:
        """Move a template date into this week."""
        return (date.fromisoformat(iso) + (self.monday - TEMPLATE_MONDAY)).isoformat()


def build_week(out_dir: Path, *, template_dir: Path | None = None, today: date | None = None) -> Week:
    """Write the dated copy of the template into out_dir (calendar.csv, tasks.csv, notes/)."""
    template_dir = Path(template_dir or find_template_dir(Path(out_dir).resolve()))
    week = Week(sim_monday(today))
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "notes").mkdir(parents=True)

    for name, column in (("calendar.csv", "date"), ("tasks.csv", "due")):
        with open(template_dir / name, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row[column] = week.shift(row[column])
        with open(out_dir / name, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    for note in sorted((template_dir / "notes").glob("*.txt")):
        text = note.read_text(encoding="utf-8")
        text = _PLACEHOLDER.sub(lambda m: week.label(int(m.group(1)), short=bool(m.group(2))), text)
        (out_dir / "notes" / note.name).write_text(text, encoding="utf-8")
    return week
