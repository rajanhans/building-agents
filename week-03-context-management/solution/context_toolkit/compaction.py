"""Compaction: the one-page summary. Recent turns stay verbatim; the summary is incremental."""

from typing import Callable

from ._items import field
from .budget import est_tokens

SUMMARY_PROMPT = """Summarise this conversation so the assistant can continue WITHOUT the original messages.
Keep: 1) goals and constraints 2) decisions and why 3) exact facts: numbers, dates, names, deadlines
4) what is done and what is still open. Drop chit-chat. At most 150 words."""
SUMMARY_TAG = "[Summary of the conversation so far]"


class Compactor:
    def __init__(self, summarize: Callable[[str], str], threshold: int, keep_last: int = 4,
                 prompt: str = SUMMARY_PROMPT):
        self.summarize, self.threshold, self.keep_last, self.prompt = summarize, threshold, keep_last, prompt
        self.summary = ""

    def __call__(self, messages: list) -> list:
        if sum(est_tokens(m) for m in messages) < self.threshold or len(messages) <= self.keep_last:
            return messages
        head, tail = messages[:-self.keep_last], messages[-self.keep_last:]
        head = [m for m in head if not str(field(m, "content", "")).startswith(SUMMARY_TAG)]
        transcript = "\n".join(f"{str(field(m, 'role', 'item')).upper()}: {field(m, 'content', '')}" for m in head)
        self.summary = self.summarize(
            f"{self.prompt}\n<previous>{self.summary}</previous>\n<transcript>\n{transcript}\n</transcript>").strip()
        return [{"role": "user", "content": f"{SUMMARY_TAG}\n{self.summary}"}] + tail
