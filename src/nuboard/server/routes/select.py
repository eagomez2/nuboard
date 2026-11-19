"""Routes of the Select page: score the steps of a set of runs, and save picks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import BaseRoute, Route

from ... import _fs
from ...directions import DIRECTIONS
from ...selection import (
    PickError,
    checkpoint_step,
    complete_steps,
    delete_pick,
    pareto_mask,
    read_picks,
    save_pick,
)
from ..common import JSON
from ..context import Context

MAX_METRICS = 12
MAX_FRONT = 500  # shortlist rows sent; the count says how many there are
MAX_POINTS = 4000  # other rows sent for the scatter plot, a random sample beyond this


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the Select page's routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    store = ctx.store
    project_dir = ctx.project_dir

    def checkpoints(record: dict[str, Any], steps: np.ndarray, times: np.ndarray) -> list[dict]:
        """Return the artifact versions a run made, each with its step (see `checkpoint_step`)."""
        home = project_dir(record["project"])
        out = []

        for o in record.get("outputs") or []:
            if not isinstance(o, dict) or not isinstance(o.get("artifact"), str):
                continue

            pdir = home

            if o.get("project_path") and home is not None:
                pdir = Path(os.path.normpath(home / o["project_path"]))

            if pdir is None:
                continue

            manifest = _fs.read_json(
                pdir / "artifacts" / o["artifact"] / f"v{o.get('version')}" / "manifest.json", {}
            )
            step, exact = checkpoint_step(manifest or {}, steps, times)
            out.append(
                {
                    "artifact": o["artifact"],
                    "version": o.get("version"),
                    "project": o.get("project") or record["project"],
                    "type": (manifest or {}).get("type"),
                    "step": step,
                    "exact": exact,
                }
            )

        return out

    def score(keys: list[str], metrics: list[str], dirs: list[str]) -> dict[str, Any]:
        """Score every complete step of the runs in `keys` (see the `steps` route)."""
        coverage = dict.fromkeys(metrics, 0)
        unranked: list[dict[str, Any]] = []
        run_idx: list[np.ndarray] = []
        all_steps: list[np.ndarray] = []
        all_values: list[np.ndarray] = []
        runs: list[dict[str, Any]] = []

        for key in keys:
            record = catalog.get(key)
            reader = store.fresh_reader(key) if record is not None else None

            if record is None or reader is None:
                continue

            series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            stamps: list[tuple[np.ndarray, np.ndarray]] = []

            for m in metrics:
                s, t, v = reader.scalars(m, 0, copy=False)

                if len(s):
                    series[m] = (s, v)
                    stamps.append((s, t))
                    coverage[m] += 1

            steps, values, _ = complete_steps(series, metrics)
            missing = [m for m in metrics if m not in series]

            if missing or not len(steps):
                unranked.append(
                    {
                        "run": key,
                        "name": record["name"],
                        "project": record["project"],
                        "missing": missing,
                    }
                )

            if not len(steps):
                continue

            # when each step was logged, for the checkpoints that do not say their step
            if stamps:
                s_all = np.concatenate([s for s, _ in stamps])
                t_all = np.concatenate([t for _, t in stamps])
                order = np.argsort(t_all, kind="stable")
                s_all, t_all = s_all[order], t_all[order]
            else:
                s_all = t_all = np.empty(0)

            ckpts = checkpoints(record, s_all, t_all)

            for c in ckpts:  # the row a checkpoint goes with: its step, else the last one before
                if c["step"] is None:
                    c["row"] = None
                elif c["exact"]:
                    c["row"] = c["step"] if np.any(steps == c["step"]) else None
                else:
                    i = int(np.searchsorted(steps, c["step"], "right")) - 1
                    c["row"] = int(steps[max(i, 0)])

            runs.append(
                {
                    "key": key,
                    "id": record["id"],
                    "name": record["name"],
                    "project": record["project"],
                    "checkpoints": ckpts,
                }
            )
            run_idx.append(np.full(len(steps), len(runs) - 1))
            all_steps.append(steps)
            all_values.append(values)

        if run_idx:
            idx = np.concatenate(run_idx)
            steps = np.concatenate(all_steps)
            values = np.concatenate(all_values)
        else:
            idx = np.empty(0, np.int64)
            steps = np.empty(0, np.int64)
            values = np.empty((0, len(metrics)))

        front = pareto_mask(values, dirs)
        on = np.flatnonzero(front)
        # best first by the first metric, so the cut keeps the best of it
        first = values[on, 0] if len(on) else np.empty(0)
        on = on[np.argsort(first if dirs[0] == "min" else -first, kind="stable")][:MAX_FRONT]
        off = np.flatnonzero(~front)

        if len(off) > MAX_POINTS:
            off = np.sort(np.random.default_rng(0).choice(off, MAX_POINTS, replace=False))

        def rows(sel: np.ndarray) -> dict[str, list]:
            return {
                "run": idx[sel].tolist(),
                "step": steps[sel].tolist(),
                "values": values[sel].T.tolist() if len(sel) else [[] for _ in metrics],
            }

        return {
            "metrics": metrics,
            "directions": dirs,
            "runs": runs,
            "coverage": coverage,
            "unranked": unranked,
            "complete": len(steps),
            "front_count": int(front.sum()),
            "front": rows(on),
            "others": rows(off),
            "others_count": int((~front).sum()),
        }

    async def steps_route(request: Request) -> Response:
        """Score the steps of a set of runs on a few scalars.

        Query parameters: `runs` (comma-separated keys), `m` (a scalar, repeated, up to
        `MAX_METRICS`) and `d` (`min` or `max` for each `m`, in the same order). A run at a step
        is a row when every scalar was logged at that step with a finite value, on rank 0.

        The response holds `runs` (the runs that have rows, with the artifact versions each made
        as `checkpoints`: `step` is the step it belongs to and `exact` whether the version said
        so or it was guessed from when it was made; `row` is the row step it goes with),
        `coverage` (how many runs log each scalar), `unranked` (runs left out: the scalars they
        never log as `missing`, or none when the scalars never share a step), `complete` (rows),
        `front_count` and `front` (the rows no other row beats on every scalar, best first by
        the first scalar, at most `MAX_FRONT`), and `others` (a sample of the other rows, at
        most `MAX_POINTS`, with `others_count`). `front` and `others` are columns: `run` (index
        into `runs`), `step`, and `values` (one list per scalar).
        """
        qp = request.query_params
        keys = [k for k in qp.get("runs", "").split(",") if k]
        metrics = [m for m in qp.getlist("m") if m]
        dirs = qp.getlist("d")

        if not metrics or len(metrics) > MAX_METRICS:
            return PlainTextResponse(f"send 1 to {MAX_METRICS} scalars as m", 400)

        if len(dirs) != len(metrics) or any(d not in DIRECTIONS for d in dirs):
            return PlainTextResponse("send min or max as d for each scalar", 400)

        if len(set(metrics)) != len(metrics):
            return PlainTextResponse("each scalar can be chosen once", 400)

        return JSON(await run_in_threadpool(score, keys, metrics, dirs))

    def picks_get(request: Request) -> Response:
        """Return the picks of every project, or of the `project` query parameter.

        Each pick has the fields saved in `picks.json` plus `project`, and `key`: the run's
        catalog key, or null when the run is gone.
        """
        want = request.query_params.get("project")
        keys = {(r["project"], r["id"]): r["key"] for r in catalog.runs()}
        out = []

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            for pick in read_picks(pdir) if pdir is not None else []:
                out.append(
                    {**pick, "project": p["name"], "key": keys.get((p["name"], pick["run"]))}
                )

        return JSON({"picks": out})

    async def picks_save(request: Request) -> Response:
        """Save a pick in its project's `picks.json`, or delete one.

        The JSON body holds `project` and either `pick` (see `selection.save_pick`; with an `id`
        it replaces that pick) or `delete` (a pick id). Returns the saved pick, or what was
        deleted.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()

        if not isinstance(body, dict):
            return JSON({"error": "expected a JSON object"}, status_code=400)

        pdir = project_dir(str(body.get("project") or ""))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=404)

        try:
            if isinstance(body.get("pick"), dict):
                return JSON({"pick": save_pick(pdir, body["pick"])})

            if isinstance(body.get("delete"), str):
                return JSON(
                    {"deleted": body["delete"], "existed": delete_pick(pdir, body["delete"])}
                )
        except PickError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON({"error": "send a pick or an id to delete"}, status_code=400)

    return [
        Route("/api/steps", steps_route),
        Route("/api/picks", picks_get),
        Route("/api/picks", picks_save, methods=["POST"]),
    ]
