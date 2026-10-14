"""Read run folders: incremental event-log decoding with NumPy, or compacted Parquet.

Requires NumPy (installed with the ``viewer`` extra). Parquet support needs PyArrow.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import _format as fmt
from . import _fs

_LOG_RE = re.compile(r"^events\.r(\d+)\.s(\d+)\.log$")
Series = tuple[np.ndarray, np.ndarray, np.ndarray]  # steps (i8), times (f8), values (f8)
_PQ_COLUMNS = ("rank", "step", "time", "value", "vmin", "vmax")
_EMPTY: Series = (np.empty(0, "i8"), np.empty(0, "f8"), np.empty(0, "f8"))


@dataclass(frozen=True)
class TextEntry:
    key: str
    step: int
    time: float
    text: str


@dataclass(frozen=True)
class MediaEntry:
    key: str
    step: int
    time: float
    offset: int
    length: int
    meta: dict[str, Any]
    rank: int


class LogFile:
    """Incremental decoder for one ``events.r<rank>.s<session>.log`` file.

    :meth:`update` reads only bytes appended since the previous call and stops
    at a torn final frame, which is retried once the writer completes it.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        m = _LOG_RE.match(path.name)
        self.rank = int(m.group(1)) if m else 0
        self.session = int(m.group(2)) if m else 0
        self.offset = 0
        self.names: dict[int, str] = {}
        self._chunks: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
        self.texts: list[TextEntry] = []
        self.media: list[MediaEntry] = []
        self.heartbeat: float | None = None
        self.end: tuple[float, str] | None = None
        self._series: dict[str, Series] | None = None

    @property
    def size(self) -> int:
        return self.offset

    def update(self) -> bool:
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return False
        if size <= self.offset:
            return False
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read(size - self.offset)
        pos = 0
        if self.offset == 0:
            if len(data) < len(fmt.MAGIC):
                return False
            if data[: len(fmt.MAGIC) - 2] != fmt.MAGIC[:-2]:
                raise ValueError(f"{self.path} is not an event log")
            pos = len(fmt.MAGIC)
        changed = False
        for kind, payload, end in fmt.iter_frames(data, pos):
            pos = end
            changed = True
            if kind == fmt.SCALARS:
                n = int.from_bytes(payload[:4], "little")
                self._chunks.append(
                    (
                        np.frombuffer(payload, "<u4", n, 4),
                        np.frombuffer(payload, "<i8", n, 4 + 4 * n),
                        np.frombuffer(payload, "<f8", n, 4 + 12 * n),
                        np.frombuffer(payload, "<f8", n, 4 + 20 * n),
                    )
                )
            elif kind == fmt.NAME:
                mid, name = fmt.decode_name(payload)
                self.names[mid] = name
            elif kind == fmt.HEARTBEAT:
                self.heartbeat = fmt.decode_f64(payload)
            elif kind == fmt.TEXT:
                key, step, t, text = fmt.decode_text(payload)
                self.texts.append(TextEntry(self.names.get(key, str(key)), step, t, text))
            elif kind == fmt.MEDIA:
                key, step, t, off, length, meta = fmt.decode_media(payload)
                self.media.append(
                    MediaEntry(
                        self.names.get(key, str(key)),
                        step,
                        t,
                        off,
                        length,
                        json.loads(meta),
                        self.rank,
                    )
                )
            elif kind == fmt.END:
                t = fmt.decode_f64(payload)
                self.end = (t, bytes(payload[8:]).decode("utf-8"))
            # unknown frame kinds are skipped: newer writers stay readable
        self.offset += pos
        if changed:
            self._series = None
        return changed

    def series(self) -> dict[str, Series]:
        """All scalars in this file, split per metric (cached until new data)."""
        if self._series is None:
            out: dict[str, Series] = {}
            if self._chunks:
                if len(self._chunks) > 1:  # consolidate so later calls stay cheap
                    self._chunks = [tuple(np.concatenate(c) for c in zip(*self._chunks))]  # type: ignore[misc]
                ids, steps, times, values = self._chunks[0]
                top = int(ids.max()) if len(ids) else 0
                small = ids.astype("u1" if top < 256 else "u2") if top < 65536 else ids
                order = np.argsort(small, kind="stable")  # radix sort for small dtypes
                ids_sorted = ids[order]
                bounds = np.flatnonzero(np.diff(ids_sorted)) + 1
                starts = np.concatenate(([0], bounds))
                ends = np.concatenate((bounds, [len(ids_sorted)]))
                for a, b in zip(starts, ends):
                    idx = order[a:b]
                    name = self.names.get(int(ids_sorted[a]), str(int(ids_sorted[a])))
                    out[name] = (steps[idx], times[idx], values[idx])
            self._series = out
        return self._series


def merge_sessions(parts: list[Series]) -> Series:
    """Combine one metric's sessions in order; a later session wins from its first step."""
    parts = [p for p in parts if len(p[0])]
    if not parts:
        return _EMPTY
    s, t, v = parts[0]
    for s2, t2, v2 in parts[1:]:
        keep = s < s2.min()
        s, t, v = (
            np.concatenate((s[keep], s2)),
            np.concatenate((t[keep], t2)),
            np.concatenate((v[keep], v2)),
        )
    if len(s) > 1 and np.any(s[1:] < s[:-1]):
        order = np.argsort(s, kind="stable")
        s, t, v = s[order], t[order], v[order]
    return s, t, v


class ParquetData:
    """Reads ``data.parquet`` written by :func:`NAME.compact.compact_run`."""

    def __init__(self, path: Path) -> None:
        import pyarrow.parquet as pq

        self.file = pq.ParquetFile(path)
        self._lock = threading.Lock()  # a ParquetFile is not safe for concurrent reads
        meta = self.file.schema_arrow.metadata or {}
        # {metric: [[row_group, rows], ...] indexed by zoom level}
        self.row_groups: dict[str, list[list[int]]] = json.loads(meta[b"row_groups"])

    def metric_names(self) -> list[str]:
        return sorted(self.row_groups)

    def levels(self, metric: str) -> list[int]:
        return [n for _, n in self.row_groups.get(metric, [])]

    def read(self, metric: str, level: int = 0, rank: int = 0) -> tuple[np.ndarray, ...]:
        groups = self.row_groups.get(metric)
        if not groups:
            return (*_EMPTY, np.empty(0, "f8"), np.empty(0, "f8"))
        level = min(level, len(groups) - 1)
        with self._lock:
            table = self.file.read_row_group(groups[level][0], columns=list(_PQ_COLUMNS))
        ranks = table.column("rank").to_numpy()
        mask = ranks == rank
        cols = [
            table.column(c).to_numpy(zero_copy_only=False)
            for c in ("step", "time", "value", "vmin", "vmax")
        ]
        if not mask.all():
            cols = [c[mask] for c in cols]
        return tuple(cols)

    def ranks(self) -> list[int]:
        with self._lock:
            return sorted(set(self.file.read(columns=["rank"]).column("rank").to_pylist()))


class RunReader:
    """Everything stored in one run folder, read lazily and refreshed incrementally."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.logs: dict[str, LogFile] = {}
        self._parquet: ParquetData | None = None
        self._parquet_checked = False
        self.lock = threading.RLock()

    # -- metadata -----------------------------------------------------------
    def meta(self) -> dict[str, Any]:
        return _fs.read_json(self.path / "run.json", {})

    def _log_paths(self) -> list[Path]:
        try:
            names = os.listdir(self.path)
        except FileNotFoundError:
            return []
        return sorted(self.path / n for n in names if _LOG_RE.match(n))

    def log_sizes(self) -> dict[str, int]:
        return {p.name: p.stat().st_size for p in self._log_paths()}

    @property
    def parquet(self) -> ParquetData | None:
        """Compacted data, used only if it covers every byte of every log."""
        if not self._parquet_checked:
            self._parquet_checked = True
            pq_path = self.path / "data.parquet"
            if pq_path.exists():
                done = (self.meta().get("compacted") or {}).get("bytes")
                if done is not None and done == self.log_sizes():
                    try:
                        self._parquet = ParquetData(pq_path)
                    except Exception:
                        self._parquet = None
        return self._parquet

    def refresh(self) -> bool:
        """Read newly appended bytes. Returns True if anything changed."""
        with self.lock:
            if self._parquet_checked and self._parquet is None:
                self._parquet_checked = False  # a compaction may have finished since
            changed = False
            for p in self._log_paths():
                log = self.logs.get(p.name)
                if log is None:
                    log = self.logs[p.name] = LogFile(p)
                changed |= log.update()
            return changed

    def _logs_for(self, rank: int) -> list[LogFile]:
        if not self.logs:
            self.refresh()
        return sorted(
            (lf for lf in self.logs.values() if lf.rank == rank), key=lambda lf: lf.session
        )

    def ranks(self) -> list[int]:
        if not self.logs:
            self.refresh()
        return sorted({lf.rank for lf in self.logs.values()})

    # -- scalars -------------------------------------------------------------
    def metric_names(self, rank: int = 0) -> list[str]:
        if self.parquet is not None:
            return self.parquet.metric_names()
        names: set[str] = set()
        for lf in self._logs_for(rank):
            names.update(lf.series())
        return sorted(names)

    def scalars(self, metric: str, rank: int = 0) -> Series:
        """Full-resolution ``(steps, times, values)`` for one metric."""
        if self.parquet is not None:
            s, t, v, _, _ = self.parquet.read(metric, 0, rank)
            return s, t, v
        with self.lock:
            return merge_sessions([lf.series().get(metric, _EMPTY) for lf in self._logs_for(rank)])

    def all_scalars(self, rank: int = 0) -> dict[str, Series]:
        return {m: self.scalars(m, rank) for m in self.metric_names(rank)}

    # -- text and media ---------------------------------------------------------
    def texts(self, key: str | None = None, rank: int = 0) -> list[TextEntry]:
        out = [e for lf in self._logs_for(rank) for e in lf.texts if key is None or e.key == key]
        return sorted(out, key=lambda e: e.step)

    def media(self, key: str | None = None, rank: int = 0) -> list[MediaEntry]:
        out = [e for lf in self._logs_for(rank) for e in lf.media if key is None or e.key == key]
        return sorted(out, key=lambda e: e.step)

    def read_media(self, entry: MediaEntry) -> bytes:
        with open(self.path / f"media.r{entry.rank}.pack", "rb") as f:
            f.seek(entry.offset)
            return f.read(entry.length)

    def heartbeat(self) -> float | None:
        beats = [lf.heartbeat for lf in self.logs.values() if lf.heartbeat]
        return max(beats) if beats else None

    def iter_logs(self) -> Iterator[LogFile]:
        yield from self.logs.values()
