"""Starlette application behind `NAME up`."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import math
import os
import re
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__, _fs
from .._meta import FORMAT_VERSION, NAME
from ..artifacts import (
    UNLINKED,
    add_artifact,
    find_artifact_projects,
    restore_artifact,
    unlink_artifact,
    version_folders,
)
from ..catalog import Catalog
from ..catalog import cache_dir as default_cache_dir
from ..collection import delete_collection, list_collections, save_collection
from ..jobs import read_meta
from ..query import QueryError, parse
from ..reports import (
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_BYTES,
    MediaRef,
    UploadError,
    check_field,
    clean_audio_notes,
    export_report,
    parse_ref,
    read_fields,
    report_names,
    report_path,
    save_fields,
    save_report,
    save_snapshot,
    save_upload,
    served_type,
)
from .auth import Guard
from .data import Store, path_inside
from .runfiles import IMAGE_SUFFIXES, change_pins, list_files, read_pins
from .storage import Meter
from .tensorfiles import inspect_file

STATIC = Path(__file__).resolve().parent.parent / "static"
ANNOTATION_FIELDS = {
    "starred": bool,
    "archived": bool,
    "reviewed": bool,
    "notes": str,
    "tags": list,
    "fields": dict,
}
TEXT_LIMIT = 2_000_000


def _safe(obj: Any) -> Any:
    """Make floats JSON-compliant (NaN/Inf become strings) recursively."""

    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj

        return "nan" if math.isnan(obj) else ("inf" if obj > 0 else "-inf")

    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]

    return obj


class JSON(JSONResponse):
    """Compact UTF-8 JSON response that also accepts NaN, infinities and arbitrary objects.

    Non-finite floats are sent as the strings `"nan"`, `"inf"` and `"-inf"`, and
    objects JSON cannot encode are sent as their `str()`.
    """

    def render(self, content: Any) -> bytes:
        """Encode `content` as compact UTF-8 JSON.

        Args:
            content: The value to send.

        Returns:
            The encoded body.
        """
        return json.dumps(
            _safe(content), ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")


def _read_only() -> JSONResponse:
    """The response to a change of a report on a server started with `--read-only-reports`."""
    return JSON(
        {"error": "reports are read-only on this server (--read-only-reports)"}, status_code=403
    )


def _config_leaves(config: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield the leaves of a nested config as `(dotted key, value)`, in config order."""

    def walk(obj: Any, prefix: str) -> Iterator[tuple[str, Any]]:
        """Yield the leaves of `obj` under keys starting with `prefix`."""

        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from walk(v, f"{prefix}{k}.")
        else:
            yield prefix[:-1], obj

    return walk(config, "")


def _flat_config(config: dict[str, Any], limit: int = 64) -> dict[str, Any]:
    """Flatten a nested config to at most `limit` dotted keys, shortening long values.

    Strings over 80 characters are cut with `...`; lists become JSON text cut to
    80 characters.
    """
    out: dict[str, Any] = {}

    for key, value in itertools.islice(_config_leaves(config), limit):
        if isinstance(value, str) and len(value) > 80:
            value = value[:77] + "..."
        elif isinstance(value, list):
            value = json.dumps(value, default=str)[:80]

        out[key] = value

    return out


def _input_versions(inputs: list[Any]) -> dict[str, str]:
    """Return `inputs.<artifact>` keys with the version a run used (`v3`; `v1+v3` for several).

    Args:
        inputs: The run's `inputs` entries (`{"artifact": ..., "version": ...}`).

    Returns:
        One key per artifact name, in first-use order.
    """
    versions: dict[str, list[str]] = {}

    for ref in inputs:
        if not isinstance(ref, dict) or not isinstance(ref.get("artifact"), str):
            continue

        label = f"v{ref.get('version')}"
        seen = versions.setdefault(f"inputs.{ref['artifact']}", [])

        if label not in seen:
            seen.append(label)

    return {key: "+".join(labels) for key, labels in versions.items()}


def _sweep_keys(
    configs: dict[str, dict[str, Any]], inputs: dict[str, list[Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Return the flattened config keys whose value differs between runs, with no cap.

    Args:
        configs: Each run's nested config, by run key.
        inputs: Each run's `inputs` (artifact versions it used), by run key.
            Their versions become `inputs.<artifact>` keys after the config
            keys, unless the config has a key of that name.

    Returns:
        For each differing key, in config order, its value per run key. Runs
        without the key are left out, and a key counts as differing when the
        runs that have it hold at least two distinct values. Lists and dicts
        are sent as JSON text.
    """
    values: dict[str, dict[str, Any]] = {}

    for run_key, config in configs.items():
        for key, value in _config_leaves(config):
            if isinstance(value, (list, tuple, dict)):
                value = json.dumps(value, default=str)

            values.setdefault(key, {})[run_key] = value

    from_config = set(values)

    for run_key, refs in (inputs or {}).items():
        for key, version in _input_versions(refs).items():
            if key not in from_config:
                values.setdefault(key, {})[run_key] = version

    return {
        key: per_run
        for key, per_run in values.items()
        if len({json.dumps(v, default=str) for v in per_run.values()}) > 1
    }


def _brief(record: dict[str, Any], metrics: set[str] | None) -> dict[str, Any]:
    """Return the run-list projection of a catalog record (keeps the payload small).

    The config is flattened, the summary is limited to `metrics` (all metrics
    when None), `baselines` is reduced to the names of the scalars that have
    one, and `metric_count` and `nonfinite` (metrics with non-finite values)
    are added.
    """
    out = {
        k: v
        for k, v in record.items()
        if k not in ("config", "summary", "baselines", "inputs", "outputs", "error", "compacted")
    }
    out["config"] = _flat_config(record.get("config") or {})
    summary = record.get("summary") or {}
    out["summary"] = (
        summary if metrics is None else {m: summary[m] for m in metrics if m in summary}
    )
    out["metric_count"] = len(summary)
    out["baselines"] = sorted(record.get("baselines") or {})
    out["nonfinite"] = sorted(m for m, s in summary.items() if s.get("nonfinite"))
    return out


class Hub:
    """Polls the folder once for all clients and fans changes out over SSE.

    Args:
        store: The store whose catalog and logs are polled.

    Attributes:
        store: The polled store.
        queues: One queue of encoded SSE messages per connected client.
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.queues: set[asyncio.Queue[str]] = set()
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Poll for changes forever while clients are connected.

        Every 1.5 s, the catalog is refreshed (only running runs, plus a full
        rescan every 8 s) and live runs' logs are checked for growth. Changed
        runs are announced as a `runs` event and grown logs as a `data` event.
        Errors while polling are ignored so the loop keeps running.
        """
        last_full = time.time()

        while True:
            await asyncio.sleep(1.5)

            if not self.queues:
                continue

            full = time.time() - last_full > 8

            if full:
                last_full = time.time()

            try:
                changed = await run_in_threadpool(self.store.catalog.refresh, full)
                grown = await run_in_threadpool(self.store.grown_logs)
            except Exception:  # pragma: no cover - keep the loop alive
                continue

            if changed:
                self._send(
                    "runs", {"changed": sorted(changed), "version": self.store.catalog.version}
                )

            if grown:
                self._send("data", {"changed": sorted(grown)})

    def _send(self, event: str, data: dict[str, Any]) -> None:
        """Queue an SSE message with the given event name and JSON data for every client."""
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"

        for q in list(self.queues):
            q.put_nowait(msg)


def create_app(
    root: str | os.PathLike[str],
    *,
    cache_dir: Path | None = None,
    allowed_hosts: list[str] | None = None,
    token: str | None = None,
    edit_artifacts: bool = False,
    read_only_reports: bool = False,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_text_bytes: int = MAX_TEXT_BYTES,
    max_audio_bytes: int = MAX_AUDIO_BYTES,
) -> Starlette:
    """Create the viewer's Starlette app for a folder of runs.

    The app serves the JSON API under `/api`, a server-sent event stream of
    changes at `/api/stream`, and the built frontend for every other path.
    Responses of 2 KB or more are gzipped.

    Args:
        root: Folder holding the runs.
        cache_dir: Folder for the catalog cache, or None for the catalog's default.
        allowed_hosts: Accepted `Host` header values, or None to accept any host.
        token: Access token every request must carry (see `auth.Guard`), or None
            for an open viewer.
        edit_artifacts: Allow adding artifact versions (as references to paths
            on this machine) and unlinking and restoring them. Without it those
            requests are refused.
        read_only_reports: Refuse every change to reports: saving, snapshots
            and uploads, as on a shared server.
        max_image_bytes: Size limit of an image uploaded into a report.
        max_text_bytes: Size limit of a text file uploaded into a report.
        max_audio_bytes: Size limit of an audio file uploaded into a report.

    Returns:
        The app. Its `state.store` holds the `Store` it reads runs through.
    """
    catalog = Catalog(root, cache=cache_dir)
    catalog.refresh()
    store = Store(catalog)
    hub = Hub(store)

    def record_or_404(key: str) -> dict[str, Any]:
        """Return a run's catalog record, refreshing once if missing; else raise `_NotFound`."""
        record = catalog.get(key)

        if record is None:
            catalog.refresh()
            record = catalog.get(key)

        if record is None:
            raise _NotFound(key)

        return record

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
                "total": len(catalog.runs()),
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
            for entry in reader.media():
                info = media_keys.setdefault(
                    entry.key, {"kind": entry.meta.get("kind"), "count": 0}
                )
                info["count"] += 1

            for text in reader.texts():
                info = media_keys.setdefault(text.key, {"kind": "text", "count": 0})
                info["count"] += 1

        return JSON(
            {
                "run": record,
                "meta": meta,
                "files": files,
                "ranks": ranks,
                "media": media_keys,
                "annotations": _fs.read_json(path / "annotations.json", {}),
            }
        )

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

        if request.query_params.get("tail") == "1":
            with target.open("rb") as f:
                f.seek(max(0, target.stat().st_size - TEXT_LIMIT))
                data = f.read()
        else:
            data = target.read_bytes()[:TEXT_LIMIT]

        return PlainTextResponse(data.decode("utf-8", errors="replace"))

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

        size = target.stat().st_size

        with target.open("rb") as f:
            if request.query_params.get("tail") == "1":
                f.seek(max(0, size - TEXT_LIMIT))

            data = f.read(TEXT_LIMIT)

        return PlainTextResponse(
            data.decode("utf-8", errors="replace"),
            headers={"X-Truncated": "1" if size > TEXT_LIMIT else "0"},
        )

    def run_raw(request: Request) -> Response:
        """Send a run file as is: images inline, anything else (or with `download=1`) as a download.

        Nothing is ever served as HTML or script, so a logged file cannot run in
        the viewer's origin.
        """
        target = run_folder_file(request)

        if target is None:
            return PlainTextResponse("not found", 404)

        image = IMAGE_SUFFIXES.get(target.suffix.lower())
        download = request.query_params.get("download") == "1" or image is None
        return FileResponse(
            target,
            media_type=image or "application/octet-stream",
            filename=target.name if download else None,
            content_disposition_type="attachment" if download else "inline",
            # Checkpoints can be GBs: send them as they are, not gzipped on the fly
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
                "Content-Encoding": "identity",
            },
        )

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

        def write() -> list[str]:
            """Apply the patch to each known run and return the updated keys."""
            done = []

            for key in keys:
                path = catalog.path_of(key)

                if path is None:
                    continue

                ann = _fs.read_json(path / "annotations.json", {}) or {}
                ann.update(patch)

                if fields_patch:
                    fields = dict(ann.get("fields") or {})

                    for k, v in fields_patch.items():
                        if v is None or v == "" or v == []:
                            fields.pop(k, None)
                        else:
                            fields[k] = v

                    ann["fields"] = fields

                _fs.atomic_write_json(path / "annotations.json", ann)
                done.append(key)

            catalog.refresh(full=True)
            return done

        done = await run_in_threadpool(write)
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
        `xmax`. Invalid values give a 400 response.
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
            )
        except ValueError as exc:
            return PlainTextResponse(str(exc), 400)

        return Response(body, media_type="application/vnd.apache.arrow.stream")

    def audio_notes_of(key: str) -> dict[str, Any]:
        """Return a run's audio notes, by `<media key>@<step>`."""
        path = catalog.path_of(key)
        ann = _fs.read_json(path / "annotations.json", {}) if path else {}
        notes = (ann or {}).get("audio_notes")
        return notes if isinstance(notes, dict) else {}

    def with_notes(item: dict[str, Any], notes: dict[str, Any]) -> dict[str, Any]:
        """Add the notes of an audio item to its media list entry."""
        found = notes.get(f"{item['key']}@{item['step']}")
        return {**item, "notes": found} if found else item

    async def set_audio_notes(request: Request) -> Response:
        """Replace the notes of one audio item of a run (`PUT`).

        The JSON body holds `item` (`<media key>@<step>`) and `notes`, a list
        of `{id, start, end, text}`; an empty list removes the item's notes.
        Returns the stored notes.
        """
        key = request.path_params["key"]
        path = catalog.path_of(key)

        if path is None:
            return PlainTextResponse("unknown run", 404)

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        item = str(body.get("item") or "")

        if not re.fullmatch(r".+@-?\d+", item):
            return PlainTextResponse("item must be <media key>@<step>", 400)

        try:
            notes = clean_audio_notes(body.get("notes"))
        except ValueError as exc:
            return PlainTextResponse(str(exc), 400)

        def write() -> None:
            """Store the notes in the run's annotations.json."""
            ann = _fs.read_json(path / "annotations.json", {}) or {}
            per = dict(ann.get("audio_notes") or {})

            if notes:
                per[item] = notes
            else:
                per.pop(item, None)

            if per:
                ann["audio_notes"] = per
            else:
                ann.pop("audio_notes", None)

            _fs.atomic_write_json(path / "annotations.json", ann)

        await run_in_threadpool(write)
        return JSON({"notes": notes})

    def media_list(request: Request) -> Response:
        """Return a run's media and text entries.

        Query parameters: `rank` (default 0) and `key` (only entries with that
        media key). Media entries carry their `index` for `media_blob`.
        """
        key = request.path_params["key"]
        record_or_404(key)
        reader = store.fresh_reader(key)
        rank = int(request.query_params.get("rank", 0))
        want = request.query_params.get("key")
        items: list[dict[str, Any]] = []
        notes = audio_notes_of(key) if rank == 0 else {}

        if reader is not None:
            for i, e in enumerate(reader.media(rank=rank)):
                if want is None or e.key == want:
                    item = {"key": e.key, "step": e.step, "time": e.time, "index": i, **e.meta}
                    items.append(with_notes(item, notes))

            for t in reader.texts(rank=rank):
                if want is None or t.key == want:
                    items.append(
                        {
                            "key": t.key,
                            "step": t.step,
                            "time": t.time,
                            "kind": "text",
                            "mime": "text/plain",
                            "text": t.text,
                        }
                    )

        return JSON({"items": items})

    def media_blob(request: Request) -> Response:
        """Return the bytes of the media entry at `index` for the given `rank` query parameter.

        Responses are cached as immutable. HTML is sent with a sandbox CSP.
        Audio and video support single byte-range requests.
        """
        key = request.path_params["key"]
        record_or_404(key)
        reader = store.fresh_reader(key)
        rank = int(request.query_params.get("rank", 0))
        entries = reader.media(rank=rank) if reader else []
        index = int(request.path_params["index"])

        if not 0 <= index < len(entries):
            return PlainTextResponse("not found", 404)

        entry = entries[index]
        assert reader is not None
        headers = {"Cache-Control": "max-age=31536000, immutable"}

        if entry.meta.get("mime") == "text/html":  # rendered only inside a sandboxed iframe
            headers["Content-Security-Policy"] = "sandbox allow-scripts"

        data = reader.read_media(entry)

        if not str(entry.meta.get("mime", "")).startswith(("audio/", "video/")):
            return Response(data, media_type=entry.meta.get("mime"), headers=headers)

        # Players seek with Range requests. Already-compressed media skips gzip
        # (which would also break byte ranges) by declaring its own encoding.
        headers.update({"Accept-Ranges": "bytes", "Content-Encoding": "identity"})
        span = _byte_range(request.headers.get("range"), len(data))

        if span is None:
            return Response(data, media_type=entry.meta.get("mime"), headers=headers)

        if isinstance(span, str):  # "invalid"
            headers["Content-Range"] = f"bytes */{len(data)}"
            return Response(b"", status_code=416, headers=headers)

        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(
            data[start : end + 1],
            status_code=206,
            media_type=entry.meta.get("mime"),
            headers=headers,
        )

    def name_of(folder: Path) -> str | None:
        """Return the project name of a folder under the root, or None outside it."""
        root = catalog.root.resolve()

        try:
            rel = folder.resolve().relative_to(root)
        except ValueError:
            return None

        return rel.as_posix() if rel.parts else root.name

    def artifact_project(name: str) -> Path | None:
        """Return the folder of a project with runs or artifacts, or None if there is none."""
        pdir = project_dir(name)

        if pdir is not None:
            return pdir

        return next((p for p in find_artifact_projects(catalog.root) if name_of(p) == name), None)

    def storage_projects() -> list[tuple[str, Path]]:
        """Return every project folder with runs or artifacts, with its name."""
        dirs = {(catalog.root / r["path"]).parent.parent for r in catalog.runs()}
        dirs |= set(find_artifact_projects(catalog.root))
        return sorted((name_of(d) or d.name, d) for d in dirs)

    meter = Meter(
        catalog.root,
        storage_projects,
        lambda: [(r["key"], r["name"], catalog.root / r["path"]) for r in catalog.runs()],
        cache_dir or default_cache_dir(),
    )

    async def storage(request: Request) -> Response:
        """Return the disk use measured last, and the progress of a measurement under way.

        `POST {"action": "start" | "resume" | "stop"}` starts a measurement,
        continues one that paused, or ends it keeping a partial result. Nothing
        is measured otherwise.
        """

        if request.method == "POST":
            body = await request.json()
            action = body.get("action") if isinstance(body, dict) else None

            if action not in ("start", "resume", "stop"):
                return JSON({"error": "action must be start, resume or stop"}, status_code=400)

            getattr(meter, action)()

        return JSON(meter.status())

    # Manifests never change in place, so each is read once: a version with a
    # million files would otherwise be parsed on every load of the Artifacts page.
    summaries: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
    file_lists: dict[Path, tuple[tuple[int, int], list[dict[str, Any]]]] = {}

    def manifest_stamp(vdir: Path) -> tuple[int, int] | None:
        """Return the manifest's modification time and size, or None if it is missing."""

        try:
            st = (vdir / "manifest.json").stat()
        except OSError:
            return None

        return (st.st_mtime_ns, st.st_size)

    def summary_of(vdir: Path) -> dict[str, Any]:
        """Return a version's manifest without its file list, plus `file_count` and `size`."""
        stamp = manifest_stamp(vdir)
        cached = summaries.get(vdir)

        if cached and cached[0] == stamp:
            return cached[1]

        manifest = _fs.read_json(vdir / "manifest.json", {}) or {}
        files = manifest.pop("files", None) or []
        out = {
            "manifest": manifest,
            "file_count": len(files),
            "size": sum(int(f.get("size") or 0) for f in files),
        }

        if stamp is not None:
            summaries[vdir] = (stamp, out)

        return out

    def artifacts(request: Request) -> Response:
        """Return artifact versions with the runs that produced and used them.

        Artifacts are found in every folder under the root that has an
        `artifacts/` folder, including projects without runs, such as a project
        of shared datasets. A run's `inputs` and `outputs` may point at another
        project (`project_path`, relative to the run's project).

        Query parameter `project` limits the list to the artifacts of one project
        and those its runs produced or used. Unlinked versions are listed too,
        with `unlinked: true`.

        Each manifest comes without its file list, which can be huge; `file_count`
        and `size` sum it up, and `/api/artifacts/files` pages through it.
        """
        root = catalog.root.resolve()
        users: dict[tuple[str, str, int], list[str]] = {}
        makers: dict[tuple[str, str, int], list[str]] = {}
        by_id: dict[tuple[str, str], str] = {}
        project_of: dict[str, str] = {}

        for r in catalog.runs():
            by_id[(r["project"], r["id"])] = r["key"]
            project_of[r["key"]] = r["project"]
            run_path = catalog.path_of(r["key"])

            for field, into in (("inputs", users), ("outputs", makers)):
                for ref in r.get(field) or []:
                    project: str | None = r["project"]

                    if ref.get("project_path") and run_path is not None:
                        project = name_of(run_path.parent.parent / ref["project_path"])

                    if project is not None:
                        k = (project, ref.get("artifact"), ref.get("version"))
                        into.setdefault(k, []).append(r["key"])

        out = []
        want = request.query_params.get("project")

        for pdir in find_artifact_projects(root):
            project = name_of(pdir)

            if project is None:
                continue

            listed = sorted(version_folders(pdir), key=lambda v: (v[3], v[0], v[1]))

            for aname, version, vdir, unlinked in listed:
                k = (project, aname, version)
                producer = makers.get(k) or []
                consumers = users.get(k, [])
                summary = summary_of(vdir)
                pid = summary["manifest"].get("producer_run")

                if not producer and pid and (project, pid) in by_id:
                    producer = [by_id[(project, pid)]]

                linked = {project_of.get(key) for key in [*producer, *consumers]}

                if want and want != project and want not in linked:
                    continue

                out.append(
                    {
                        "project": project,
                        "name": aname,
                        "version": version,
                        **summary,
                        "producers": producer,
                        "consumers": consumers,
                        "unlinked": unlinked,
                    }
                )

        return JSON({"artifacts": out})

    def artifact_files(request: Request) -> Response:
        """Return a page of one version's files, in manifest order.

        Query parameters: `project`, `name`, `version`, `unlinked` (1 for an
        unlinked version), `find` (only paths containing it, ignoring case),
        `offset` and `limit` (default 1,000, at most 5,000). Returns `files`,
        `total` (files in the version) and `matched` (files that match `find`).
        """
        q = request.query_params
        pdir = artifact_project(q.get("project") or "")
        name = q.get("name") or ""

        try:
            version = int(q.get("version") or "")
            offset = max(int(q.get("offset") or 0), 0)
            limit = min(max(int(q.get("limit") or 1000), 1), 5000)
        except ValueError:
            return JSON({"error": "version, offset and limit must be numbers"}, status_code=400)

        if pdir is None or not name or name != _fs.sanitize(name, ""):
            return JSON({"error": "unknown project or artifact"}, status_code=400)

        base = pdir / "artifacts" / (UNLINKED if q.get("unlinked") == "1" else "")
        vdir = base / name / f"v{version}"
        stamp = manifest_stamp(vdir)

        if stamp is None:
            return JSON({"error": f"no v{version} of artifact {name!r}"}, status_code=404)

        cached = file_lists.get(vdir)

        if cached and cached[0] == stamp:
            files = cached[1]
        else:
            files = (_fs.read_json(vdir / "manifest.json", {}) or {}).get("files") or []
            file_lists.clear()  # keep only the version being browsed
            file_lists[vdir] = (stamp, files)

        find = (q.get("find") or "").strip().lower()
        matched = [f for f in files if find in str(f.get("path", "")).lower()] if find else files
        page = matched[offset : offset + limit]
        return JSON({"files": page, "total": len(files), "matched": len(matched)})

    def artifact_source(raw: str) -> tuple[str, Path]:
        """Return what to pass to `add_artifact` for a typed path, and the path it points at.

        `~`, environment variables and absolute paths work as in the CLI; a relative
        path is taken from the served folder.
        """
        expanded = os.path.expanduser(os.path.expandvars(raw))

        if os.path.isabs(expanded):
            return raw, Path(expanded)

        target = (catalog.root / expanded).resolve()
        return str(target), target

    async def edit_body(request: Request) -> dict[str, Any] | Response:
        """Return the JSON body of an artifact change, or the error response that refuses it."""

        if not edit_artifacts:
            hint = f"start the viewer with `{NAME} up --edit-artifacts` to change artifacts"
            return JSON({"error": hint}, status_code=403)

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        return body if isinstance(body, dict) else JSON({"error": "expected an object"}, 400)

    async def artifact_check(request: Request) -> Response:
        """Check a path for a new artifact version (JSON body: `path`).

        Returns `resolved` (the absolute path), `exists`, `kind` (`file` or
        `folder`), `files` and `size` (`partial` when the count stopped at 200,000
        files or 3 seconds), or `error`.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        raw = str(body.get("path") or "").strip()

        if not raw:
            return JSON({"error": "enter a path"})

        unset = re.search(r"\$\{?(\w+)", os.path.expandvars(raw))

        if unset:
            return JSON({"error": f"{unset.group(1)} is not set on this machine"})

        _, target = artifact_source(raw)

        def walk() -> dict[str, Any]:
            """Count the files and bytes under `target`, within the limits."""

            if target.is_file():
                return {"kind": "file", "files": 1, "size": target.stat().st_size, "partial": False}

            files = size = 0
            todo = [target]
            deadline = time.monotonic() + 3

            while todo:
                if files >= 200_000 or time.monotonic() > deadline:
                    return {"kind": "folder", "files": files, "size": size, "partial": True}

                try:
                    with os.scandir(todo.pop()) as it:
                        for e in it:
                            if e.is_dir(follow_symlinks=True):
                                todo.append(Path(e.path))
                            elif e.is_file():
                                files += 1
                                size += e.stat().st_size
                except OSError:
                    continue

            return {"kind": "folder", "files": files, "size": size, "partial": False}

        out: dict[str, Any] = {"resolved": str(target), "exists": target.exists()}

        if target.exists():
            out.update(await run_in_threadpool(walk))

        return JSON(out)

    async def artifact_add(request: Request) -> Response:
        """Add an artifact version that references a path on this machine.

        JSON body: `project`, `name`, `path` (as for `artifact_check`), and
        optionally `type`, `description`, `metadata` (an object) and `checksum`
        (also hash every file). Returns the new version as `{project, name, version}`.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        project = str(body.get("project") or "")
        pdir = artifact_project(project)
        name = _fs.sanitize(str(body.get("name") or ""), "")
        raw = str(body.get("path") or "").strip()
        metadata = body.get("metadata") or {}
        kind = body.get("type") or None

        if pdir is None:
            return JSON({"error": f"unknown project {project!r}"}, status_code=400)

        if not name:
            return JSON({"error": "enter a name"}, status_code=400)

        if not raw:
            return JSON({"error": "enter a path"}, status_code=400)

        if not isinstance(metadata, dict) or (kind is not None and not isinstance(kind, str)):
            return JSON({"error": "metadata must be an object and type a string"}, 400)

        src, target = artifact_source(raw)

        if not target.exists():
            return JSON({"error": f"{target} does not exist"}, status_code=400)

        try:
            art = await run_in_threadpool(
                add_artifact,
                pdir,
                name,
                src,
                type=kind,
                metadata=metadata,
                reference=True,
                checksum=bool(body.get("checksum")),
                description=str(body.get("description") or ""),
            )
        except OSError as exc:
            return JSON({"error": f"the version could not be added: {exc}"}, status_code=409)

        return JSON({"project": project, "name": art.name, "version": art.version})

    async def artifact_unlink(request: Request) -> Response:
        """Unlink one version (`version`) or every version of an artifact, or restore one.

        JSON body: `project`, `name`, `version` (omit to unlink all) and
        `restore` (true to move that version back). Nothing is deleted.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        pdir = artifact_project(str(body.get("project") or ""))
        name = str(body.get("name") or "")
        version = body.get("version")

        if pdir is None or not name or name != _fs.sanitize(name, ""):
            return JSON({"error": "unknown project or artifact"}, status_code=400)

        if version is not None and (not isinstance(version, int) or isinstance(version, bool)):
            return JSON({"error": "version must be a number"}, status_code=400)

        try:
            if body.get("restore"):
                if version is None:
                    return JSON({"error": "name the version to restore"}, status_code=400)

                restore_artifact(pdir, name, version)
                return JSON({"restored": [version]})

            return JSON({"unlinked": unlink_artifact(pdir, name, version)})
        except FileNotFoundError as exc:
            return JSON({"error": str(exc)}, status_code=404)
        except OSError as exc:
            return JSON({"error": f"could not move the version: {exc}"}, status_code=409)

    def alerts(request: Request) -> Response:
        """Return the health alerts of the known runs in `runs` (comma-separated keys)."""
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        return JSON({"alerts": {k: store.alerts(k) for k in keys if catalog.get(k)}})

    def collections(request: Request) -> Response:
        """Return the saved collections, optionally only those of the `project` query parameter."""
        out = []
        want = request.query_params.get("project")

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            if pdir is not None:
                out += [{**c, "project": p["name"]} for c in list_collections(pdir)]

        return JSON({"collections": out})

    async def collection_save(request: Request) -> Response:
        """Create, update or delete a collection in each project its runs belong to.

        The JSON body holds `name` (required), `add` and `remove` (run keys),
        `project` (also save it there when no run is given), `description` and
        `delete` (delete the collection instead). Returns the saved collections.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        name = str(body.get("name") or "").strip()

        if not name:
            return JSON({"error": "a collection needs a name"}, status_code=400)

        # run keys are grouped by project; each project keeps its own collection file
        per_project: dict[str, tuple[list[str], list[str]]] = {}

        for field, slot in (("add", 0), ("remove", 1)):
            for key in body.get(field) or []:
                record = catalog.get(str(key))

                if record is not None:
                    per_project.setdefault(record["project"], ([], []))[slot].append(record["id"])

        if body.get("project"):
            per_project.setdefault(str(body["project"]), ([], []))

        if not per_project:
            return JSON({"error": "no known runs or project"}, status_code=400)

        saved = []

        for project, (add, remove) in per_project.items():
            pdir = project_dir(project)

            if pdir is None:
                continue

            if body.get("delete"):
                delete_collection(pdir, name)
                continue

            saved.append(
                {
                    **save_collection(
                        pdir, name, add=add, remove=remove, description=body.get("description")
                    ),
                    "project": project,
                }
            )

        return JSON({"collections": saved})

    def project_dir(name: str) -> Path | None:
        """Return the folder of a known project, or None if it is unknown or outside the root."""

        if name == catalog.root.name and any(p["name"] == name for p in catalog.projects()):
            return catalog.root

        if not any(p["name"] == name for p in catalog.projects()):
            return None

        return path_inside(catalog.root, name)

    def view_item(request: Request) -> Response:
        """Return a saved view of a project (`GET`) or delete it (`DELETE`).

        Returns the view, or `{"deleted": <name>}`; an unknown view is a 404 error.
        """
        pdir = project_dir(request.path_params["project"])
        target = path_inside(pdir / "views", request.path_params["name"]) if pdir else None

        if target is None or not target.is_file() or target.suffix != ".json":
            return JSON({"error": "no such view"}, status_code=404)

        if request.method == "DELETE":
            target.unlink()
            return JSON({"deleted": target.name})

        return JSON(_fs.read_json(target, {}))

    async def view_save(request: Request) -> Response:
        """Save a view (page and URL parameters) under the project's `views/` folder.

        The JSON body holds `project`, `name` and `state` (`page` and `params`;
        the `cmp` and `tab` parameters are dropped). Returns the saved file name.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        name = _fs.sanitize(str(body.get("name", "view")).removesuffix(".json"), "view") + ".json"
        (pdir / "views").mkdir(exist_ok=True)
        state = body.get("state") or {}
        params = {k: v for k, v in (state.get("params") or {}).items() if k not in ("cmp", "tab")}
        _fs.atomic_write_json(
            pdir / "views" / name, {"page": state.get("page", "charts"), "params": params}
        )
        return JSON({"saved": name})

    def run_key_of(project: str, run_id: str) -> str | None:
        """Return the catalog key of run `run_id` of `project`, or None."""

        for refresh in (False, True):
            if refresh:
                catalog.refresh()

            for r in catalog.runs():
                if r["project"] == project and run_id in (r["id"], Path(r["path"]).name):
                    return r["key"]

        return None

    def find_item(project: str, ref: MediaRef) -> tuple[str, dict[str, Any]] | None:
        """Return the run key and media list entry a reference points to, or None."""
        key = run_key_of(project, ref.run_id)
        reader = store.fresh_reader(key) if key else None

        if key is None or reader is None:
            return None

        found: dict[str, Any] | None = None

        for i, e in enumerate(reader.media()):
            if e.key == ref.key and e.step == ref.step:
                found = {"key": e.key, "step": e.step, "time": e.time, "index": i, **e.meta}
                found = with_notes(found, audio_notes_of(key))

        for t in reader.texts(ref.key):
            if t.step == ref.step:
                found = {"key": t.key, "step": t.step, "time": t.time, "kind": "text"}
                found.update({"mime": "text/plain", "text": t.text})

        return (key, found) if found else None

    def best_steps(request: Request) -> Response:
        """Return, per run, the step where a metric is lowest (or highest).

        Query parameters: `runs` (comma-separated keys), `metric` and `mode`
        (`min`, the default, or `max`). Runs without finite values are left out.
        """
        metric = request.query_params.get("metric", "")
        highest = request.query_params.get("mode") == "max"
        out: dict[str, dict[str, float]] = {}

        for key in filter(None, request.query_params.get("runs", "").split(",")):
            reader = store.reader(key)

            if reader is None:
                continue

            steps, _, values = reader.scalars(metric)
            best: tuple[float, int] | None = None

            for st, v in zip(steps.tolist(), values.tolist()):
                if math.isfinite(v) and (best is None or (v > best[0] if highest else v < best[0])):
                    best = (v, int(st))

            if best is not None:
                out[key] = {"step": best[1], "value": best[0]}

        return JSON({"metric": metric, "mode": "max" if highest else "min", "best": out})

    def media_ref(request: Request) -> Response:
        """Resolve a media reference (`project` and `ref` query parameters) to its item."""
        project = request.query_params.get("project", "")

        try:
            ref = parse_ref(request.query_params.get("ref", ""))
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        found = find_item(project, ref)

        if found is None:
            return JSON({"error": "not found"}, status_code=404)

        key, item = found
        record = catalog.get(key) or {}
        return JSON({"run": key, "run_name": record.get("name", ref.run_id), "item": item})

    def reports(request: Request) -> Response:
        """Return the reports of every project, or of the `project` query parameter."""
        want = request.query_params.get("project")
        out = []

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            if pdir is not None:
                out += [{"project": p["name"], **r} for r in report_names(pdir)]

        return JSON({"reports": out})

    def report_file(request: Request) -> Path | None:
        """Return the file of the report named in the path, or None for an unknown project."""
        pdir = project_dir(request.path_params["project"])
        return report_path(pdir, request.path_params["name"]) if pdir else None

    def report_get(request: Request) -> Response:
        """Return a report's Markdown text."""
        path = report_file(request)

        if path is None or not path.is_file():
            return JSON({"error": "no such report"}, status_code=404)

        text = path.read_text(encoding="utf-8", errors="replace")
        return JSON({"project": request.path_params["project"], "name": path.stem, "text": text})

    def report_export(request: Request) -> Response:
        """Return a zip with the report's Markdown and the files it embeds."""
        path = report_file(request)
        project = request.path_params["project"]

        if path is None or not path.is_file():
            return JSON({"error": "no such report"}, status_code=404)

        def resolve(ref: MediaRef) -> tuple[dict[str, Any], bytes] | None:
            """Return an embedded item and its bytes."""
            found = find_item(project, ref)

            if found is None:
                return None

            key, item = found

            if item.get("kind") == "text":
                return item, b""

            record = catalog.get(key) or {}
            item = {**item, "run_name": record.get("name", ref.run_id), "project": project}
            reader = store.fresh_reader(key)
            assert reader is not None
            return item, reader.read_media(reader.media()[item["index"]])

        def local(name: str) -> bytes | None:
            """Return a report-local file such as a chart snapshot."""
            target = path_inside(path.parent, name)
            return target.read_bytes() if target and target.is_file() else None

        data = export_report(path.read_text(encoding="utf-8"), resolve, path.stem, local)
        disposition = f'attachment; filename="{path.stem}.zip"'
        return Response(
            data, media_type="application/zip", headers={"Content-Disposition": disposition}
        )

    async def report_save(request: Request) -> Response:
        """Save, rename or delete a report.

        The JSON body holds `project`, `name` and `text`; `append` adds a block
        at the end instead (creating the report if needed), `rename` moves the
        report to a new name and `delete: true` removes it.
        """

        if read_only_reports:
            return _read_only()

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        path = report_path(pdir, str(body.get("name", "report")))

        if body.get("delete"):
            path.unlink(missing_ok=True)
            return JSON({"deleted": path.stem})

        if body.get("rename"):
            target = report_path(pdir, str(body["rename"]))

            if target.exists() and target != path:
                return JSON({"error": f"a report named {target.stem} exists"}, status_code=409)

            path = target if not path.exists() else path.rename(target)

        text = body.get("text")

        if body.get("append"):  # add a block at the end, creating the report if needed
            old = path.read_text(encoding="utf-8") if path.exists() else f"# {body.get('name')}\n"
            text = f"{old.rstrip()}\n\n{str(body['append']).strip()}\n"

        if text is None and path.exists():
            return JSON({"saved": path.stem})

        save_report(pdir, path.stem, str(text or ""))
        return JSON({"saved": path.stem})

    def report_asset(request: Request) -> Response:
        """Serve a report-local file, such as a chart snapshot in `reports/files/`."""
        pdir = project_dir(request.path_params["project"])
        target = (
            path_inside(pdir / "reports" / "files", request.path_params["file"]) if pdir else None
        )

        if target is None or not target.is_file():
            return JSON({"error": "not found"}, status_code=404)

        # The type comes from a fixed list, never from sniffing; text and unknown files are
        # downloads, and an SVG opened on its own runs nothing, whatever the file holds
        media_type, download = served_type(target.name)
        return FileResponse(
            target,
            media_type=media_type,
            filename=target.name if download else None,
            content_disposition_type="attachment" if download else "inline",
            headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def report_upload(request: Request) -> Response:
        """Store an image, audio or text file uploaded into a report (see `save_upload`).

        The body is the file's bytes, sent as `application/octet-stream`; query
        parameters `project`, `name` (the file's name) and `kind` (`image`,
        `audio` or `text`). Returns the stored file's `path`, `kind`, `size` and `name`, or
        an `error` that says why it was refused.
        """

        if read_only_reports:
            return _read_only()

        if not request.headers.get("content-type", "").startswith("application/octet-stream"):
            return PlainTextResponse("expected application/octet-stream", 415)

        pdir = project_dir(request.query_params.get("project", ""))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        kind = request.query_params.get("kind", "")
        name = request.query_params.get("name", "file")
        limit = {"text": max_text_bytes, "audio": max_audio_bytes}.get(kind, max_image_bytes)
        too_large = JSON(
            {"error": f"{name} is too large; {kind} files can be at most {limit / 1e6:.0f} MB"},
            status_code=413,
        )
        declared = request.headers.get("content-length", "")

        if declared.isdigit() and int(declared) > limit:
            return too_large

        data = bytearray()

        async for chunk in request.stream():
            data += chunk

            if len(data) > limit:
                return too_large

        try:
            saved = await run_in_threadpool(save_upload, pdir, bytes(data), name, kind, limit)
        except UploadError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON(saved)

    async def report_snapshot(request: Request) -> Response:
        """Store a chart snapshot (JSON body: `project`, `report`, `png` as a data URL)."""

        if read_only_reports:
            return _read_only()

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        raw = str(body.get("png", "")).split(",", 1)[-1]

        try:
            png = base64.b64decode(raw, validate=True)
            path = save_snapshot(pdir, str(body.get("report", "report")), png)
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON({"path": path})

    def fields_get(request: Request) -> Response:
        """Return the property definitions of the `project` query parameter."""
        pdir = project_dir(request.query_params.get("project", ""))
        return JSON({"fields": read_fields(pdir) if pdir else []})

    async def fields_save(request: Request) -> Response:
        """Replace a project's property definitions (JSON body: `project`, `fields`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        try:
            fields = save_fields(pdir, list(body.get("fields") or []))
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON({"fields": fields})

    def pins_get(request: Request) -> Response:
        """Return the pinned files of the `project` query parameter."""
        pdir = project_dir(request.query_params.get("project", ""))
        return JSON({"pins": read_pins(pdir) if pdir else []})

    async def pins_save(request: Request) -> Response:
        """Pin or unpin one file of a project (JSON body: `project`, and `add` or `remove`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        add = body.get("add")
        remove = body.get("remove")

        try:
            pins = change_pins(
                pdir,
                add=str(add) if add is not None else None,
                remove=str(remove) if remove is not None else None,
            )
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSON({"error": f"pins.json could not be saved: {exc}"}, status_code=409)

        return JSON({"pins": pins})

    def sweep_settings_get(request: Request) -> Response:
        """Return the Sweeps settings of the `project` query parameter (`<project>/sweeps.json`).

        `hide` is a filter in the syntax of the settings filter (`!seed !.path`):
        parameters it lets through are offered, the others are hidden.
        """
        pdir = project_dir(request.query_params.get("project", ""))
        data = _fs.read_json(pdir / "sweeps.json", {}) if pdir else {}
        hide = data.get("hide") if isinstance(data, dict) else None
        return JSON({"hide": hide if isinstance(hide, str) else ""})

    async def sweep_settings_save(request: Request) -> Response:
        """Save the Sweeps hide rules of a project (JSON body: `project`, `hide`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        hide = " ".join(str(body.get("hide") or "").split())

        if len(hide) > 1000:
            return JSON({"error": "hide rules are at most 1000 characters"}, status_code=400)

        try:
            data = _fs.read_json(pdir / "sweeps.json", {}) or {}
            data = {**(data if isinstance(data, dict) else {}), "hide": hide}
            _fs.atomic_write_json(pdir / "sweeps.json", data)
        except OSError as exc:
            return JSON({"error": f"sweeps.json could not be saved: {exc}"}, status_code=409)

        return JSON({"hide": hide})

    async def stream(request: Request) -> Response:
        """Return a server-sent event stream: `hello`, then `runs` and `data` change events.

        A keep-alive comment is sent after 15 s without events. The stream ends
        when the server shuts down, so Ctrl+C does not wait for open tabs.
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        hub.queues.add(queue)

        async def events() -> AsyncIterator[str]:
            """Yield the SSE messages for this client until it disconnects."""

            try:
                hello = json.dumps({"version": catalog.version})
                yield f"retry: 3000\nevent: hello\ndata: {hello}\n\n"

                idle = 0.0

                # Checked twice a second, so the server can stop while a tab is open
                while not request.app.state.stopping():
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=0.5)
                        idle = 0.0
                    except asyncio.TimeoutError:
                        idle += 0.5

                        if idle >= 15:
                            idle = 0.0
                            yield ": keep-alive\n\n"
            finally:
                hub.queues.discard(queue)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def index(request: Request) -> Response:
        """Return the frontend's `index.html`, or a 503 page if the frontend is not built."""
        page = STATIC / "index.html"

        if not page.exists():
            return HTMLResponse(
                f"<h1>{NAME}</h1><p>The frontend is not built. Run <code>pnpm install</code> and"
                " <code>pnpm build</code> in <code>frontend/</code>, or install a wheel.</p>",
                503,
            )

        return FileResponse(page, headers={"Cache-Control": "no-cache", **_NO_FRAMING})

    async def static_file(request: Request) -> Response:
        """Return a built frontend file, or `index.html` for any other path (client routing)."""
        target = path_inside(STATIC, request.path_params["path"])

        if target is not None and target.is_file():
            framing = _NO_FRAMING if target.suffix == ".html" else {}
            return FileResponse(target, headers=framing)

        return await index(request)

    async def not_found(request: Request, exc: Exception) -> Response:
        """Return a JSON 404 error for an unknown run."""
        return JSON({"error": f"no run {exc}"}, status_code=404)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Run the change poller while the app is up."""
        hub._task = asyncio.create_task(hub.run())

        try:
            yield
        finally:
            hub._task.cancel()

    routes: list[BaseRoute] = [
        Route("/api/info", info),
        Route("/api/storage", storage, methods=["GET", "POST"]),
        Route("/api/runs", runs),
        Route("/api/runs/annotate", annotate, methods=["POST"]),
        Route("/api/runs/{key}", run_detail),
        Route("/api/runs/{key}", annotate, methods=["PATCH"]),
        Route("/api/runs/{key}/files/{path:path}", run_file),
        Route("/api/runs/{key}/tree", run_tree),
        Route("/api/runs/{key}/text/{path:path}", run_text),
        Route("/api/runs/{key}/raw/{path:path}", run_raw),
        Route("/api/runs/{key}/inspect/{path:path}", run_inspect),
        Route("/api/runs/{key}/media", media_list),
        Route("/api/runs/{key}/audio-notes", set_audio_notes, methods=["PUT"]),
        Route("/api/runs/{key}/media/{index:int}", media_blob),
        Route("/api/metrics", metrics),
        Route("/api/scalars", scalars),
        Route("/api/sweep-keys", sweep_keys),
        Route("/api/sweep-settings", sweep_settings_get),
        Route("/api/sweep-settings", sweep_settings_save, methods=["POST"]),
        Route("/api/artifacts", artifacts),
        Route("/api/artifacts/files", artifact_files),
        Route("/api/artifacts/check", artifact_check, methods=["POST"]),
        Route("/api/artifacts/add", artifact_add, methods=["POST"]),
        Route("/api/artifacts/unlink", artifact_unlink, methods=["POST"]),
        Route("/api/alerts", alerts),
        Route("/api/collections", collections),
        Route("/api/collections", collection_save, methods=["POST"]),
        Route("/api/views", view_save, methods=["POST"]),
        Route("/api/views/{project:path}/{name}", view_item, methods=["GET", "DELETE"]),
        Route("/api/best", best_steps),
        Route("/api/media/ref", media_ref),
        Route("/api/reports", reports),
        Route("/api/reports", report_save, methods=["POST"]),
        Route("/api/reports/snapshot", report_snapshot, methods=["POST"]),
        Route("/api/reports/upload", report_upload, methods=["POST"]),
        Route("/api/reports/{project:path}/files/{file}", report_asset),
        Route("/api/reports/{project:path}/{name}/export", report_export),
        Route("/api/reports/{project:path}/{name}", report_get),
        Route("/api/fields", fields_get),
        Route("/api/fields", fields_save, methods=["POST"]),
        Route("/api/pins", pins_get),
        Route("/api/pins", pins_save, methods=["POST"]),
        Route("/api/stream", stream),
        Route("/", index),
    ]

    if (STATIC / "assets").exists():
        routes.append(Mount("/assets", _SharedAssets(directory=STATIC / "assets")))

    routes.append(Route("/{path:path}", static_file))
    middleware = [Middleware(Guard, token=token), Middleware(GZipMiddleware, minimum_size=2048)]

    if allowed_hosts:
        middleware.insert(0, Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts))

    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
        exception_handlers={_NotFound: not_found},
    )
    app.state.store = store
    app.state.stopping = lambda: False  # `up` replaces it with the server's shutdown flag
    return app


# Pages of the viewer can only be framed by the viewer, so another site cannot overlay them
_NO_FRAMING = {"X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "frame-ancestors 'self'"}


def _byte_range(header: str | None, size: int) -> tuple[int, int] | str | None:
    """Parse a single `bytes=a-b` / `bytes=a-` / `bytes=-n` range.

    Returns:
        `(start, end)` inclusive, None to send everything (no or unsupported
        header), or `"invalid"` when the range cannot be satisfied.
    """

    if not header or not header.startswith("bytes=") or "," in header:
        return None

    first, _, last = header[6:].strip().partition("-")

    try:
        if first:
            start = int(first)
            end = int(last) if last else size - 1
        else:
            start, end = max(0, size - int(last)), size - 1
    except ValueError:
        return None

    if start >= size or start > end:
        return "invalid"

    return start, min(end, size - 1)


class _SharedAssets(StaticFiles):
    """Built JS/CSS, readable from the sandboxed figure frame (opaque origin)."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        """Return the file response with `Access-Control-Allow-Origin: *` added."""
        response = super().file_response(*args, **kwargs)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


class _NotFound(Exception):
    """Raised by route handlers for an unknown run key; answered with a JSON 404."""
