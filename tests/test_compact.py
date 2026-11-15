"""Compaction to Parquet and the reader's choice between Parquet and logs."""

from __future__ import annotations

import json
import time

import numpy as np
import pyarrow.parquet as pq
import pytest

import nuboard as nb
from nuboard.compact import compact_run
from nuboard.reader import RunReader


def make_run(n=20_000, compact=True):
    run = nb.init("p", capture_env=False, compact=compact)

    for s in range(n):
        run.add_scalar({"loss": 1.0 / (s + 1), "lr": 0.1}, step=s)

    run.finish()
    return run


def test_parquet_matches_logs_and_has_row_group_map():
    run = make_run()
    path = run.path / "data.parquet"
    assert path.exists()
    pf = pq.ParquetFile(path)
    groups = json.loads(pf.schema_arrow.metadata[b"row_groups"])
    assert set(groups) == {"loss", "lr"}
    assert pf.num_row_groups == sum(len(v) for v in groups.values())
    assert groups["loss"][0][1] == 20_000 and len(groups["loss"]) >= 2  # zoom levels
    fresh = RunReader(run.path)
    assert fresh.parquet is not None
    from_pq = fresh.scalars("loss")
    logs = RunReader(run.path)
    logs._parquet_checked = True  # force the log path
    from_log = logs.scalars("loss")

    for a, b in zip(from_pq, from_log):
        np.testing.assert_array_equal(a, b)

    s, _, v, lo, hi = fresh.parquet.read("loss", level=1)
    assert len(s) == 20_000 // 8
    assert np.all(lo <= v) and np.all(v <= hi)


def test_one_metric_read_is_fast():
    run = make_run(200_000)
    reader = RunReader(run.path)
    assert reader.parquet is not None  # open once
    best = float("inf")

    for _ in range(5):  # best of five: shared CI machines are noisy
        t0 = time.perf_counter()
        reader.scalars("loss")
        best = min(best, time.perf_counter() - t0)

    assert best < 0.05, best  # target: under 10 ms


def test_stale_parquet_is_ignored_after_resume():
    run = make_run(100)
    again = nb.init("p", run_id=run.id, resume="must", capture_env=False, compact=False)
    again.add_scalar({"loss": -1.0}, step=100)
    again.finish()
    reader = RunReader(run.path)
    assert reader.parquet is None  # logs grew: compacted data no longer covers them
    assert reader.scalars("loss")[2][-1] == -1.0
    compact_run(run.path)
    assert RunReader(run.path).parquet is not None


def test_million_points_read_quickly():
    run = nb.init("p", capture_env=False, compact=False)

    for s in range(100_000):
        run.add_scalar({f"m{i}": float(s) for i in range(10)}, step=s)

    run.finish()
    t0 = time.perf_counter()
    reader = RunReader(run.path)
    reader.refresh()
    data = reader.all_scalars()
    elapsed = time.perf_counter() - t0
    assert sum(len(v[0]) for v in data.values()) == 1_000_000
    assert elapsed < 0.5, elapsed  # target is 0.1 s on a laptop; CI machines vary


def test_compaction_retries_while_the_old_file_is_in_use(monkeypatch):
    import os

    from nuboard import _fs
    from nuboard.compact import compact_run

    run = nb.init("busy", capture_env=False, system_metrics=False, capture_console=False)
    run.add_scalar("loss", 1.0, step=0)
    run.finish()
    real, calls = os.replace, {"n": 0}

    def busy(src, dest):  # Windows, while a viewer reads the old data.parquet
        if str(dest).endswith("data.parquet"):
            calls["n"] += 1

            if calls["n"] <= 2:
                raise PermissionError("in use")

        return real(src, dest)

    monkeypatch.setattr(_fs.os, "replace", busy)
    compact_run(run.path)
    assert calls["n"] == 3


def test_parquet_reads_leave_no_file_open():
    import sys

    from nuboard.reader import RunReader

    if not sys.platform.startswith("linux"):
        pytest.skip("counts open files with /proc")

    import os

    run = nb.init("open", capture_env=False, system_metrics=False, capture_console=False)
    run.add_scalar("loss", 1.0, step=0)
    run.finish()
    reader = RunReader(run.path)
    assert reader.parquet is not None and reader.scalars("loss")[2].tolist() == [1.0]
    target = str(run.path / "data.parquet")
    fds = []

    for fd in os.listdir("/proc/self/fd"):
        try:
            fds.append(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:  # the descriptor listdir itself used
            pass

    assert target not in fds


def test_zoom_levels_are_cached_until_the_file_changes():
    from nuboard.reader import _LEVELS

    run = nb.init("cache", capture_env=False, system_metrics=False, capture_console=False)

    for i in range(50):
        run.add_scalar("loss", float(i), step=i)

    run.finish()
    data = RunReader(run.path).parquet
    assert data is not None
    first = data.read("loss")
    assert data.read("loss") is first  # decoded once
    assert not first[2].flags.writeable

    resumed = nb.init("cache", run_id=run.id, resume="must", capture_env=False)
    resumed.add_scalar("loss", 99.0, step=50)
    resumed.finish()
    again = RunReader(run.path).parquet
    assert again is not None and len(again.read("loss")[0]) == 51
    assert _LEVELS.size <= _LEVELS.budget


def test_bytes_written_while_compacting_are_not_counted_as_covered(monkeypatch):
    from array import array

    from nuboard import _format as fmt

    run = nb.init("race", capture_env=False, system_metrics=False, capture_console=False)
    run.add_scalar("loss", 1.0, step=0)
    run.finish()
    log = next(run.path.glob("events.*.log"))
    decode = RunReader._read_logs

    def decode_then_write(self):  # the run writes one more frame during compaction
        decode(self)

        with open(log, "ab") as f:
            f.write(fmt.name_frame(99, "late"))
            ids, steps = array("I", [99]), array("q", [1])
            f.write(fmt.scalars_frame(ids, steps, array("d", [0.0]), array("d", [2.0])))

    monkeypatch.setattr(RunReader, "_read_logs", decode_then_write)
    compact_run(run.path)
    monkeypatch.undo()
    reader = RunReader(run.path)
    assert reader.parquet is None  # the logs are longer than what the file covers
    assert list(reader.scalars("late")[2]) == [2.0]


def test_scalars_are_yours_to_change_also_when_compacted():
    run = nb.init("own", capture_env=False, system_metrics=False, capture_console=False)

    for i in range(5):
        run.add_scalar("loss", float(i), step=i)

    run.flush()
    live = RunReader(run.path)
    _, _, v = live.scalars("loss")
    v *= 2  # from the logs
    assert list(live.scalars("loss")[2]) == [0.0, 1.0, 2.0, 3.0, 4.0]  # the cache is untouched
    run.finish()
    reader = RunReader(run.path)
    assert reader.parquet is not None
    _, _, v = reader.scalars("loss")
    v *= 2  # from data.parquet
    assert list(reader.scalars("loss")[2]) == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert not reader.scalars("loss", copy=False)[2].flags.writeable
