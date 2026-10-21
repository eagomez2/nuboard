"""Jobs: more than one process writing to the same run.

A run's main job is whatever process created it; its state lives in `run.json`
as always. Another process can join the run with `init(..., run_id=ID, job="eval")`.
Such a helper job writes its scalars and media to its own session files and
its state (status, heartbeat, summary, inputs, outputs, baselines) to
`jobs/<job>.json`, never to `run.json`, so the two cannot overwrite each other.

`read_meta` returns `run.json` with the helper jobs merged in: their summaries,
baselines, inputs and outputs are added, and a `jobs` list describes each one.
The run's own status stays the main job's.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import _fs

JOBS = "jobs"
MAIN = "main"


def job_path(run_dir: Path, job: str) -> Path:
    """Return the state file of a helper job: `<run>/jobs/<job>.json`."""
    return run_dir / JOBS / f"{job}.json"


def read_jobs(run_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Return the state of every helper job of a run, sorted by name."""
    folder = Path(run_dir) / JOBS

    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return []

    out = []

    for n in names:
        data = _fs.read_json(folder / n, None)

        if isinstance(data, dict):
            data.setdefault("job", n[:-5])
            out.append(data)

    return out


def merge_jobs(meta: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge helper jobs into a run's metadata (in place) and return it.

    The main job's summary and baselines win when a helper logged the same name.
    Inputs and outputs of a helper get `job` set to its name.

    Args:
        meta: Contents of `run.json`.
        jobs: Helper job states, from `read_jobs`.

    Returns:
        `meta`, with `jobs` listing `{job, status, started, ended, heartbeat, error,
        host}` for each helper.
    """

    if not jobs:
        return meta

    summary = dict(meta.get("summary") or {})
    baselines = dict(meta.get("baselines") or {})
    inputs = list(meta.get("inputs") or [])
    outputs = list(meta.get("outputs") or [])
    listed = []

    for j in jobs:
        name = j["job"]

        for k, v in (j.get("summary") or {}).items():
            summary.setdefault(k, v)

        for k, v in (j.get("baselines") or {}).items():
            baselines.setdefault(k, v)

        inputs += [{**r, "job": name} for r in j.get("inputs") or [] if isinstance(r, dict)]
        outputs += [{**r, "job": name} for r in j.get("outputs") or [] if isinstance(r, dict)]
        listed.append(
            {
                "job": name,
                "status": j.get("status"),
                "started": j.get("started"),
                "ended": j.get("ended"),
                "heartbeat": j.get("heartbeat"),
                "error": (j.get("exit") or {}).get("error"),
                "host": (j.get("env") or {}).get("host"),
            }
        )

    meta.update(summary=summary, baselines=baselines, inputs=inputs, outputs=outputs, jobs=listed)
    return meta


def read_meta(run_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Return a run's `run.json` with its helper jobs merged in, or None if unreadable."""
    meta = _fs.read_json(Path(run_dir) / "run.json", None)
    return merge_jobs(meta, read_jobs(run_dir)) if isinstance(meta, dict) else None
