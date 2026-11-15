"""Routes for the run list, one run's details, files and timers, annotations and scalars."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
)
from starlette.routing import BaseRoute, Route

from ... import __version__, _fs
from ..._annotations import AnnotationsError, StaleEdit, check_expected, update_annotations
from ..._meta import FORMAT_VERSION, NAME
from ...artifacts import (
    UNLINKED,
)
from ...jobs import read_meta
from ...query import QueryError, parse
from ...reports import (
    check_field,
    read_fields,
)
from ..common import (
    ANNOTATION_FIELDS,
    JSON,
    _brief,
    _sweep_keys,
    send_file,
    text_part,
)
from ..context import Context
from ..data import path_inside
from ..runfiles import list_files
from ..tensorfiles import inspect_file


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the runs routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    store = ctx.store
    edit_artifacts = ctx.edit_artifacts
    read_only_reports = ctx.read_only_reports
    read_only_hypotheses = ctx.read_only_hypotheses
    lock_directions = ctx.lock_directions
    max_image_bytes = ctx.max_image_bytes
    max_text_bytes = ctx.max_text_bytes
    max_audio_bytes = ctx.max_audio_bytes
    record_or_404 = ctx.record_or_404
    project_dir = ctx.project_dir

    # -- routes ---------------------------------------------------------------
    async def info(request: Request) -> Response:
        """Return the app name and versions, the root folder and the projects with saved views."""
        root_path = catalog.root
        home = Path.home()

        try:
            display = "~/" + root_path.relative_to(home).as_posix()
        except ValueError:
            display = str(root_path)

        projects = []

        for p in catalog.projects():
            pdir = catalog.root if p["name"] == catalog.root.name else catalog.root / p["name"]
            views = (
                sorted(v.name for v in (pdir / "views").glob("*.json"))
                if (pdir / "views").exists()
                else []
            )
            projects.append({**p, "views": views})

        return JSON(
            {
                "name": NAME,
                "version": __version__,
                "format_version": FORMAT_VERSION,
                "root": str(root_path),
                "root_display": display,
                "projects": projects,
                "catalog_version": catalog.version,
                "edit_artifacts": edit_artifacts,
                "read_only_reports": read_only_reports,
                "read_only_hypotheses": read_only_hypotheses,
                "lock_directions": lock_directions,
                "upload_limits": {
                    "image": max_image_bytes,
                    "text": max_text_bytes,
                    "audio": max_audio_bytes,
                },
            }
        )

    def runs(request: Request) -> Response:
        """Return the run list, filtered and ordered by a query.

        Query parameters: `q` (the query; a parse error is returned in `error`
        and every run is listed), `project` (keep runs of that project and its
        subprojects), `metrics` (comma-separated metrics to include in each
        summary; all when absent) and `refresh` (`0` skips rescanning the
        folder). Without an `order by`, runs are newest first.
        """
        t0 = time.perf_counter()

        if request.query_params.get("refresh") != "0":
            catalog.refresh(full=True)

        q_text = request.query_params.get("q", "")
        error = None

        try:
            query = parse(q_text)
        except QueryError as exc:
            query, error = parse(""), str(exc)

        rows = catalog.runs()
        project = request.query_params.get("project")

        if project:
            rows = [
                r for r in rows if r["project"] == project or r["project"].startswith(project + "/")
            ]

        try:
            rows = query.apply(rows)
        except Exception as exc:  # defensive: a bad comparison must not 500
            error = str(exc)

        if not query.order_by:
            rows.sort(key=lambda r: r.get("started") or 0, reverse=True)

        metrics_param = request.query_params.get("metrics")
        metrics = set(metrics_param.split(",")) if metrics_param else None
        all_metrics: dict[str, int] = {}

        for r in rows:
            for m in r.get("summary") or {}:
                all_metrics[m] = all_metrics.get(m, 0) + 1

        return JSON(
            {
                "runs": [_brief(r, metrics) for r in rows],
                "total": catalog.count(),
                "query": query.to_json(),
                "error": error,
                "metrics": sorted(all_metrics),
                "version": catalog.version,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )

    def run_detail(request: Request) -> Response:
        """Return one run's record, metadata, files, ranks, media keys and annotations.

        Artifact versions in the metadata's `inputs` and `outputs` that were
        unlinked get `unlinked: true`.
        """
        key = request.path_params["key"]
        record = record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        meta = read_meta(path) or {}

        for ref in [*(meta.get("inputs") or []), *(meta.get("outputs") or [])]:
            if isinstance(ref, dict) and ref.get("artifact"):
                home = path.parent.parent / str(ref.get("project_path") or ".")
                folder = home / "artifacts" / UNLINKED / str(ref["artifact"])
                ref["unlinked"] = (folder / f"v{ref.get('version')}").is_dir()

        files_dir = path / "files"
        files = (
            sorted(p.relative_to(files_dir).as_posix() for p in files_dir.rglob("*") if p.is_file())
            if files_dir.exists()
            else []
        )
        reader = store.fresh_reader(key)
        ranks = reader.ranks() if reader else [0]
        media_keys: dict[str, dict[str, Any]] = {}

        if reader is not None:
            for entry in reader.media(latest=True):
                info = media_keys.setdefault(
                    entry.key, {"kind": entry.meta.get("kind"), "count": 0}
                )
                info["count"] += 1

            for text in reader.texts(latest=True):
                info = media_keys.setdefault(text.key, {"kind": "text", "count": 0})
                info["count"] += 1

        timing = False

        if reader is not None:
            from ...timings import timer_keys, timing_prefix

            timing = bool(timer_keys(reader, timing_prefix(meta)))

        return JSON(
            {
                "run": record,
                "meta": meta,
                "files": files,
                "ranks": ranks,
                "media": media_keys,
                "timing": timing,
                "annotations": _fs.read_json(path / "annotations.json", {}),
            }
        )

    def run_timing(request: Request) -> Response:
        """Return the summary of a run's timers for its Timing tab.

        Query parameter `rank`: a rank number (default 0) or `all` for every
        rank (per step the mean, with min and max across ranks).
        """
        key = request.path_params["key"]
        record_or_404(key)
        raw = request.query_params.get("rank", "0")

        try:
            rank = None if raw == "all" else int(raw)
        except ValueError:
            return PlainTextResponse("rank must be a number or 'all'", 400)

        return JSON(store.timing(key, rank) or {})

    def run_timing_spans(request: Request) -> Response:
        """Return the spans of one step of a run (query parameter `step`; default the last)."""
        key = request.path_params["key"]
        record_or_404(key)
        raw = request.query_params.get("step")

        try:
            step = int(raw) if raw not in (None, "") else None
        except ValueError:
            return PlainTextResponse("step must be a number", 400)

        return JSON(store.timing_spans(key, step) or {})

    def run_file(request: Request) -> Response:
        """Return a file from the run's `files/` folder as text (2 MB at most).

        The first 2 MB, or with `tail=1` the last 2 MB, as for a long console log.
        """
        key = request.path_params["key"]
        record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        target = path_inside(path / "files", request.path_params["path"])

        if target is None or not target.is_file():
            return PlainTextResponse("not found", 404)

        return text_part(target, request.query_params.get("tail") == "1")

    def run_folder_file(request: Request) -> Path | None:
        """The file a request names inside a run folder, or None (also for symlinks out)."""
        key = request.path_params["key"]
        record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        target = path_inside(path, request.path_params["path"])
        return target if target is not None and target.is_file() else None

    def run_tree(request: Request) -> Response:
        """List every file of a run folder with its size, date and kind (for the Files tab)."""
        key = request.path_params["key"]
        record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        return JSON(list_files(path))

    def run_text(request: Request) -> Response:
        """Return any file of a run folder as text: its first (or with `tail=1` last) 2 MB."""
        target = run_folder_file(request)

        if target is None:
            return PlainTextResponse("not found", 404)

        return text_part(target, request.query_params.get("tail") == "1")

    def run_raw(request: Request) -> Response:
        """Send a run file as is; `download=1` saves it even if it is an image."""
        target = run_folder_file(request)

        if target is None:
            return PlainTextResponse("not found", 404)

        return send_file(target, request.query_params.get("download") == "1")

    async def run_inspect(request: Request) -> Response:
        """Describe the tensors in a checkpoint or array file of a run, without loading them."""
        target = run_folder_file(request)

        if target is None:
            return JSON({"error": "not found"}, status_code=404)

        return JSON(await run_in_threadpool(inspect_file, target))

    async def annotate(request: Request) -> Response:
        """Update annotations of one run (`PATCH`) or of the runs in `keys` (`POST`).

        The JSON body holds `patch` with any of `starred`, `archived`,
        `reviewed`, `notes`, `tags` and `fields`. Fields are merged key by key;
        a null or empty value removes a field. Returns the updated keys and
        records.

        An optional `expect` maps run keys to the values the edit started from
        (`notes`, and `fields` by name). A run whose values changed since is not
        saved: the reply is a 409 with `conflicts`, its current values by key,
        and `updated`, the runs that were saved.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        keys = body.get("keys") or (
            [request.path_params["key"]] if "key" in request.path_params else []
        )
        raw: dict[str, Any] = dict(body.get("patch") or {})
        fields_raw = raw.pop("fields", None)
        patch: dict[str, Any] = {
            k: ANNOTATION_FIELDS[k](v) if k != "tags" else [str(t) for t in v]
            for k, v in raw.items()
            if k in ANNOTATION_FIELDS
        }
        fields_patch: dict[str, Any] = {}

        if isinstance(fields_raw, dict):  # merged key by key; null removes a field
            fields_patch = {
                str(k)[:64]: v
                for k, v in fields_raw.items()
                if v is None
                or isinstance(v, (str, int, float, bool))
                or (isinstance(v, list) and all(isinstance(x, str) for x in v))  # tags
            }

        if fields_patch:  # values must fit their project's property definitions
            projects = {(catalog.get(k) or {}).get("project") for k in keys} - {None}

            for name in projects:
                pdir = project_dir(str(name))
                defs = {f["name"]: f for f in read_fields(pdir)} if pdir else {}

                for k, v in fields_patch.items():
                    if k in defs:
                        try:
                            check_field(defs[k], v)
                        except ValueError as exc:
                            return PlainTextResponse(str(exc), 400)

        expect = body.get("expect") if isinstance(body.get("expect"), dict) else {}

        def change(ann: dict[str, Any], expected: Any = None, logged_notes: str = "") -> None:
            """Apply the patch to one run's annotations, if they are as `expected`."""
            check_expected(ann, expected, logged_notes)
            ann.update(patch)

            if fields_patch:
                fields = dict(ann.get("fields") or {})

                for k, v in fields_patch.items():
                    if v is None or v == "" or v == []:
                        fields.pop(k, None)
                    else:
                        fields[k] = v

                ann["fields"] = fields

        def write() -> tuple[list[str], str | None, dict[str, Any]]:
            """Apply the patch to each run; return the updated keys, any refusal and conflicts."""
            done: list[str] = []
            error = None
            conflicts: dict[str, Any] = {}

            try:
                for key in keys:
                    path = catalog.path_of(key)

                    if path is None:
                        continue

                    expected = expect.get(key)
                    logged = str((read_meta(path) or {}).get("notes") or "") if expected else ""

                    try:
                        update_annotations(
                            path, lambda ann, e=expected, n=logged: change(ann, e, n)
                        )
                    except StaleEdit as exc:  # the other runs are still saved
                        conflicts[key] = exc.current
                        continue

                    done.append(key)
            except AnnotationsError as exc:
                error = str(exc)

                if done:
                    error += f" ({len(done)} of {len(keys)} runs were saved before it)"
            finally:
                catalog.refresh(full=True)

            return done, error, conflicts

        done, error, conflicts = await run_in_threadpool(write)

        if error:
            return PlainTextResponse(error, 409)

        if conflicts:
            n = len(conflicts)
            return JSON(
                {
                    "error": f"{'a run' if n == 1 else f'{n} runs'} changed since the edit began",
                    "conflicts": conflicts,
                    "updated": done,
                },
                status_code=409,
            )

        return JSON({"updated": done, "runs": [catalog.get(k) for k in done]})

    def metrics(request: Request) -> Response:
        """Return the metric names of the runs in `runs` (comma-separated), with run counts."""
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        counts: dict[str, int] = {}

        for key in keys:
            record = catalog.get(key)

            if record is None:
                continue

            names = list(record.get("summary") or {})

            if not names:  # live run before its first heartbeat: read the log
                reader = store.fresh_reader(key)
                names = reader.scalar_names() if reader else []

            for m in names:
                counts[m] = counts.get(m, 0) + 1

        return JSON({"metrics": [{"name": m, "runs": n} for m, n in sorted(counts.items())]})

    def sweep_keys(request: Request) -> Response:
        """Return the config keys whose value differs between runs, with each run's value.

        Query parameters: `runs` (comma-separated keys) or, without it,
        `project` (its runs and its subprojects' runs). Unlike the run list,
        whose configs are cut to 64 values, every key is considered (see
        `_sweep_keys`), and the artifact versions each run used are added as
        `inputs.<artifact>` keys. The response holds `keys` (in config order,
        then inputs) and `values` (key to run key to value).
        """
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        project = request.query_params.get("project")

        if keys:
            records = [r for r in (catalog.get(k) for k in keys) if r is not None]
        elif project:
            records = [
                r
                for r in catalog.runs()
                if r["project"] == project or r["project"].startswith(project + "/")
            ]
        else:
            records = []

        values = _sweep_keys(
            {r["key"]: r.get("config") or {} for r in records},
            {r["key"]: r.get("inputs") or [] for r in records},
        )
        return JSON({"keys": list(values), "values": values})

    def scalars(request: Request) -> Response:
        """Return chart data for one metric as an Arrow IPC stream (see `Store.chart`).

        Query parameters: `runs` (comma-separated keys), `metric` (required),
        `x` (x axis, default `step`), `group`, `agg` (default `std`), `points`
        (clamped to 16-20000, default 1000), `rank` (default 0), `xmin` and
        `xmax`, and `logx` (`1` for a log x-axis). Invalid values give a 400
        response.
        """
        qp = request.query_params
        keys = [k for k in qp.get("runs", "").split(",") if k]
        metric = qp.get("metric")

        if not metric:
            return PlainTextResponse("metric is required", 400)

        def opt(name: str) -> float | None:
            """Return a float query parameter, or None when absent, empty or `null`."""
            v = qp.get(name)
            return float(v) if v not in (None, "", "null") else None

        try:
            body = store.chart(
                keys,
                metric,
                x_kind=qp.get("x", "step"),
                group_by=qp.get("group") or None,
                agg=qp.get("agg", "std"),
                points=max(16, min(int(qp.get("points", 1000)), 20000)),
                rank=int(qp.get("rank", 0)),
                xmin=opt("xmin"),
                xmax=opt("xmax"),
                logx=qp.get("logx") == "1",
            )
        except ValueError as exc:
            return PlainTextResponse(str(exc), 400)

        return Response(body, media_type="application/vnd.apache.arrow.stream")

    def alerts(request: Request) -> Response:
        """Return the health alerts of the known runs in `runs` (comma-separated keys)."""
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        return JSON({"alerts": {k: store.alerts(k) for k in keys if catalog.get(k)}})

    return [
        Route("/api/info", info),
        Route("/api/runs", runs),
        Route("/api/runs/annotate", annotate, methods=["POST"]),
        Route("/api/runs/{key}", run_detail),
        Route("/api/runs/{key}", annotate, methods=["PATCH"]),
        Route("/api/runs/{key}/files/{path:path}", run_file),
        Route("/api/runs/{key}/tree", run_tree),
        Route("/api/runs/{key}/timing", run_timing),
        Route("/api/runs/{key}/timing/spans", run_timing_spans),
        Route("/api/runs/{key}/text/{path:path}", run_text),
        Route("/api/runs/{key}/raw/{path:path}", run_raw),
        Route("/api/runs/{key}/inspect/{path:path}", run_inspect),
        Route("/api/metrics", metrics),
        Route("/api/scalars", scalars),
        Route("/api/sweep-keys", sweep_keys),
        Route("/api/alerts", alerts),
    ]
