"""Rough performance checks against the targets in the project brief.

uv run python benchmarks/bench.py
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import nuboard as nb
from nuboard.catalog import Catalog
from nuboard.reader import RunReader


def main() -> None:
    """Run the benchmarks and print the timings next to their targets.

    Measures `Run.log` overhead, reading a live log, compacting to Parquet,
    reading a metric from Parquet, and opening and refreshing a catalog of 5000
    runs. Data goes to a temporary folder, removed afterwards unless `KEEP` is set.
    """
    root = Path(tempfile.mkdtemp())
    data = {f"metric_{i:02d}": float(i) for i in range(50)}

    run = nb.init("bench", dir=root, capture_env=False, compact=False)
    n = 20_000
    t0 = time.perf_counter()

    for step in range(n):
        run.add_scalar(data, step=step)

    per_call = (time.perf_counter() - t0) / n
    t1 = time.perf_counter()
    run.finish()
    print(f"log() of a 50-metric dict:      {per_call * 1e6:6.1f} µs per call (target < 50 µs)")
    print(
        f"  final flush of {n * 50 / 1e6:.1f}M points:      "
        f"{time.perf_counter() - t1:6.2f} s (background)"
    )

    run = nb.init("bench", name="million", dir=root, capture_env=False, compact=False)

    for step in range(100_000):
        run.add_scalar({f"m{i}": step * 0.5 + i for i in range(10)}, step=step)

    run.finish()
    size = sum(p.stat().st_size for p in run.path.glob("events.*"))
    t0 = time.perf_counter()
    reader = RunReader(run.path)
    reader.refresh()
    total = sum(len(s[0]) for s in reader.all_scalars().values())
    print(
        f"read {total / 1e6:.0f}M points from the live log:   "
        f"{time.perf_counter() - t0:6.3f} s (target < 0.1 s), "
        f"{size / 1e6:.0f} MB on disk"
    )

    from nuboard.compact import compact_run

    t0 = time.perf_counter()
    compact_run(run.path)
    print(
        f"compact to Parquet:              {time.perf_counter() - t0:6.2f} s, "
        f"{(run.path / 'data.parquet').stat().st_size / 1e6:.1f} MB"
    )
    reader = RunReader(run.path)
    assert reader.parquet is not None
    times = []

    for name in ("m3", "m4", "m3"):
        t0 = time.perf_counter()
        reader.scalars(name)
        times.append((time.perf_counter() - t0) * 1e3)

    print(
        f"one metric (100k points) from Parquet: first {times[0]:.1f} ms, "
        f"warm {min(times[1:]):.1f} ms"
    )

    many = root / "many" / "proj" / "runs"
    meta = json.dumps(
        {
            "format_version": 1,
            "status": "finished",
            "config": {"lr": 0.1},
            "summary": {
                f"m{i}": {"last": 1.0, "min": 0.5, "max": 2, "count": 1, "step": 0, "nonfinite": 0}
                for i in range(20)
            },
        }
    )

    for i in range(5000):
        d = many / f"20250101-0000_r{i}_aaaaaa"
        d.mkdir(parents=True)
        (d / "run.json").write_text(meta)

    cache = root / "cache"
    Catalog(root / "many", cache=cache).refresh()  # cold build
    t0 = time.perf_counter()
    cat = Catalog(root / "many", cache=cache)
    print(f"open catalog of 5000 runs (server start): {(time.perf_counter() - t0) * 1e3:5.0f} ms")
    t0 = time.perf_counter()
    cat.refresh()
    print(
        f"refresh + list {len(cat.runs())} runs (per request): "
        f"{(time.perf_counter() - t0) * 1e3:5.0f} ms (target < 200 ms)"
    )

    if os.environ.get("KEEP") is None:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
