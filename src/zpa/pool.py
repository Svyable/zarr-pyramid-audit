"""
pool.py -- bounded parallel map with progress, for I/O-bound survey work.

Uses threads: the workloads this toolkit runs are network-bound (HTTP HEAD /
ranged GET), where threads beat processes because there is no pickling cost
and the GIL is released during socket waits. For CPU-bound work use
`parallel_map(..., mode="process")`.

Failures are captured per item, never raised out of the pool, so one bad
object cannot abort a survey of 100,000. Every result carries its input.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

__all__ = ["TaskResult", "parallel_map", "default_workers", "Progress"]


def default_workers(io_bound: bool = True) -> int:
    """RT_WORKERS if set by env.sh, else a sensible default for the host."""
    env = os.environ.get("RT_WORKERS")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    n = os.cpu_count() or 4
    # I/O-bound survey work benefits from oversubscription; CPU work does not.
    return min(64, n * 4) if io_bound else n


@dataclass
class TaskResult:
    item: Any
    ok: bool
    value: Any = None
    error: str | None = None
    traceback: str | None = None
    seconds: float = 0.0


class Progress:
    """Thread-safe stderr progress line. Silent when not a TTY unless forced."""

    def __init__(self, total: int | None, label: str = "", force: bool = False,
                 every: float = 0.5):
        self.total = total
        self.label = label
        self.n = 0
        self.fail = 0
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._last = 0.0
        self._every = every
        self._on = force or sys.stderr.isatty()

    def update(self, ok: bool = True, n: int = 1) -> None:
        with self._lock:
            self.n += n
            if not ok:
                self.fail += 1
            now = time.time()
            if self._on and (now - self._last >= self._every):
                self._last = now
                self._render(now)

    def _render(self, now: float) -> None:
        el = now - self._t0
        rate = self.n / el if el > 0 else 0.0
        if self.total:
            pct = 100.0 * self.n / self.total
            eta = (self.total - self.n) / rate if rate > 0 else 0.0
            msg = (f"\r{self.label} {self.n}/{self.total} ({pct:5.1f}%) "
                   f"{rate:7.1f}/s fail={self.fail} eta={eta/60:5.1f}m")
        else:
            msg = f"\r{self.label} {self.n} {rate:7.1f}/s fail={self.fail}"
        sys.stderr.write(msg.ljust(96))
        sys.stderr.flush()

    def close(self) -> None:
        if self._on:
            self._render(time.time())
            sys.stderr.write("\n")
            sys.stderr.flush()


def parallel_map(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int | None = None,
    mode: str = "thread",
    label: str = "",
    progress: bool = True,
    ordered: bool = False,
) -> Iterator[TaskResult]:
    """
    Apply *fn* to every item in parallel, yielding TaskResult as they finish
    (or in input order when ordered=True).

    Exceptions inside *fn* are captured into TaskResult.error/.traceback --
    the pool never propagates them, so a survey always runs to completion and
    the failures become data rather than a crash.
    """
    seq: Sequence[T] = list(items)
    if not seq:
        return
    io_bound = (mode == "thread")
    nw = workers or default_workers(io_bound=io_bound)
    nw = max(1, min(nw, len(seq)))
    Executor = ThreadPoolExecutor if io_bound else ProcessPoolExecutor
    prog = Progress(len(seq), label=label) if progress else None

    def _wrapped(it: T) -> TaskResult:
        t0 = time.time()
        try:
            v = fn(it)
            return TaskResult(item=it, ok=True, value=v, seconds=time.time() - t0)
        except Exception as e:
            return TaskResult(item=it, ok=False,
                              error=f"{type(e).__name__}: {e}",
                              traceback=traceback.format_exc(),
                              seconds=time.time() - t0)

    with Executor(max_workers=nw) as ex:
        if ordered:
            for res in ex.map(_wrapped, seq):
                if prog:
                    prog.update(res.ok)
                yield res
        else:
            futs = {ex.submit(_wrapped, it): it for it in seq}
            for fu in as_completed(futs):
                res = fu.result()
                if prog:
                    prog.update(res.ok)
                yield res
    if prog:
        prog.close()
