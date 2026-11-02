"""Timer summaries for the viewer's Timing tab (needs NumPy).

Timers are `S`-frame scalars under the run's timing prefix (see
`nuboard.timing`): each point's value is a span's duration and its time the
span's start. This module turns them into what the Timing tab shows: per timer
the calls, mean, p95, total and share of the run with a per-step series; the
time no timer covered; the time ranks waited for each other; a few findings;
and the spans of one step for the timeline.

Nesting is not stored: a timer is the child of another when its spans fall
inside the other's spans on the same rank.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import numpy as np

from .reader import RunReader
from .series import bucket_envelope
from .timing import COUNT

DEFAULT_PREFIX = "timing"
_INSIDE = 0.9  # share of a timer's spans that must fall inside another's to nest under it
_SPIKE = 3.0  # a step this many times its timer's median (and 0.5 s above it) is a finding
_SLOW_SHARE = 0.5  # a rank slowest in more than this share of steps is a finding


def timing_prefix(meta: Mapping[str, Any]) -> str:
    """Return the run's timing prefix, without the trailing `/`."""
    value = (meta.get("prefixes") or {}).get("timing")
    return value if isinstance(value, str) and value else DEFAULT_PREFIX


def timer_keys(reader: RunReader, prefix: str) -> list[str]:
    """Return the timer scalar keys of a run (any rank), sorted."""
    head = prefix + "/"
    keys: set[str] = set()

    for rank in reader.ranks() or [0]:
        keys.update(n for n in reader.scalar_names(rank) if n.startswith(head))

    return sorted(keys)


def wall_time(meta: Mapping[str, Any], now: float | None = None) -> float:
    """Return the run's wall time in seconds: the sum of its sessions' lengths."""
    now = time.time() if now is None else now
    total = 0.0

    for s in meta.get("sessions") or []:
        start = s.get("started")
        end = s.get("ended") or meta.get("heartbeat") or now

        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            total += end - start

    if not total:
        start, end = meta.get("started"), meta.get("ended") or meta.get("heartbeat") or now

        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            total = max(end - start, 0.0)

    return total


class _Timer:
    """One timer's points on every rank that logged it."""

    def __init__(self, reader: RunReader, key: str, name: str, ranks: list[int]) -> None:
        self.key = key
        self.name = name
        self.points: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self.counts: dict[int, np.ndarray] = {}

        for rank in ranks:
            s, t, v = reader.scalars(key, rank)

            if len(s):
                self.points[rank] = (s, t, v)
                _, _, c = reader.scalars(key + COUNT, rank)

                if len(c) == len(s):
                    self.counts[rank] = c

        self.accumulated = bool(self.counts)
        self.parent: str | None = None
        self.depth = 0

    def per_step(self, rank: int) -> tuple[np.ndarray, np.ndarray]:
        """Return the rank's distinct steps and the summed duration at each."""
        s, _, v = self.points[rank]
        steps, first = np.unique(s, return_index=True)
        return steps, np.add.reduceat(v, first) if len(v) else v

    def calls(self, rank: int) -> int:
        """Return how many spans the rank timed (summed spans count one each)."""
        c = self.counts.get(rank)
        return int(np.nansum(c)) if c is not None else len(self.points[rank][0])

    def intervals(self, rank: int) -> tuple[np.ndarray, np.ndarray]:
        """Return the rank's spans as sorted `(starts, ends)`; summed spans have no extent."""
        _, t, v = self.points[rank]
        ends = t if self.accumulated else t + v
        order = np.argsort(t, kind="stable")
        return t[order], ends[order]


def _matrix(timer: _Timer, ranks: list[int]) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Return the steps, a `(rank, step)` matrix of durations and the rank of each row.

    The steps are the union of every rank's; a rank without a step has NaN there.
    """
    per = {r: timer.per_step(r) for r in ranks if r in timer.points}

    if not per:
        return np.empty(0, "i8"), np.empty((0, 0)), []

    steps = np.unique(np.concatenate([s for s, _ in per.values()]))
    out = np.full((len(per), len(steps)), np.nan)

    for i, (s, v) in enumerate(per.values()):
        out[i, np.searchsorted(steps, s)] = v

    return steps, out, list(per)


def _inside_share(child: _Timer, parent: _Timer, rank: int) -> float:
    """Return the share of the child's spans that lie inside one of the parent's spans."""

    if rank not in child.points or rank not in parent.points or parent.accumulated:
        return 0.0

    ps, pe = parent.intervals(rank)
    cs, ce = child.intervals(rank)

    if not len(cs) or not len(ps):
        return 0.0

    idx = np.searchsorted(ps, cs, "right") - 1
    ok = idx >= 0
    j = np.where(ok, idx, 0)
    inside = ok & (cs >= ps[j]) & (ce <= pe[j] + 1e-6)
    return float(inside.mean())


def _nest(timers: list[_Timer], rank: int) -> list[_Timer]:
    """Set each timer's parent and depth, and return them parents first (tree order)."""
    by_key = {t.key: t for t in timers}
    mean_len = {
        t.key: float(np.mean(t.points[rank][2])) if rank in t.points else 0.0 for t in timers
    }

    for child in timers:
        best: tuple[float, float, str] | None = None

        for parent in timers:
            if parent is child or mean_len[parent.key] <= mean_len[child.key]:
                continue

            share = _inside_share(child, parent, rank)

            if share >= _INSIDE:
                cand = (-share, mean_len[parent.key], parent.key)  # most inside, then tightest

                if best is None or cand < best:
                    best = cand

        child.parent = best[2] if best else None

    # siblings in the order they run: by their usual start within a step
    first: dict[int, float] = {}

    for t in timers:
        if rank in t.points:
            for step, start in zip(*(a.tolist() for a in t.points[rank][:2]), strict=True):
                first[step] = min(first.get(step, start), start)

    def offset(t: _Timer) -> tuple[float, str]:
        if rank not in t.points:
            return (np.inf, t.key)

        s, st, _ = t.points[rank]
        return (float(np.median(st - np.array([first[x] for x in s.tolist()]))), t.key)

    order = sorted(timers, key=offset)
    ordered: list[_Timer] = []

    def visit(t: _Timer, depth: int) -> None:
        t.depth = depth
        ordered.append(t)

        for c in order:
            if c.parent == t.key:
                visit(c, depth + 1)

    for t in order:
        if t.parent is None or t.parent not in by_key:
            visit(t, 0)

    return ordered


def _union(starts: np.ndarray, ends: np.ndarray) -> float:
    """Return the total length covered by possibly overlapping intervals."""

    if not len(starts):
        return 0.0

    order = np.argsort(starts)
    s, e = starts[order], ends[order]
    reach = np.maximum.accumulate(e)
    prev = np.concatenate(([-np.inf], reach[:-1]))
    return float(np.sum(np.maximum(e, prev) - np.maximum(s, prev)).clip(min=0))


def _series(steps: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, points: int):
    """Downsample a per-step series to about `points` points, keeping its min/max envelope."""
    x, ym, lom, him = bucket_envelope(steps.astype("f8"), y, lo, hi, points)
    clean = lambda a: [None if not np.isfinite(v) else round(float(v), 6) for v in a]  # noqa: E731
    return {"x": [float(v) for v in x], "y": clean(ym), "lo": clean(lom), "hi": clean(him)}


def _stats(values: np.ndarray, calls: float, wall: float) -> dict[str, Any]:
    """Return mean, p95 and total of per-step durations, with the share of the wall time."""
    v = values[np.isfinite(values)]
    total = float(v.sum()) if len(v) else 0.0
    return {
        "calls": calls,
        "mean": float(v.mean()) if len(v) else 0.0,
        "p95": float(np.percentile(v, 95)) if len(v) else 0.0,
        "total": total,
        "share": total / wall if wall > 0 else None,
        "steps": len(v),
    }


def summarize(
    reader: RunReader,
    meta: Mapping[str, Any],
    rank: int | None = 0,
    points: int = 600,
) -> dict[str, Any]:
    """Summarize a run's timers for the Timing tab.

    Args:
        reader: The run's reader.
        meta: The run's `run.json`.
        rank: The rank to show, or None for every rank: per step the mean over
            ranks, with the min and max across ranks as `lo` and `hi`.
        points: About how many points each per-step series keeps.

    Returns:
        A JSON-ready dict with `prefix`, `ranks` (that logged timers), `wall`
        (seconds), `steps` (distinct steps timed), `sessions` (the step where
        each resumed session starts), `timers` (tree order: `name`, `key`,
        `parent`, `depth`, `accumulated`, the stats and `series`), `untimed`,
        `waiting` (None with fewer than two ranks) and `findings`.
    """
    prefix = timing_prefix(meta)
    all_ranks = reader.ranks() or [0]
    keys = timer_keys(reader, prefix)
    timers = [_Timer(reader, k, k[len(prefix) + 1 :], all_ranks) for k in keys]
    timers = [t for t in timers if t.points]
    ranks = sorted({r for t in timers for r in t.points})
    wall = wall_time(meta)
    out: dict[str, Any] = {
        "prefix": prefix,
        "ranks": ranks,
        "rank": rank,
        "wall": wall,
        "steps": 0,
        "sessions": [],
        "timers": [],
        "untimed": None,
        "waiting": None,
        "findings": [],
    }

    if not timers:
        return out

    ref = rank if rank is not None and rank in ranks else ranks[0]
    use = [ref] if rank is not None else ranks
    timers = _nest(timers, ref)
    all_steps: set[int] = set()
    medians: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for t in timers:
        steps, m, _ = _matrix(t, use)

        if not len(steps):
            continue

        with np.errstate(all="ignore"):
            y = np.nanmean(m, axis=0)
            lo, hi = np.nanmin(m, axis=0), np.nanmax(m, axis=0)

        calls = float(np.mean([t.calls(r) for r in use if r in t.points]))
        all_steps.update(steps.tolist())
        medians[t.key] = (steps, y)
        out["timers"].append(
            {
                "name": t.name,
                "key": t.key,
                "parent": t.parent[len(prefix) + 1 :] if t.parent else None,
                "depth": t.depth,
                "accumulated": t.accumulated,
                **_stats(y, calls, wall),
                "series": _series(steps, y, lo, hi, points),
            }
        )

    out["steps"] = len(all_steps)
    top = [t for t in timers if t.parent is None]
    covered = []

    for r in use:
        spans = [t.intervals(r) for t in top if r in t.points and not t.accumulated]
        summed = sum(float(np.sum(t.points[r][2])) for t in top if r in t.points and t.accumulated)
        starts = np.concatenate([s for s, _ in spans]) if spans else np.empty(0)
        ends = np.concatenate([e for _, e in spans]) if spans else np.empty(0)
        covered.append(_union(starts, ends) + summed)

    timed = float(np.mean(covered)) if covered else 0.0
    untimed = max(wall - timed, 0.0)
    out["untimed"] = {
        "total": untimed,
        "share": untimed / wall if wall > 0 else None,
        "mean": untimed / max(len(all_steps), 1),
    }

    if len(ranks) > 1:
        out["waiting"] = _waiting(top, ranks, use, wall, points)

    out["sessions"] = _session_steps(meta, timers, ref)
    out["findings"] = _findings(timers, medians, ranks, prefix)
    return out


def _waiting(
    top: list[_Timer], ranks: list[int], use: list[int], wall: float, points: int
) -> dict[str, Any] | None:
    """Per step, the time each rank had no top-level timer running while another rank had."""
    per_step: dict[int, dict[int, tuple[list[float], list[float]]]] = {}

    for t in top:
        if t.accumulated:
            continue

        for r, (s, st, v) in t.points.items():
            for step, a, d in zip(s.tolist(), st.tolist(), v.tolist(), strict=True):
                spans = per_step.setdefault(step, {}).setdefault(r, ([], []))
                spans[0].append(a)
                spans[1].append(a + d)

    if not per_step:
        return None

    steps = np.array(sorted(per_step))
    m = np.full((len(use), len(steps)), np.nan)

    for j, step in enumerate(steps.tolist()):
        by_rank = per_step[step]
        every = [x for r in ranks for x in zip(*by_rank.get(r, ([], [])), strict=True)]

        if not every:
            continue

        union = _union(np.array([a for a, _ in every]), np.array([b for _, b in every]))

        for i, r in enumerate(use):
            mine = by_rank.get(r, ([], []))
            m[i, j] = max(union - _union(np.array(mine[0]), np.array(mine[1])), 0.0)

    with np.errstate(all="ignore"):
        y = np.nanmean(m, axis=0)
        lo, hi = np.nanmin(m, axis=0), np.nanmax(m, axis=0)

    return {**_stats(y, 0, wall), "series": _series(steps, y, lo, hi, points)}


def _session_steps(meta: Mapping[str, Any], timers: list[_Timer], rank: int) -> list[dict]:
    """Return, for each resumed session, the first timed step at or after its start."""
    sessions = (meta.get("sessions") or [])[1:]

    if not sessions:
        return []

    pts = [t.points[rank] for t in timers if rank in t.points]

    if not pts:
        return []

    s = np.concatenate([p[0] for p in pts])
    t = np.concatenate([p[1] for p in pts])
    order = np.argsort(t)
    s, t = s[order], t[order]
    out = []

    for sess in sessions:
        start = sess.get("started")

        if not isinstance(start, (int, float)):
            continue

        i = int(np.searchsorted(t, start))

        if i < len(t):
            out.append(
                {"session": sess.get("session"), "step": int(s[i]), "host": sess.get("host")}
            )

    return out


def _findings(
    timers: list[_Timer],
    medians: dict[str, tuple[np.ndarray, np.ndarray]],
    ranks: list[int],
    prefix: str,
) -> list[dict[str, Any]]:
    """Return the notable things: a step far above its timer's median, a rank usually slowest."""
    out: list[dict[str, Any]] = []
    spikes = []

    for t in timers:
        steps, y = medians.get(t.key, (np.empty(0), np.empty(0)))
        ok = np.isfinite(y)

        if ok.sum() < 5:
            continue

        med = float(np.median(y[ok]))
        i = int(np.nanargmax(y))

        if med > 0 and y[i] > _SPIKE * med and y[i] - med > 0.5:
            spikes.append((y[i] / med, t.name, int(steps[i]), float(y[i])))

    for ratio, name, step, value in sorted(spikes, reverse=True)[:2]:
        out.append(
            {
                "kind": "spike",
                "timer": name,
                "step": step,
                "value": value,
                "message": f"{name} {ratio:.1f}× its median at step {step}",
            }
        )

    if len(ranks) > 1:
        best = None

        for t in timers:
            if t.parent is not None or len(t.points) < 2:
                continue

            _, m, rows = _matrix(t, ranks)
            full = m[:, np.all(np.isfinite(m), axis=0)]

            if full.shape[1] < 5:
                continue

            slowest = np.argmax(full, axis=0)
            counts = np.bincount(slowest, minlength=full.shape[0])
            i = int(np.argmax(counts))
            med = np.median(full, axis=0)

            with np.errstate(all="ignore"):
                excess = float(np.nanmean(full[i] / med) - 1)

            total = float(np.nansum(full))

            if counts[i] / full.shape[1] > _SLOW_SHARE and excess > 0.01:
                cand = (total, rows[i], int(counts[i]), full.shape[1], excess, t.name)

                if best is None or cand > best:
                    best = cand

        if best is not None:
            _, rank, n, of, excess, name = best
            out.append(
                {
                    "kind": "slow_rank",
                    "rank": rank,
                    "timer": name,
                    "message": f"rank {rank} slowest in {n:,} of {of:,} steps (+{excess:.1%})",
                }
            )

    return out


def spans(reader: RunReader, meta: Mapping[str, Any], step: int | None) -> dict[str, Any]:
    """Return the spans of one step on every rank, for the timeline.

    Args:
        reader: The run's reader.
        meta: The run's `run.json`.
        step: The step to show; None for the last timed step. A step without
            spans gives the nearest timed step before it.

    Returns:
        `{step, prev, next, start, ranks: [{rank, spans: [{name, start, end,
        depth, accumulated, count}]}]}`; times are seconds from `start`, the
        step's earliest span start. `prev` and `next` are the neighboring
        timed steps (or None).
    """
    prefix = timing_prefix(meta)
    all_ranks = reader.ranks() or [0]
    timers = [
        _Timer(reader, k, k[len(prefix) + 1 :], all_ranks) for k in timer_keys(reader, prefix)
    ]
    timers = [t for t in timers if t.points]
    out: dict[str, Any] = {"step": None, "prev": None, "next": None, "start": None, "ranks": []}

    if not timers:
        return out

    ranks = sorted({r for t in timers for r in t.points})
    timers = _nest(timers, ranks[0])
    steps = np.unique(np.concatenate([p[0] for t in timers for p in t.points.values()]))

    if step is None:
        i = len(steps) - 1
    else:
        i = max(int(np.searchsorted(steps, step, "right")) - 1, 0)

    at = int(steps[i])
    out["step"] = at
    out["prev"] = int(steps[i - 1]) if i > 0 else None
    out["next"] = int(steps[i + 1]) if i + 1 < len(steps) else None
    lanes: dict[int, list[dict[str, Any]]] = {r: [] for r in ranks}
    t0 = np.inf

    for t in timers:
        for r, (s, st, v) in t.points.items():
            mask = s == at

            if not mask.any():
                continue

            counts = t.counts.get(r)
            idx = np.flatnonzero(mask)
            t0 = min(t0, float(st[idx].min()))

            for k in idx.tolist():
                lanes[r].append(
                    {
                        "name": t.name,
                        "start": float(st[k]),
                        "end": float(st[k] + (0 if t.accumulated else v[k])),
                        "seconds": float(v[k]),
                        "depth": t.depth,
                        "accumulated": t.accumulated,
                        "count": int(counts[k]) if counts is not None else 1,
                    }
                )

    out["start"] = t0

    for r in ranks:
        for span in lanes[r]:
            span["start"] -= t0
            span["end"] -= t0

        out["ranks"].append({"rank": r, "spans": sorted(lanes[r], key=lambda x: x["start"])})

    return out
