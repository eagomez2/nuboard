"""Choose the best steps of a set of runs, and keep the picks in `<project>/picks.json`.

A candidate is one run at one step where every chosen scalar was logged. Each scalar has a
direction (`min`: lower is better, `max`: higher is better), and the shortlist is the Pareto
front: the steps that no other step beats on every scalar at once. A step that is missing one
of the scalars is never ranked; it is counted as incomplete instead, so a run is not favored for
being judged on fewer numbers.

A pick records the run, the step, why it was chosen and, optionally, the checkpoint that goes
with it. The file holds

    {"picks": [{"id": "3f2a9c1e", "run": "20261119-0840_base_ab12", "step": 15000,
                "note": "...", "metrics": {"val/acc": 0.839}, "directions": {"val/acc": "max"},
                "checkpoint": {"artifact": "model", "version": 5}, "created": 1795079576.8}]}

It sits next to `directions.json`, so it can be committed to git with the project's other
settings.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import _fs
from .directions import DIRECTIONS, _file_lock

PICKS_FILE = "picks.json"
MAX_PICKS = 1000
MAX_NOTE = 4000
_CHUNK = 512  # rows compared at once by `pareto_mask`


def complete_steps(
    series: Mapping[str, tuple[np.ndarray, np.ndarray]],
    metrics: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return the steps where every metric was logged, with the values there.

    Args:
        series: `{metric: (steps, values)}` of one run; a metric that is absent counts as never
            logged. Steps need not be sorted; a step logged twice keeps its last value.
        metrics: The metrics, in the order of the returned columns.

    Returns:
        `(steps, values, incomplete)`: the sorted steps where all metrics have a value,
        a `(len(steps), len(metrics))` float array, and how many other steps have at least
        one of the metrics. Steps whose values are not all finite are left out of both.
    """
    per: list[tuple[np.ndarray, np.ndarray]] = []

    for m in metrics:
        s, v = series.get(m, (np.empty(0, np.int64), np.empty(0)))
        s = np.asarray(s, dtype=np.int64)
        v = np.asarray(v, dtype=np.float64)
        # the last value of each step: unique on the reversed arrays keeps the first seen
        rs, idx = np.unique(s[::-1], return_index=True)
        per.append((rs, v[::-1][idx]))

    if not per:
        return np.empty(0, np.int64), np.empty((0, 0)), 0

    union = np.unique(np.concatenate([s for s, _ in per]))
    steps = per[0][0]

    for s, _ in per[1:]:
        steps = np.intersect1d(steps, s, assume_unique=True)

    values = np.empty((len(steps), len(per)))

    for k, (s, v) in enumerate(per):
        values[:, k] = v[np.searchsorted(s, steps)]

    finite = np.isfinite(values).all(axis=1)
    return steps[finite], values[finite], int(len(union) - finite.sum())


def pareto_mask(values: np.ndarray, directions: Sequence[str]) -> np.ndarray:
    """Return which rows no other row beats on every column (the Pareto front).

    Row `j` beats row `i` when it is at least as good on every column and better on one, by
    each column's direction. Equal rows do not beat each other, so both are kept.

    Args:
        values: A `(n, k)` array of finite values.
        directions: `min` or `max` for each column.

    Returns:
        A boolean array of length `n`, True for the rows on the front.
    """
    n = len(values)

    if n == 0:
        return np.zeros(0, dtype=bool)

    sign = np.array([1.0 if d == "min" else -1.0 for d in directions])
    x = np.asarray(values, dtype=np.float64) * sign  # lower is better in every column
    # A row can only be beaten by one before it in this order, so one pass suffices; rows beaten
    # by a row off the front are beaten by a front row too, so only the front is kept to compare.
    order = np.lexsort(x.T[::-1])
    xs = x[order]
    front = np.empty((0, x.shape[1]))
    keep = np.zeros(n, dtype=bool)

    for start in range(0, n, _CHUNK):
        c = xs[start : start + _CHUNK]
        rivals = np.concatenate([front, c])
        le = (rivals[None, :, :] <= c[:, None, :]).all(axis=2)
        lt = (rivals[None, :, :] < c[:, None, :]).any(axis=2)
        beaten = (le & lt).any(axis=1)
        keep[start : start + len(c)] = ~beaten
        front = np.concatenate([front, c[~beaten]])

    out = np.zeros(n, dtype=bool)
    out[order] = keep
    return out


def checkpoint_step(
    manifest: Mapping[str, Any], steps: np.ndarray, times: np.ndarray
) -> tuple[int | None, bool]:
    """Return the step an artifact version belongs to, and whether it was recorded or guessed.

    A version made with `add_artifact(..., step=...)` (or with a whole-number `step` in its
    metadata) says its step. Otherwise it is guessed from when it was made: the last step logged
    before then.

    Args:
        manifest: The version's `manifest.json`.
        steps: Steps the run logged, sorted by time.
        times: When each of `steps` was logged (Unix seconds).

    Returns:
        `(step, exact)`; `(None, False)` when there is no way to tell.
    """

    for value in (manifest.get("step"), (manifest.get("metadata") or {}).get("step")):
        if isinstance(value, int) and not isinstance(value, bool):
            return value, True

    created = manifest.get("created")

    if not isinstance(created, (int, float)) or not len(times):
        return None, False

    i = int(np.searchsorted(times, created, "right")) - 1
    return (int(steps[i]), False) if i >= 0 else (None, False)


class PickError(ValueError):
    """A pick that cannot be saved: a missing run or step, or a note that is too long."""


def read_picks(project_dir: Path) -> list[dict[str, Any]]:
    """Return the picks saved in a project, oldest first, skipping malformed entries."""
    data = _fs.read_json(project_dir / PICKS_FILE, {}) or {}
    items = data.get("picks") if isinstance(data, dict) else None
    out = []

    for p in items if isinstance(items, list) else []:
        if (
            isinstance(p, dict)
            and isinstance(p.get("id"), str)
            and isinstance(p.get("run"), str)
            and isinstance(p.get("step"), int)
        ):
            out.append(p)

    return out


def _clean(pick: Mapping[str, Any]) -> dict[str, Any]:
    """Check a pick sent by the viewer and keep only the fields a pick has."""
    run = pick.get("run")
    step = pick.get("step")

    if not isinstance(run, str) or not run.strip():
        raise PickError("a pick needs a run")

    if not isinstance(step, int) or isinstance(step, bool):
        raise PickError("a pick needs a whole-number step")

    note = str(pick.get("note") or "").strip()

    if len(note) > MAX_NOTE:
        raise PickError(f"a note has at most {MAX_NOTE} characters")

    metrics = {
        str(k): float(v)
        for k, v in (pick.get("metrics") or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    directions = {str(k): v for k, v in (pick.get("directions") or {}).items() if v in DIRECTIONS}
    ckpt = pick.get("checkpoint")
    checkpoint = None

    if isinstance(ckpt, dict) and isinstance(ckpt.get("artifact"), str):
        version = ckpt.get("version")
        checkpoint = {
            "artifact": ckpt["artifact"],
            "version": version if isinstance(version, int) else None,
        }

    return {
        "run": run.strip(),
        "run_name": str(pick.get("run_name") or ""),
        "step": step,
        "note": note,
        "metrics": metrics,
        "directions": directions,
        "checkpoint": checkpoint,
    }


def save_pick(project_dir: Path, pick: Mapping[str, Any]) -> dict[str, Any]:
    """Add a pick to the project, or replace the one with the same `id`, and return it.

    Raises:
        PickError: If the pick has no run or step, its note is too long, or the project has
            `MAX_PICKS` picks already.
        OSError: If `picks.json` cannot be written.
    """
    item = _clean(pick)

    with _file_lock(project_dir / ".picks.lock"):
        picks = read_picks(project_dir)
        pid = pick.get("id")
        old = next((p for p in picks if isinstance(pid, str) and p["id"] == pid), None)

        if old is not None:
            item = {**item, "id": old["id"], "created": old.get("created"), "edited": time.time()}
            picks = [item if p is old else p for p in picks]
        else:
            if len(picks) >= MAX_PICKS:
                raise PickError(f"a project has at most {MAX_PICKS} picks")

            item = {**item, "id": secrets.token_hex(4), "created": time.time()}
            picks.append(item)

        _fs.atomic_write_json(project_dir / PICKS_FILE, {"picks": picks})
        return item


def delete_pick(project_dir: Path, pick_id: str) -> bool:
    """Delete a pick; return whether it existed."""

    with _file_lock(project_dir / ".picks.lock"):
        picks = read_picks(project_dir)
        kept = [p for p in picks if p["id"] != pick_id]

        if len(kept) == len(picks):
            return False

        _fs.atomic_write_json(project_dir / PICKS_FILE, {"picks": kept})
        return True
