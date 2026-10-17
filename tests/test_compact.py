"""Compaction to Parquet and the reader's choice between Parquet and logs."""

from __future__ import annotations

import json
import time

import numpy as np
import pyarrow.parquet as pq

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
