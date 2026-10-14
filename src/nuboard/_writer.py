"""Background writer: the training thread only appends to a deque."""

from __future__ import annotations

import collections
import json
import math
import os
import threading
import time
import warnings
from array import array
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from . import _format as fmt
from ._meta import NAME

_SCALARS, _TEXT, _MEDIA = 0, 1, 2


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            yield from _flatten(value, name + "/")
        else:
            yield name, value


def _to_float(value: Any) -> float:
    if type(value) is float:
        return value
    try:
        return float(value)
    except TypeError:
        if hasattr(value, "item"):
            return float(value.item())
        raise


def json_float(x: float) -> float | str | None:
    if math.isfinite(x):
        return x
    if math.isnan(x):
        return "nan"
    return "inf" if x > 0 else "-inf"


class Writer:
    """Owns one ``events.r<rank>.s<session>.log`` file and its media pack."""

    def __init__(
        self,
        run_dir: Path,
        rank: int,
        session: int,
        flush_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
        on_heartbeat: Callable[[], None] | None = None,
    ) -> None:
        self.log_path = run_dir / f"events.r{rank}.s{session}.log"
        self.pack_path = run_dir / f"media.r{rank}.pack"
        self.queue: collections.deque[tuple[Any, ...]] = collections.deque()
        self.flush_interval = flush_interval
        self.heartbeat_interval = heartbeat_interval
        self._on_heartbeat = on_heartbeat
        self._ids: dict[str, int] = {}
        self._pack = None
        self._f = open(self.log_path, "ab")
        if self._f.tell() == 0:
            self._f.write(fmt.MAGIC)
            self._f.flush()
        # name -> [last, last_step, min, max, count, nonfinite]
        self._summary: dict[str, list[float]] = {}
        self.summary_lock = threading.Lock()
        self._warned: set[str] = set()
        self._wake = threading.Event()
        self._stopping = False
        self._closed = False
        self._thread = threading.Thread(target=self._loop, name=f"{NAME}-writer", daemon=True)
        self._thread.start()

    # -- called from the training thread ------------------------------------
    def put_scalars(self, step: int, t: float, data: Mapping[str, Any]) -> None:
        self.queue.append((_SCALARS, step, t, data))

    def put_text(self, key: str, step: int, t: float, text: str) -> None:
        self.queue.append((_TEXT, key, step, t, text))

    def put_media(
        self,
        key: str,
        step: int,
        t: float,
        producer: Callable[[], tuple[Any, ...]],
        meta: dict[str, Any],
    ) -> None:
        self.queue.append((_MEDIA, key, step, t, producer, meta))

    def flush(self, timeout: float = 10.0) -> None:
        """Block until everything queued so far is on disk."""
        deadline = time.monotonic() + timeout
        self._wake.set()
        while self.queue and time.monotonic() < deadline and self._thread.is_alive():
            time.sleep(0.005)
            self._wake.set()
        time.sleep(0)  # let the writer finish the batch it popped

    def summary(self) -> dict[str, dict[str, Any]]:
        with self.summary_lock:
            items = list(self._summary.items())
        out = {}
        for name, (last, step, lo, hi, count, bad) in items:
            out[name] = {
                "last": json_float(last),
                "step": int(step),
                "min": lo if lo != math.inf else None,
                "max": hi if hi != -math.inf else None,
                "count": int(count),
                "nonfinite": int(bad),
            }
        return out

    def write_points(self, points: Iterable[tuple[str, int, float, float]]) -> None:
        """Synchronously write already-decoded points (used for forks)."""
        ids, steps, times, values = array("I"), array("q"), array("d"), array("d")
        out: list[bytes] = []
        with self.summary_lock:
            for name, step, t, v in points:
                ids.append(self._id(name, out))
                steps.append(step)
                times.append(t)
                values.append(v)
                self._update_summary(name, step, v)
        if ids:
            out.append(fmt.scalars_frame(ids, steps, times, values))
        self._f.write(b"".join(out))
        self._f.flush()

    def close(self, status: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._stopping = True
        self._wake.set()
        self._thread.join(timeout=60)
        if self._thread.is_alive() or self.queue:  # pragma: no cover - shutdown edge
            self._drain()
        self._f.write(fmt.end_frame(time.time(), status))
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except OSError:  # pragma: no cover
            pass
        self._f.close()
        if self._pack is not None:
            self._pack.close()

    # -- writer thread --------------------------------------------------------
    def _loop(self) -> None:
        last_hb = time.monotonic()
        while True:
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            self._drain()
            if self._stopping:
                return
            now = time.monotonic()
            if now - last_hb >= self.heartbeat_interval:
                last_hb = now
                self._heartbeat()

    def _heartbeat(self) -> None:
        try:
            self._f.write(fmt.heartbeat_frame(time.time()))
            self._f.flush()
            if self._on_heartbeat is not None:
                self._on_heartbeat()
        except Exception as exc:  # pragma: no cover - never break training
            self._warn_once("heartbeat", f"{NAME}: heartbeat failed: {exc!r}")

    def _id(self, name: str, out: list[bytes]) -> int:
        mid = self._ids.get(name)
        if mid is None:
            mid = self._ids[name] = len(self._ids)
            out.append(fmt.name_frame(mid, name))
        return mid

    def _update_summary(self, name: str, step: int, v: float) -> None:
        s = self._summary.get(name)
        if s is None:
            s = self._summary[name] = [v, step, math.inf, -math.inf, 0, 0]
        s[0] = v
        s[1] = step
        s[4] += 1
        if v - v == 0:  # finite
            if v < s[2]:
                s[2] = v
            if v > s[3]:
                s[3] = v
        else:
            s[5] += 1

    def _drain(self) -> None:
        q = self.queue
        if not q:
            return
        ids, steps, times, values = array("I"), array("q"), array("d"), array("d")
        out: list[bytes] = []
        try:
            with self.summary_lock:
                while q:
                    item = q.popleft()
                    kind = item[0]
                    if kind == _SCALARS:
                        _, step, t, data = item
                        for name, raw in _flatten(data):
                            try:
                                v = _to_float(raw)
                            except (TypeError, ValueError):
                                self._warn_once(
                                    name,
                                    f"{NAME}: skipping {name!r}: cannot convert "
                                    f"{type(raw).__name__} to float (use log_text for strings)",
                                )
                                continue
                            ids.append(self._id(name, out))
                            steps.append(step)
                            times.append(t)
                            values.append(v)
                            self._update_summary(name, step, v)
                    elif kind == _TEXT:
                        _, key, step, t, text = item
                        out.append(fmt.text_frame(self._id(key, out), step, t, text))
                    else:
                        _, key, step, t, producer, meta = item
                        try:
                            produced = producer()
                        except Exception as exc:
                            self._warn_once(key, f"{NAME}: could not encode {key!r}: {exc!r}")
                            continue
                        # Producers return (bytes, mime) or (bytes, mime, extra meta)
                        data_bytes, mime = produced[0], produced[1]
                        extra = produced[2] if len(produced) > 2 else {}
                        offset = self._append_pack(data_bytes)
                        meta = {"mime": mime, **meta, **extra}
                        out.append(
                            fmt.media_frame(
                                self._id(key, out),
                                step,
                                t,
                                offset,
                                len(data_bytes),
                                json.dumps(meta, default=str),
                            )
                        )
            if ids:
                out.append(fmt.scalars_frame(ids, steps, times, values))
            if out:
                self._f.write(b"".join(out))
                self._f.flush()
        except Exception as exc:  # pragma: no cover - never break training
            self._warn_once("drain", f"{NAME}: failed to write a batch: {exc!r}")

    def _append_pack(self, data: bytes) -> int:
        if self._pack is None:
            self._pack = open(self.pack_path, "ab")
        offset = self._pack.seek(0, os.SEEK_END)
        self._pack.write(data)
        self._pack.flush()  # pack bytes land before the index frame that points at them
        return offset

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            warnings.warn(message, RuntimeWarning, stacklevel=2)
