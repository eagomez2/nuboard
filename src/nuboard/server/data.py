"""Data access for the viewer: cached run readers and chart series as Arrow."""

from __future__ import annotations

import collections
import json
import math
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from .. import _format as fmt
from ..alerts import check_run
from ..catalog import Catalog
from ..query import resolve
from ..reader import RunReader, align
from ..series import aggregate, bucket_envelope, x_values

MAX_READERS = 256


class Store:
    """Owns the catalog and an LRU of `RunReader` objects.

    At most `MAX_READERS` readers are kept; the least recently used one is
    dropped first. Reader lookups are thread-safe.

    Args:
        catalog: The catalog of runs to serve.
    """

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._readers: collections.OrderedDict[str, RunReader] = collections.OrderedDict()
        self._lock = threading.Lock()
        self._log_bytes: dict[str, int] = {}
        self._alerts: dict[str, tuple[Any, list[dict[str, Any]]]] = {}

    def reader(self, key: str) -> RunReader | None:
        """Return the cached reader for a run, creating it if needed.

        Args:
            key: Catalog key of the run.

        Returns:
            The run's reader, or None if the catalog does not know the run.
        """

        with self._lock:
            reader = self._readers.get(key)

            if reader is not None:
                self._readers.move_to_end(key)
                return reader

            path = self.catalog.path_of(key)

            if path is None:
                return None

            reader = self._readers[key] = RunReader(path)

            while len(self._readers) > MAX_READERS:
                self._readers.popitem(last=False)

            return reader

    def fresh_reader(self, key: str) -> RunReader | None:
        """Return a reader with every byte written so far decoded.

        Refreshing is skipped for compacted runs, whose data is in Parquet.

        Args:
            key: Catalog key of the run.

        Returns:
            The run's reader, or None if the catalog does not know the run.
        """
        reader = self.reader(key)

        if reader is not None and reader.parquet is None:
            reader.refresh()

        return reader

    def grown_logs(self) -> set[str]:
        """Return the keys of live runs whose event logs grew since the last call.

        Returns:
            Keys of running runs whose total `events.*` file size changed. On the
            first call every running run counts as grown.
        """
        grown = set()

        for row in self.catalog.runs():
            if row["status"] != "running":
                continue

            path = self.catalog.path_of(row["key"])

            if path is None:
                continue

            total = 0

            try:
                for p in path.iterdir():
                    if p.name.startswith("events."):
                        total += p.stat().st_size
            except FileNotFoundError:
                continue

            if self._log_bytes.get(row["key"]) != total:
                self._log_bytes[row["key"]] = total
                grown.add(row["key"])

        return grown

    def alerts(self, key: str) -> list[dict[str, Any]]:
        """Return the health alerts of a run.

        Finished compacted runs use the alerts stored at compaction. Otherwise
        the alerts are computed with `check_run` and cached until the run's log
        sizes or compaction state change.

        Args:
            key: Catalog key of the run.

        Returns:
            The alerts as dicts; empty if the run is unknown.
        """
        record = self.catalog.get(key)

        if record is None:
            return []

        if record["status"] != "running" and record.get("compacted"):
            return record.get("alerts") or []

        reader = self.fresh_reader(key)

        if reader is None:
            return []

        state = (tuple(sorted(reader.log_sizes().items())), reader.parquet is not None)
        cached = self._alerts.get(key)

        if cached is None or cached[0] != state:
            with reader.lock:
                cached = self._alerts[key] = (state, check_run(reader))

        return cached[1]

    # -- series ----------------------------------------------------------------
    def raw_series(
        self,
        key: str,
        metric: str,
        x_kind: str,
        rank: int,
        points: int,
        xmin: float | None,
        xmax: float | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool] | None:
        """Load one run's series of `metric` at a resolution that suits the chart.

        For compacted runs, the coarsest Parquet level that still has at least
        `2 * points` points in the visible range is read (the visible share is
        estimated from the coarsest level). Otherwise the raw scalars are used.
        With a zoom range, the series is cut to it plus one point on each side.

        Args:
            key: Catalog key of the run.
            metric: Metric name.
            x_kind: The x axis: `step`, `time`, `relative`, `active` or
                `metric:<name>` to plot against another metric.
            rank: Process rank whose values to read.
            points: Approximate number of points the chart will draw.
            xmin: Lower end of the zoom range in x units, or None.
            xmax: Upper end of the zoom range in x units, or None.

        Returns:
            A tuple `(x, y, lo, hi, band)`, or None if the run is unknown or has
            no data for `metric`. When `band` is True the metric was logged with
            `low` and `high`, and `lo` and `hi` are those bounds (NaN where a
            point has none). Otherwise they bound the values each point
            summarizes (equal to `y` for raw data).
        """

        if x_kind.startswith("metric:"):
            return self._series_against(key, metric, x_kind[7:], rank, points, xmin, xmax)

        reader = self.fresh_reader(key)
        record = self.catalog.get(key)

        if reader is None or record is None:
            return None

        start = record.get("started")
        pq = reader.parquet

        if pq is not None:
            counts = pq.levels(metric)

            if not counts:
                return None

            frac = 1.0

            if xmin is not None or xmax is not None:  # estimate visible share from coarsest level
                s, t, *_ = pq.read(metric, len(counts) - 1, rank)
                xc = x_values(x_kind, s, t, start)

                if len(xc):
                    inside = np.count_nonzero(
                        (xc >= (xmin if xmin is not None else -np.inf))
                        & (xc <= (xmax if xmax is not None else np.inf))
                    )
                    frac = max(inside, 1) / len(xc)

            level = 0

            for i, n in enumerate(counts):
                if n * frac >= points * 2:
                    level = i

            s, t, v, lo, hi = pq.read(metric, level, rank)
            lo = np.where(np.isnan(lo), v, lo)
            hi = np.where(np.isnan(hi), v, hi)
            band = bool(pq.levels(metric + fmt.BAND_LOW) or pq.levels(metric + fmt.BAND_HIGH))

            if band:  # the outer edges of the bounds each point summarizes
                lo = _level_bound(pq.read(metric + fmt.BAND_LOW, level, rank), s, 3)
                hi = _level_bound(pq.read(metric + fmt.BAND_HIGH, level, rank), s, 4)
        else:
            s, t, v = reader.scalars(metric, rank)
            lo = hi = v
            bounds = reader.bounds(metric, rank)
            band = bounds is not None

            if bounds is not None:
                lo, hi = bounds

        if len(s) == 0:
            return None

        x = x_values(x_kind, s, t, start)

        if xmin is not None or xmax is not None:
            i0 = int(np.searchsorted(x, xmin, "left")) - 1 if xmin is not None else 0
            i1 = int(np.searchsorted(x, xmax, "right")) + 1 if xmax is not None else len(x)
            sl = slice(max(i0, 0), min(i1, len(x)))
            x, v, lo, hi = x[sl], v[sl], lo[sl], hi[sl]

        return x, v, lo, hi, band

    def _series_against(
        self,
        key: str,
        metric: str,
        x_metric: str,
        rank: int,
        points: int,
        xmin: float | None,
        xmax: float | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool] | None:
        """`metric` with another metric (e.g. tokens seen) as x, matched by step.

        The x metric is interpolated at each step of `metric`. When it only
        grows (tokens, epochs, samples), a zoom range in its units is turned into
        a step range, so zooming still loads finer data.
        """
        reader = self.fresh_reader(key)

        if reader is None:
            return None

        xs, _, xv = reader.scalars(x_metric, rank)
        ok = np.isfinite(xv)
        xs, xv = xs[ok], xv[ok]

        if len(xs) == 0:
            return None

        if np.any(np.diff(xs) < 0):
            order = np.argsort(xs, kind="stable")
            xs, xv = xs[order], xv[order]

        xs_f = xs.astype("f8")
        increasing = bool(np.all(np.diff(xv) >= 0))
        smin = smax = None

        if increasing:
            if xmin is not None:
                smin = float(np.interp(xmin, xv, xs_f))

            if xmax is not None:
                smax = float(np.interp(xmax, xv, xs_f))

        data = self.raw_series(key, metric, "step", rank, points, smin, smax)

        if data is None:
            return None

        steps, v, lo, hi, band = data
        x = np.interp(steps, xs_f, xv, left=np.nan, right=np.nan)
        keep = np.isfinite(x)

        if not increasing:  # e.g. a learning rate: plot as a curve ordered by x
            if xmin is not None:
                keep &= x >= xmin

            if xmax is not None:
                keep &= x <= xmax

        x, v, lo, hi = x[keep], v[keep], lo[keep], hi[keep]

        if not increasing:
            order = np.argsort(x, kind="stable")
            x, v, lo, hi = x[order], v[order], lo[order], hi[order]

        return x, v, lo, hi, band

    def chart(
        self,
        keys: list[str],
        metric: str,
        *,
        x_kind: str = "step",
        group_by: str | None = None,
        agg: str = "std",
        points: int = 1000,
        rank: int = 0,
        xmin: float | None = None,
        xmax: float | None = None,
    ) -> bytes:
        """Build the data of one chart as an Arrow IPC stream.

        Without `group_by`, each run with data becomes one series, bucketed to
        about `points` points. With `group_by`, runs are grouped by that field's
        value (see `resolve`) and each group becomes one aggregated series,
        sorted by group value.

        Args:
            keys: Catalog keys of the runs to plot.
            metric: Metric name.
            x_kind: The x axis, as for `raw_series`.
            group_by: Field to group runs by, or None for one series per run.
            agg: Band of grouped series: `std` (mean ± std), `sem` (mean ± standard
                error), `minmax` (mean with min/max), `median` (median with
                min/max) or anything else for the mean with no band.
            points: Approximate number of points per series.
            rank: Process rank whose values to read.
            xmin: Lower end of the zoom range in x units, or None.
            xmax: Upper end of the zoom range in x units, or None.

        Returns:
            An Arrow IPC stream with one row per point and the columns `series`
            (index into the series metadata), `x`, `y`, `lo` and `hi`. The schema
            metadata holds `metric`, `x` and `series`, a JSON list with each
            series' label, runs, group value, group size (`n`, grouped only),
            whether `lo` and `hi` are logged bounds to draw as a band (`band`,
            ungrouped only), last finite value and whether it has non-finite
            values.
        """
        series_meta: list[dict[str, Any]] = []
        cols: dict[str, list[np.ndarray]] = {c: [] for c in ("series", "x", "y", "lo", "hi")}

        def add(
            meta: dict[str, Any], x: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray
        ) -> None:
            """Append one series and its metadata to the output columns."""
            idx = len(series_meta)
            finite = y[np.isfinite(y)]
            meta["last"] = float(finite[-1]) if len(finite) else None
            meta["nonfinite"] = bool(len(finite) < len(y))
            series_meta.append(meta)
            cols["series"].append(np.full(len(x), idx, "i4"))

            for name, arr in (("x", x), ("y", y), ("lo", lo), ("hi", hi)):
                cols[name].append(np.asarray(arr, "f8"))

        loaded: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool]] = {}

        for key in keys:
            data = self.raw_series(key, metric, x_kind, rank, points, xmin, xmax)

            if data is not None:
                loaded[key] = data

        if not group_by:
            names = {key: (self.catalog.get(key) or {}).get("name", key) for key in loaded}
            counts = collections.Counter(names.values())

            for key, (x, v, lo, hi, band) in loaded.items():
                xb, yb, lob, hib = bucket_envelope(x, v, lo, hi, points)
                label = names[key]

                if counts[label] > 1:  # series are told apart by label in the viewer
                    label = f"{label} ({key.rsplit('_', 1)[-1]})"

                add(
                    {"label": label, "runs": [key], "group": None, "band": band},
                    xb,
                    yb,
                    lob,
                    hib,
                )
        else:
            groups: dict[str, list[str]] = {}
            values: dict[str, Any] = {}

            for key in loaded:
                value = resolve(self.catalog.get(key) or {}, group_by)
                label = _label(value)
                groups.setdefault(label, []).append(key)
                values[label] = value

            for label in sorted(groups, key=lambda lb: _sort_value(values[lb])):
                members = groups[label]
                stats = aggregate(
                    [loaded[k][0] for k in members],
                    [loaded[k][1] for k in members],
                    points,
                    xmin,
                    xmax,
                )
                center = stats["median"] if agg == "median" else stats["mean"]

                if agg == "std":
                    lo, hi = center - stats["std"], center + stats["std"]
                elif agg == "sem":
                    err = stats["std"] / np.sqrt(np.maximum(stats["n"], 1))
                    lo, hi = center - err, center + err
                elif agg in ("minmax", "median"):
                    lo, hi = stats["min"], stats["max"]
                else:
                    lo = hi = np.full(len(center), np.nan)

                keep = stats["n"] > 0
                add(
                    {
                        "label": label,
                        "runs": members,
                        "group": _jsonable(values[label]),
                        "n": len(members),
                    },
                    stats["x"][keep],
                    center[keep],
                    lo[keep],
                    hi[keep],
                )

        arrays = {
            name: np.concatenate(parts) if parts else np.empty(0, "f8")
            for name, parts in cols.items()
        }

        if not cols["series"]:
            arrays["series"] = np.empty(0, "i4")

        table = pa.table(arrays)
        table = table.replace_schema_metadata(
            {
                "series": json.dumps(series_meta, allow_nan=False, default=str),
                "metric": metric,
                "x": x_kind,
            }
        )
        sink = pa.BufferOutputStream()

        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)

        return sink.getvalue().to_pybytes()


def _level_bound(data: tuple[np.ndarray, ...], steps: np.ndarray, col: int) -> np.ndarray:
    """Align one band bound read from a Parquet zoom level with the metric's steps.

    Args:
        data: `(steps, times, values, vmin, vmax)` of the bound's companion scalar.
        steps: Steps of the metric at the same level.
        col: Column to use: 3 (`vmin`) for the low bound, 4 (`vmax`) for the high one.

    Returns:
        One bound per step; NaN where the bound has none.
    """
    at, values = data[0], np.where(np.isnan(data[col]), data[2], data[col])

    if len(at) == len(steps) or len(at) < 2:
        return align(steps, at, values)

    # bounds were logged at fewer steps, so the levels are bucketed differently
    return np.interp(steps, at, values, left=np.nan, right=np.nan)


def _label(value: Any) -> str:
    """Format a group value as a short label (`(none)` for None, compact floats)."""

    if value is None:
        return "(none)"

    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-2 or abs(value) >= 1e5):
            mant, _, exp = f"{value:.2e}".partition("e")
            return f"{mant.rstrip('0').rstrip('.')}e{int(exp)}"

        return f"{value:g}"

    return str(value)


def _sort_value(value: Any) -> tuple[int, Any]:
    """Return a sort key that orders numbers before strings."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value)

    return (1, str(value))


def _jsonable(value: Any) -> Any:
    """Return `value` if it is a finite JSON scalar, else its string form."""

    if isinstance(value, float) and not math.isfinite(value):
        return str(value)

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def path_inside(base: Path, rel: str) -> Path | None:
    """Resolve a relative path and check that it stays inside `base`.

    Args:
        base: The folder the path must stay in.
        rel: Path relative to `base`, as received from a client.

    Returns:
        The resolved path, or None if it points outside `base` (for example
        through `..` or a symlink).
    """
    target = (base / rel).resolve()

    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None

    return target
