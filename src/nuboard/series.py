"""NumPy helpers for zoom levels, downsampling, x-axis choice and group bands."""

from __future__ import annotations

import warnings

import numpy as np

LEVEL_FACTOR = 8  # each zoom level holds 1/8 of the points of the one below
MIN_LEVEL_POINTS = 512  # stop building levels below this many points
ACTIVE_GAP_S = 300.0  # gaps longer than this do not count as active time


def bucket(x: np.ndarray, y: np.ndarray, n_buckets: int) -> tuple[np.ndarray, ...]:
    """Split a series into `n_buckets` buckets holding equal numbers of points.

    Non-finite values are ignored by mean/min/max; a bucket with only NaN/Inf
    yields NaN, so divergence stays visible as a gap plus an alert.

    Args:
        x: X values, sorted.
        y: Y values, same length as `x`.
        n_buckets: Number of buckets wanted. If the series has no more points
            than this, it is returned unbucketed (as floats).

    Returns:
        `(x_first, y_mean, y_min, y_max)`: the first x of each bucket and the
        mean, minimum and maximum of the finite y values in it.
    """
    n = len(x)

    if n == 0:
        e = np.empty(0, "f8")
        return x[:0], e, e, e

    if n <= n_buckets:
        return x, y.astype("f8"), y.astype("f8"), y.astype("f8")

    starts = np.unique(np.linspace(0, n, n_buckets, endpoint=False).astype(np.int64))
    finite = np.isfinite(y)
    yz = np.where(finite, y, 0.0)
    counts = np.add.reduceat(finite.astype(np.int64), starts)

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.add.reduceat(yz, starts) / counts

    lo = np.fmin.reduceat(np.where(finite, y, np.nan), starts)
    hi = np.fmax.reduceat(np.where(finite, y, np.nan), starts)
    return x[starts], mean, lo, hi


def zoom_levels(
    steps: np.ndarray, times: np.ndarray, values: np.ndarray
) -> list[tuple[np.ndarray, ...]]:
    """Build the zoom levels of one series.

    Level 0 is the raw data; level k buckets `LEVEL_FACTOR**k` points. Levels
    are added while they would still hold at least `MIN_LEVEL_POINTS` points.

    Args:
        steps: Steps of the series.
        times: Unix timestamps, same length as `steps`.
        values: Values, same length as `steps`.

    Returns:
        One `(steps, times, mean, min, max)` tuple per level, starting at
        level 0 (where mean, min and max are all the raw values).
    """
    levels = [(steps, times, values, values, values)]
    k = 1

    while len(steps) // LEVEL_FACTOR**k >= MIN_LEVEL_POINTS:
        nb = max(1, len(steps) // LEVEL_FACTOR**k)
        idx = np.unique(np.linspace(0, len(steps), nb, endpoint=False).astype(np.int64))
        s = steps[idx]
        t = times[idx]
        _, mean, lo, hi = bucket(steps, values, nb)
        levels.append((s, t, mean, lo, hi))
        k += 1

    return levels


def x_values(
    kind: str, steps: np.ndarray, times: np.ndarray, start: float | None = None
) -> np.ndarray:
    """Compute the x coordinates of a series for the chosen x axis.

    Args:
        kind: `step`, `time` (unix seconds), `relative` (seconds since
            `start`) or `active` (seconds of activity, where gaps longer than
            `ACTIVE_GAP_S` or going backwards in time count as zero).
        steps: Steps of the series.
        times: Unix timestamps, same length as `steps`.
        start: Origin for `relative`; defaults to the first timestamp.

    Returns:
        The x coordinates as floats. An empty series always yields its steps.

    Raises:
        ValueError: If `kind` is not one of the axes above.
    """

    if kind == "step" or len(steps) == 0:
        return steps.astype("f8")

    if kind == "time":
        return times

    if kind == "relative":
        return times - (start if start is not None else times[0])

    if kind == "active":
        dt = np.diff(times, prepend=times[0])
        dt[(dt > ACTIVE_GAP_S) | (dt < 0)] = 0.0
        return np.cumsum(dt)

    raise ValueError(f"unknown x axis {kind!r}")


def aggregate(
    xs: list[np.ndarray],
    ys: list[np.ndarray],
    points: int,
    xmin: float | None = None,
    xmax: float | None = None,
) -> dict[str, np.ndarray]:
    """Interpolate runs onto a shared grid, then compute per-group statistics.

    A run contributes only inside its own x range; no extrapolation.
    Non-finite y values are left out of the interpolation.

    Args:
        xs: X values of each run, each sorted.
        ys: Y values of each run, matching `xs`.
        points: Number of grid points (at least 2 are used).
        xmin: Left end of the grid; defaults to the smallest first x.
        xmax: Right end of the grid; defaults to the largest last x.

    Returns:
        Arrays keyed `x`, `mean`, `std`, `min`, `max`, `median` and `n` (how
        many runs cover each grid point). All are empty if every run is empty.
    """
    xs_nonempty = [x for x in xs if len(x)]

    if not xs_nonempty:
        e = np.empty(0, "f8")
        return {"x": e, "mean": e, "std": e, "min": e, "max": e, "median": e, "n": e}

    lo = min(float(x[0]) for x in xs_nonempty) if xmin is None else xmin
    hi = max(float(x[-1]) for x in xs_nonempty) if xmax is None else xmax
    grid = np.linspace(lo, hi, max(2, points))
    stack = np.full((len(xs), len(grid)), np.nan)

    for i, (x, y) in enumerate(zip(xs, ys)):
        if len(x) == 0:
            continue

        finite = np.isfinite(y)

        if not finite.any():
            continue

        row = np.interp(grid, x[finite], y[finite], left=np.nan, right=np.nan)
        stack[i] = row

    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns are expected
        return {
            "x": grid,
            "mean": np.nanmean(stack, axis=0),
            "std": np.nanstd(stack, axis=0),
            "min": np.nanmin(stack, axis=0),
            "max": np.nanmax(stack, axis=0),
            "median": np.nanmedian(stack, axis=0),
            "n": np.sum(np.isfinite(stack), axis=0).astype("f8"),
        }


def bucket_envelope(
    x: np.ndarray,
    y: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    n_buckets: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bucket a series like `bucket`, but keep an existing min/max envelope.

    Used on zoom levels, whose min and max already summarize the raw data.

    Args:
        x: X values, sorted.
        y: Y values (bucket means), same length as `x`.
        lo: Existing per-point minimum.
        hi: Existing per-point maximum.
        n_buckets: Number of buckets wanted.

    Returns:
        `(x_first, y_mean, y_min, y_max)` per bucket, where `y_min` and
        `y_max` are taken from `lo` and `hi`.
    """
    xb, mean, _, _ = bucket(x, y, n_buckets)

    if len(x) <= n_buckets:
        return xb, mean, lo.astype("f8"), hi.astype("f8")

    starts = np.unique(np.linspace(0, len(x), n_buckets, endpoint=False).astype(np.int64))

    with np.errstate(invalid="ignore"):
        return xb, mean, np.fmin.reduceat(lo, starts), np.fmax.reduceat(hi, starts)
