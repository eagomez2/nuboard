"""Health checks over a run's scalars: non-finite values, spikes and throughput drops.

Each check works on at most ``BUCKETS`` bucketed points per metric (mean, min
and max per bucket), so a run with millions of points is scanned in
milliseconds and a single spike still shows up through the bucket maximum.
Needs NumPy.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import numpy as np

from .reader import RunReader
from .series import bucket

BUCKETS = 2000
WINDOW = 25  # trailing buckets that form the baseline
SPIKE_MADS = 10.0  # a spike is this many robust deviations above the baseline...
SPIKE_REL = 0.15  # ...and at least this fraction of the baseline's magnitude
DROP_FRACTION = 0.7  # throughput below this fraction of the run's median is a drop
DROP_MIN_BUCKETS = 3  # ...for at least this many consecutive buckets
MAX_PER_METRIC = 5

SPIKE_RE = re.compile(r"(loss|grad)", re.IGNORECASE)
THROUGHPUT_RE = re.compile(
    r"(throughput|per_sec|per_s$|/s$|_ps$|fps|tokens_per|samples_per|it_s|steps_per)",
    re.IGNORECASE,
)


def _alert(kind: str, metric: str, rank: int, step: int, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "metric": metric, "rank": rank, "step": int(step), **extra}


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges ``[start, end)`` where ``mask`` is True."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def nonfinite(metric: str, rank: int, steps: np.ndarray, values: np.ndarray) -> list[dict]:
    bad = ~np.isfinite(values)
    if not bad.any():
        return []
    i = int(np.argmax(bad))
    v = float(values[i])
    label = "NaN" if np.isnan(v) else ("+Inf" if v > 0 else "-Inf")
    return [
        _alert(
            "nonfinite",
            metric,
            rank,
            steps[i],
            severity="error",
            count=int(bad.sum()),
            message=f"{metric} is {label} from step {int(steps[i]):,}",
        )
    ]


def spikes(metric: str, rank: int, steps: np.ndarray, values: np.ndarray) -> list[dict]:
    x, mean, _, hi = bucket(steps, values, BUCKETS)
    n = len(mean)
    if n <= WINDOW + 1:
        return []
    windows = np.lib.stride_tricks.sliding_window_view(mean[:-1], WINDOW)  # trailing windows
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows after a divergence
        base = np.nanmedian(windows, axis=1)
        mad = np.nanmedian(np.abs(windows - base[:, None]), axis=1) * 1.4826
    peak = hi[WINDOW:]
    limit = base + np.maximum(SPIKE_MADS * mad, SPIKE_REL * np.abs(base))
    with np.errstate(invalid="ignore"):
        flagged = np.isfinite(peak) & np.isfinite(limit) & (peak > limit)
    out = []
    for a, b in _runs(flagged)[:MAX_PER_METRIC]:
        j = a + int(np.nanargmax(peak[a:b]))
        out.append(
            _alert(
                "spike",
                metric,
                rank,
                x[WINDOW + a],
                end_step=int(x[min(WINDOW + b, n - 1)]),
                severity="warning",
                value=float(peak[j]),
                baseline=float(base[j]),
                message=(
                    f"{metric} spiked to {peak[j]:.4g} (baseline {base[j]:.4g})"
                    f" at step {int(x[WINDOW + j]):,}"
                ),
            )
        )
    return out


def drops(metric: str, rank: int, steps: np.ndarray, values: np.ndarray) -> list[dict]:
    x, mean, _, _ = bucket(steps, values, BUCKETS)
    finite = np.isfinite(mean)
    if finite.sum() < 4 * DROP_MIN_BUCKETS:
        return []
    median = float(np.median(mean[finite]))
    if median <= 0:
        return []
    with np.errstate(invalid="ignore"):
        low = finite & (mean < DROP_FRACTION * median)
    out = []
    for a, b in _runs(low):
        if b - a < DROP_MIN_BUCKETS or a == 0:  # ramp-up at the start is not a drop
            continue
        worst = float(np.min(mean[a:b]))
        out.append(
            _alert(
                "drop",
                metric,
                rank,
                x[a],
                end_step=int(x[b - 1]),
                severity="warning",
                value=worst,
                baseline=median,
                message=(
                    f"{metric} dropped {100 * (1 - worst / median):.0f}% below its median"
                    f" from step {int(x[a]):,} to {int(x[b - 1]):,}"
                ),
            )
        )
        if len(out) >= MAX_PER_METRIC:
            break
    return out


def check_series(metric: str, rank: int, steps: np.ndarray, values: np.ndarray) -> list[dict]:
    out = nonfinite(metric, rank, steps, values)
    if SPIKE_RE.search(metric):
        out += spikes(metric, rank, steps, values)
    if THROUGHPUT_RE.search(metric):
        out += drops(metric, rank, steps, values)
    return out


def check_run(reader: RunReader) -> list[dict[str, Any]]:
    """All alerts for every metric and rank of a run, ordered by step."""
    out: list[dict[str, Any]] = []
    for rank in reader.ranks() or [0]:
        for metric, (s, _, v) in reader.all_scalars(rank).items():
            if len(s):
                out += check_series(metric, rank, s, v)
    out.sort(key=lambda a: (a["step"], a["metric"], a["rank"]))
    return out
