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

from ..alerts import check_run
from ..catalog import Catalog
from ..query import resolve
from ..reader import RunReader
from ..series import aggregate, bucket_envelope, x_values

MAX_READERS = 256


class Store:
    """Owns the catalog and an LRU of :class:`RunReader` objects."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._readers: collections.OrderedDict[str, RunReader] = collections.OrderedDict()
        self._lock = threading.Lock()
        self._log_bytes: dict[str, int] = {}
        self._alerts: dict[str, tuple[Any, list[dict[str, Any]]]] = {}

    def reader(self, key: str) -> RunReader | None:
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
        """A reader with every byte written so far decoded (no-op for compacted runs)."""
        reader = self.reader(key)
        if reader is not None and reader.parquet is None:
            reader.refresh()
        return reader

    def grown_logs(self) -> set[str]:
        """Keys of live runs whose event logs grew since the last call."""
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
        """Health alerts: stored at compaction, else computed and cached per log size."""
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
    ) -> tuple[np.ndarray, ...] | None:
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
        else:
            s, t, v = reader.scalars(metric, rank)
            lo = hi = v
        if len(s) == 0:
            return None
        x = x_values(x_kind, s, t, start)
        if xmin is not None or xmax is not None:
            i0 = int(np.searchsorted(x, xmin, "left")) - 1 if xmin is not None else 0
            i1 = int(np.searchsorted(x, xmax, "right")) + 1 if xmax is not None else len(x)
            sl = slice(max(i0, 0), min(i1, len(x)))
            x, v, lo, hi = x[sl], v[sl], lo[sl], hi[sl]
        return x, v, lo, hi

    def _series_against(
        self,
        key: str,
        metric: str,
        x_metric: str,
        rank: int,
        points: int,
        xmin: float | None,
        xmax: float | None,
    ) -> tuple[np.ndarray, ...] | None:
        """``metric`` with another metric (e.g. tokens seen) as x, matched by step.

        The x metric is interpolated at each step of ``metric``. When it only
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
        steps, v, lo, hi = data
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
        return x, v, lo, hi

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
        """Arrow IPC stream: one row per point with columns series, x, y, lo, hi.

        Series metadata (label, runs, group value) is JSON in the schema metadata.
        """
        series_meta: list[dict[str, Any]] = []
        cols: dict[str, list[np.ndarray]] = {c: [] for c in ("series", "x", "y", "lo", "hi")}

        def add(
            meta: dict[str, Any], x: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray
        ) -> None:
            idx = len(series_meta)
            finite = y[np.isfinite(y)]
            meta["last"] = float(finite[-1]) if len(finite) else None
            meta["nonfinite"] = bool(len(finite) < len(y))
            series_meta.append(meta)
            cols["series"].append(np.full(len(x), idx, "i4"))
            for name, arr in (("x", x), ("y", y), ("lo", lo), ("hi", hi)):
                cols[name].append(np.asarray(arr, "f8"))

        loaded: dict[str, tuple[np.ndarray, ...]] = {}
        for key in keys:
            data = self.raw_series(key, metric, x_kind, rank, points, xmin, xmax)
            if data is not None:
                loaded[key] = data

        if not group_by:
            for key, (x, v, lo, hi) in loaded.items():
                xb, yb, lob, hib = bucket_envelope(x, v, lo, hi, points)
                record = self.catalog.get(key) or {}
                add(
                    {"label": record.get("name", key), "runs": [key], "group": None},
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


def _label(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-2 or abs(value) >= 1e5):
            mant, _, exp = f"{value:.2e}".partition("e")
            return f"{mant.rstrip('0').rstrip('.')}e{int(exp)}"
        return f"{value:g}"
    return str(value)


def _sort_value(value: Any) -> tuple[int, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value)
    return (1, str(value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def path_inside(base: Path, rel: str) -> Path | None:
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target
