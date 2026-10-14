"""Compaction of a run's event logs into one `data.parquet` (needs PyArrow + NumPy).

Layout: rows sorted by metric, zoom level, rank, step; exactly one row group
per (metric, level); a JSON row-group map in the file's key/value metadata so
one metric at one level is a single row-group read.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import _fs
from ._meta import FORMAT_VERSION
from .alerts import check_run
from .reader import RunReader
from .series import zoom_levels

SCHEMA = pa.schema(
    [
        ("metric", pa.string()),
        ("level", pa.int8()),
        ("rank", pa.int32()),
        ("step", pa.int64()),
        ("time", pa.float64()),
        ("value", pa.float64()),
        ("vmin", pa.float64()),
        ("vmax", pa.float64()),
    ]
)


def compact_run(path: str | os.PathLike[str]) -> Path:
    """Write `data.parquet` for the run at `path`.

    The file is written to a temporary name and then moved into place. Also
    records in `run.json` which log bytes the file covers and the run's health
    alerts (see `NAME.alerts`).

    Args:
        path: The run folder.

    Returns:
        Path of the written `data.parquet`.
    """
    path = Path(path)
    reader = RunReader(path)
    reader._parquet_checked = True  # always decode the logs themselves
    reader.refresh()
    sizes = reader.log_sizes()
    per_metric: dict[str, list[tuple[int, list[tuple[np.ndarray, ...]]]]] = {}

    for rank in reader.ranks():
        for metric, (s, t, v) in reader.all_scalars(rank).items():
            per_metric.setdefault(metric, []).append((rank, zoom_levels(s, t, v)))

    tables: list[pa.Table] = []
    row_groups: dict[str, list[list[int]]] = {}

    for metric in sorted(per_metric):
        ranks = per_metric[metric]
        n_levels = max(len(levels) for _, levels in ranks)
        row_groups[metric] = []

        for level in range(n_levels):
            cols: list[list[np.ndarray]] = [[] for _ in range(6)]

            for rank, levels in ranks:
                s, t, v, lo, hi = levels[min(level, len(levels) - 1)]
                cols[0].append(np.full(len(s), rank, "i4"))

                for i, arr in enumerate((s, t, v, lo, hi), start=1):
                    cols[i].append(arr)

            arrays = [np.concatenate(c) for c in cols]
            n = len(arrays[0])
            table = pa.table(
                {
                    "metric": pa.array([metric] * n, pa.string()),
                    "level": pa.array(np.full(n, level, "i1")),
                    "rank": arrays[0],
                    "step": arrays[1].astype("i8"),
                    "time": arrays[2],
                    "value": arrays[3],
                    "vmin": arrays[4],
                    "vmax": arrays[5],
                },
                schema=SCHEMA,
            )
            row_groups[metric].append([len(tables), n])
            tables.append(table)

    schema = SCHEMA.with_metadata(
        {
            "row_groups": json.dumps(row_groups),
            "format_version": str(FORMAT_VERSION),
        }
    )
    target = path / "data.parquet"
    tmp = path / f".data.parquet.{_fs.random_suffix(4)}.tmp"

    with pq.ParquetWriter(tmp, schema, compression="zstd") as writer:
        for table in tables:
            writer.write_table(
                table.replace_schema_metadata(schema.metadata),
                row_group_size=max(1, table.num_rows),
            )

    os.replace(tmp, target)
    meta = _fs.read_json(path / "run.json", {})

    if meta:
        meta["compacted"] = {"bytes": sizes, "time": time.time()}
        meta["alerts"] = check_run(reader)
        _fs.atomic_write_json(path / "run.json", meta)

    return target
