"""Timers: how long parts of the training code take, logged as `timing/` scalars.

`Run.timer(name)` returns a `Timer` that works as a context manager or as a
start/stop handle. The name is the handle: the same name returns the same
timer, so a timer can start in one method and stop in another.

Each stop is logged as one scalar under the run's timing prefix (`timing/` by
default): its `time` is the wall-clock start of the span and its value the
duration in seconds, so the viewer can rebuild when each span ran. A timer made
with `accumulate=True` sums its spans instead and logs the total (and, under the
hidden key `<name>` + `COUNT`, how many spans it summed) on `flush`.
"""

from __future__ import annotations

import sys
import time
import warnings
from typing import TYPE_CHECKING

from ._meta import NAME

if TYPE_CHECKING:
    from .run import Run

COUNT = "\x1fcount"  # suffix of the hidden key holding an accumulated timer's span count

# A timer that logs every stop more often than this (points per second, over at
# least `_FAST_MIN` points) gets a one-time warning suggesting `accumulate=True`.
_FAST_RATE = 5.0
_FAST_MIN = 50


def cuda_sync() -> None:
    """Wait for queued CUDA work, if PyTorch is already imported and using CUDA.

    PyTorch is never imported here, so the logging side keeps no dependency on it.
    """
    torch = sys.modules.get("torch")

    if torch is None:
        return

    try:
        if torch.cuda.is_available() and torch.cuda.is_initialized():
            torch.cuda.synchronize()
    except Exception:  # pragma: no cover - a broken CUDA setup must not stop training
        pass


class Timer:
    """Measures how long a part of the training code takes and logs it to the run.

    Get one with `Run.timer`; `Timer.disabled` makes one that logs nothing.

    Use it as a context manager (`with run.timer("train/epoch"): ...`), or call
    `start` and `stop`, which may be in different methods: `run.timer(name)`
    returns the same timer for the same name.

    Starting a running timer restarts it and stopping a stopped one returns 0.0,
    each with a one-time warning; neither raises, so a callback called in an
    unexpected order never stops training.

    Attributes:
        name: The timer's name, such as `"train/epoch"` (without the prefix).
        key: The scalar it logs, such as `"timing/train/epoch"`.
        accumulate: Whether spans are summed until `flush`.
        all_ranks: Whether every rank logs it, not only rank 0.
        sync: Whether CUDA is synchronized at start and stop.
    """

    __slots__ = (
        "_count",
        "_first",
        "_logged",
        "_logged_since",
        "_run",
        "_step",
        "_t0",
        "_total",
        "_wall",
        "_warned",
        "accumulate",
        "all_ranks",
        "key",
        "name",
        "sync",
    )

    def __init__(
        self,
        run: Run | None,
        name: str,
        key: str,
        *,
        accumulate: bool = False,
        all_ranks: bool = False,
        sync: bool = False,
    ) -> None:
        self._run = run
        self.name = name
        self.key = key
        self.accumulate = accumulate
        self.all_ranks = all_ranks
        self.sync = sync
        self._t0: float | None = None  # perf_counter at start, None when stopped
        self._wall = 0.0  # wall-clock time at start
        self._step: int | None = None  # step for the next log, from `Run.timer(name, step)`
        self._total = 0.0  # accumulate mode: summed seconds since the last flush
        self._count = 0
        self._first = 0.0  # accumulate mode: wall-clock start of the first summed span
        self._logged = 0  # points logged, for the high-frequency warning
        self._logged_since = 0.0
        self._warned: set[str] = set()

    @classmethod
    def disabled(cls, name: str = "timer") -> Timer:
        """Return a timer that measures but logs nothing.

        Handy in wrappers that hand out timers before a run exists, or on a
        rank that does not log, so callers need no `if run is not None` checks.

        Args:
            name: A name, only used in warnings.

        Returns:
            A timer with the same interface whose `stop` and `flush` return
            seconds but write nothing.
        """
        return cls(None, name, name)

    # -- measuring --------------------------------------------------------------
    @property
    def running(self) -> bool:
        """Whether the timer has been started and not stopped."""
        return self._t0 is not None

    @property
    def elapsed(self) -> float:
        """Seconds since `start` while running, else 0.0. Logs nothing."""
        return 0.0 if self._t0 is None else time.perf_counter() - self._t0

    def start(self) -> Timer:
        """Start the timer.

        Returns:
            The timer itself, so `t = run.timer("x").start()` works.
        """

        if self._t0 is not None:
            self._warn("start", f"{NAME}: timer {self.name!r} was already running; restarted it")

        if self.sync:
            cuda_sync()

        self._wall = time.time()
        self._t0 = time.perf_counter()
        return self

    def stop(self, step: int | None = None) -> float:
        """Stop the timer and log the span (or add it to the total with `accumulate`).

        Args:
            step: Step to log at. Defaults to the one given to `Run.timer`, then
                to the run's latest step.

        Returns:
            The span's duration in seconds, or 0.0 if the timer was not running.
        """

        if self._t0 is None:
            self._warn("stop", f"{NAME}: timer {self.name!r} was stopped without being started")
            return 0.0

        if self.sync:
            cuda_sync()

        seconds = time.perf_counter() - self._t0
        self._t0 = None

        if self.accumulate:
            if not self._count:
                self._first = self._wall

            self._total += seconds
            self._count += 1

            if step is not None:
                self._step = step
        else:
            self._log(step, self._wall, seconds, None)

        return seconds

    def flush(self, step: int | None = None) -> float:
        """Log the spans summed since the last flush as one point, and reset.

        For a timer made with `accumulate=True`, such as one around each batch,
        call it once per epoch. Does nothing when no span was summed.

        Args:
            step: Step to log at. Defaults as for `stop`.

        Returns:
            The summed seconds (0.0 if there were none).
        """
        total, count = self._total, self._count

        if count:
            self._log(step, self._first, total, count)

        self._total, self._count = 0.0, 0
        return total

    def __enter__(self) -> Timer:
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if self._t0 is not None:  # stops even when the block raised
            self.stop()

    def __repr__(self) -> str:
        state = "running" if self._t0 is not None else "stopped"
        return f"Timer({self.key!r}, {state})"

    # -- internals --------------------------------------------------------------
    def _log(self, step: int | None, started: float, seconds: float, count: int | None) -> None:
        """Hand one point to the run, which writes it (or not, on a rank that does not log)."""

        if step is None:
            step = self._step

        self._step = None

        if self._run is None:
            return

        self._run._log_timer(self, step, started, seconds, count)

        if count is None:
            self._check_rate()

    def _check_rate(self) -> None:
        """Warn once when a non-accumulating timer logs many points per second."""
        self._logged += 1

        if self._logged == 1:
            self._logged_since = time.monotonic()
        elif self._logged % _FAST_MIN == 0 and "fast" not in self._warned:
            rate = self._logged / max(time.monotonic() - self._logged_since, 1e-9)

            if rate > _FAST_RATE:
                self._warn(
                    "fast",
                    f"{NAME}: timer {self.name!r} logs about {rate:.0f} points per second; "
                    f"for a timer around every batch use run.timer({self.name!r}, "
                    "accumulate=True) and call flush() once per epoch",
                )

    def _warn(self, kind: str, message: str) -> None:

        if kind not in self._warned:
            self._warned.add(kind)
            warnings.warn(message, RuntimeWarning, stacklevel=4)
