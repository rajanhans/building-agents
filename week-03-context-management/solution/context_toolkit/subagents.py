"""Isolate: send interns with their own desks; each returns one small page."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .budget import est_tokens


class ContractBroken(ValueError):
    """An intern returned more than one page."""


def run_subagents(intern: Callable[[Any], Any], jobs: list, max_tokens: int = 300, workers: int = 4) -> list:
    def run(job):
        page = intern(job)
        if est_tokens(page) > max_tokens:
            raise ContractBroken(f"intern returned ~{est_tokens(page)} tokens for {job!r}; the contract is {max_tokens}")
        return page
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, jobs))
