"""Starlette application behind `NAME up`."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import os
import re
import time
from collections.abc import AsyncIterator
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
from ..artifacts import list_artifacts
from ..catalog import Catalog
from ..collection import delete_collection, list_collections, save_collection
from ..query import QueryError, parse
from ..reports import (
    MediaRef,
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
)
from .data import Store, path_inside

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


def _flat_config(config: dict[str, Any], limit: int = 64) -> dict[str, Any]:
    """Flatten a nested config to at most `limit` dotted keys, shortening long values.

    Strings over 80 characters are cut with `...`; lists become JSON text cut to
    80 characters.
    """
    out: dict[str, Any] = {}

    def walk(obj: Any, prefix: str) -> None:
        """Add the leaves of `obj` to `out` under keys starting with `prefix`."""

        if len(out) >= limit:
            return

        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}{k}.")
        else:
            value = obj

            if isinstance(value, str) and len(value) > 80:
                value = value[:77] + "..."
            elif isinstance(value, list):
                value = json.dumps(value, default=str)[:80]

            out[prefix[:-1]] = value

    walk(config, "")
    return out


def _brief(record: dict[str, Any], metrics: set[str] | None) -> dict[str, Any]:
    """Return the run-list projection of a catalog record (keeps the payload small).

    The config is flattened, the summary is limited to `metrics` (all metrics
    when None), and `metric_count` and `nonfinite` (metrics with non-finite
    values) are added.
    """
    out = {
        k: v
        for k, v in record.items()
        if k not in ("config", "summary", "inputs", "outputs", "error", "compacted")
    }
    out["config"] = _flat_config(record.get("config") or {})
    summary = record.get("summary") or {}
    out["summary"] = (
        summary if metrics is None else {m: summary[m] for m in metrics if m in summary}
    )
    out["metric_count"] = len(summary)
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
) -> Starlette:
    """Create the viewer's Starlette app for a folder of runs.

    The app serves the JSON API under `/api`, a server-sent event stream of
    changes at `/api/stream`, and the built frontend for every other path.
    Responses of 2 KB or more are gzipped.

    Args:
        root: Folder holding the runs.
        cache_dir: Folder for the catalog cache, or None for the catalog's default.
        allowed_hosts: Accepted `Host` header values, or None to accept any host.

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
        """Return one run's record, metadata, files, ranks, media keys and annotations."""
        key = request.path_params["key"]
        record = record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        meta = _fs.read_json(path / "run.json", {})
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

    def artifacts(request: Request) -> Response:
        """Return artifact versions with the runs that produced and used them.

        Query parameter `project` limits the list to one project.
        """
        rows = catalog.runs()
        users: dict[tuple[str, str, int], list[str]] = {}
        makers: dict[tuple[str, str, int], list[str]] = {}
        by_id: dict[tuple[str, str], str] = {}

        for r in rows:
            by_id[(r["project"], r["id"])] = r["key"]

            for ref in r.get("inputs") or []:
                k = (r["project"], ref.get("artifact"), ref.get("version"))
                users.setdefault(k, []).append(r["key"])

            for ref in r.get("outputs") or []:
                k = (r["project"], ref.get("artifact"), ref.get("version"))
                makers.setdefault(k, []).append(r["key"])

        out = []
        want = request.query_params.get("project")

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            if pdir is None:
                continue

            for a in list_artifacts(pdir):
                k = (p["name"], a.name, a.version)
                producer = makers.get(k) or []
                pid = a.manifest.get("producer_run")

                if not producer and pid and (p["name"], pid) in by_id:
                    producer = [by_id[(p["name"], pid)]]

                out.append(
                    {
                        "project": p["name"],
                        "name": a.name,
                        "version": a.version,
                        "manifest": a.manifest,
                        "producers": producer,
                        "consumers": users.get(k, []),
                        "size": sum(int(f.get("size") or 0) for f in a.manifest.get("files") or []),
                    }
                )

        return JSON({"artifacts": out})

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

    def view_get(request: Request) -> Response:
        """Return a saved view of a project, or a 404 error."""
        pdir = project_dir(request.path_params["project"])
        target = path_inside(pdir / "views", request.path_params["name"]) if pdir else None

        if target is None or not target.is_file():
            return JSON({"error": "no such view"}, status_code=404)

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

        return FileResponse(target)

    async def report_snapshot(request: Request) -> Response:
        """Store a chart snapshot (JSON body: `project`, `report`, `png` as a data URL)."""

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

    async def stream(request: Request) -> Response:
        """Return a server-sent event stream: `hello`, then `runs` and `data` change events.

        A keep-alive comment is sent after 15 s without events.
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        hub.queues.add(queue)

        async def events() -> AsyncIterator[str]:
            """Yield the SSE messages for this client until it disconnects."""

            try:
                hello = json.dumps({"version": catalog.version})
                yield f"retry: 3000\nevent: hello\ndata: {hello}\n\n"

                while True:
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
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

        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    async def static_file(request: Request) -> Response:
        """Return a built frontend file, or `index.html` for any other path (client routing)."""
        target = path_inside(STATIC, request.path_params["path"])

        if target is not None and target.is_file():
            return FileResponse(target)

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
        Route("/api/runs", runs),
        Route("/api/runs/annotate", annotate, methods=["POST"]),
        Route("/api/runs/{key}", run_detail),
        Route("/api/runs/{key}", annotate, methods=["PATCH"]),
        Route("/api/runs/{key}/files/{path:path}", run_file),
        Route("/api/runs/{key}/media", media_list),
        Route("/api/runs/{key}/audio-notes", set_audio_notes, methods=["PUT"]),
        Route("/api/runs/{key}/media/{index:int}", media_blob),
        Route("/api/metrics", metrics),
        Route("/api/scalars", scalars),
        Route("/api/artifacts", artifacts),
        Route("/api/alerts", alerts),
        Route("/api/collections", collections),
        Route("/api/collections", collection_save, methods=["POST"]),
        Route("/api/views", view_save, methods=["POST"]),
        Route("/api/views/{project:path}/{name}", view_get),
        Route("/api/best", best_steps),
        Route("/api/media/ref", media_ref),
        Route("/api/reports", reports),
        Route("/api/reports", report_save, methods=["POST"]),
        Route("/api/reports/snapshot", report_snapshot, methods=["POST"]),
        Route("/api/reports/{project:path}/files/{file}", report_asset),
        Route("/api/reports/{project:path}/{name}/export", report_export),
        Route("/api/reports/{project:path}/{name}", report_get),
        Route("/api/fields", fields_get),
        Route("/api/fields", fields_save, methods=["POST"]),
        Route("/api/stream", stream),
        Route("/", index),
    ]

    if (STATIC / "assets").exists():
        routes.append(Mount("/assets", _SharedAssets(directory=STATIC / "assets")))

    routes.append(Route("/{path:path}", static_file))
    middleware = [Middleware(GZipMiddleware, minimum_size=2048)]

    if allowed_hosts:
        middleware.insert(0, Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts))

    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
        exception_handlers={_NotFound: not_found},
    )
    app.state.store = store
    return app


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
