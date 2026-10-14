"""Starlette application behind ``NAME up``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
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
    def render(self, content: Any) -> bytes:
        return json.dumps(
            _safe(content), ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")


def _flat_config(config: dict[str, Any], limit: int = 64) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def walk(obj: Any, prefix: str) -> None:
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
    """The run-list projection of a catalog record (keeps the payload small)."""
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
    """Polls the folder once for all clients and fans changes out over SSE."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.queues: set[asyncio.Queue[str]] = set()
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
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
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        for q in list(self.queues):
            q.put_nowait(msg)


def create_app(
    root: str | os.PathLike[str],
    *,
    cache_dir: Path | None = None,
    allowed_hosts: list[str] | None = None,
) -> Starlette:
    catalog = Catalog(root, cache=cache_dir)
    catalog.refresh()
    store = Store(catalog)
    hub = Hub(store)

    def record_or_404(key: str) -> dict[str, Any]:
        record = catalog.get(key)
        if record is None:
            catalog.refresh()
            record = catalog.get(key)
        if record is None:
            raise _NotFound(key)
        return record

    # -- routes ---------------------------------------------------------------
    async def info(request: Request) -> Response:
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
        key = request.path_params["key"]
        record_or_404(key)
        path = catalog.path_of(key)
        assert path is not None
        target = path_inside(path / "files", request.path_params["path"])
        if target is None or not target.is_file():
            return PlainTextResponse("not found", 404)
        data = target.read_bytes()[:TEXT_LIMIT]
        return PlainTextResponse(data.decode("utf-8", errors="replace"))

    async def annotate(request: Request) -> Response:
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
                if v is None or isinstance(v, (str, int, float, bool))
            }

        def write() -> list[str]:
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
                        if v is None or v == "":
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
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        counts: dict[str, int] = {}
        for key in keys:
            record = catalog.get(key)
            if record is None:
                continue
            names = list(record.get("summary") or {})
            if not names:  # live run before its first heartbeat: read the log
                reader = store.fresh_reader(key)
                names = reader.metric_names() if reader else []
            for m in names:
                counts[m] = counts.get(m, 0) + 1
        return JSON({"metrics": [{"name": m, "runs": n} for m, n in sorted(counts.items())]})

    def scalars(request: Request) -> Response:
        qp = request.query_params
        keys = [k for k in qp.get("runs", "").split(",") if k]
        metric = qp.get("metric")
        if not metric:
            return PlainTextResponse("metric is required", 400)

        def opt(name: str) -> float | None:
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

    def media_list(request: Request) -> Response:
        key = request.path_params["key"]
        record_or_404(key)
        reader = store.fresh_reader(key)
        rank = int(request.query_params.get("rank", 0))
        want = request.query_params.get("key")
        items: list[dict[str, Any]] = []
        if reader is not None:
            for i, e in enumerate(reader.media(rank=rank)):
                if want is None or e.key == want:
                    items.append(
                        {"key": e.key, "step": e.step, "time": e.time, "index": i, **e.meta}
                    )
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
        return Response(
            reader.read_media(entry), media_type=entry.meta.get("mime"), headers=headers
        )

    def artifacts(request: Request) -> Response:
        """Artifact versions with the runs that produced and used them."""
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
        keys = [k for k in request.query_params.get("runs", "").split(",") if k]
        return JSON({"alerts": {k: store.alerts(k) for k in keys if catalog.get(k)}})

    def collections(request: Request) -> Response:
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
        if name == catalog.root.name and any(p["name"] == name for p in catalog.projects()):
            return catalog.root
        if not any(p["name"] == name for p in catalog.projects()):
            return None
        return path_inside(catalog.root, name)

    def view_get(request: Request) -> Response:
        pdir = project_dir(request.path_params["project"])
        target = path_inside(pdir / "views", request.path_params["name"]) if pdir else None
        if target is None or not target.is_file():
            return JSON({"error": "no such view"}, status_code=404)
        return JSON(_fs.read_json(target, {}))

    async def view_save(request: Request) -> Response:
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

    async def stream(request: Request) -> Response:
        queue: asyncio.Queue[str] = asyncio.Queue()
        hub.queues.add(queue)

        async def events() -> AsyncIterator[str]:
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
        page = STATIC / "index.html"
        if not page.exists():
            return HTMLResponse(
                f"<h1>{NAME}</h1><p>The frontend is not built. Run <code>pnpm install</code> and"
                " <code>pnpm build</code> in <code>frontend/</code>, or install a wheel.</p>",
                503,
            )
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    async def static_file(request: Request) -> Response:
        target = path_inside(STATIC, request.path_params["path"])
        if target is not None and target.is_file():
            return FileResponse(target)
        return await index(request)

    async def not_found(request: Request, exc: Exception) -> Response:
        return JSON({"error": f"no run {exc}"}, status_code=404)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
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
        Route("/api/runs/{key}/media/{index:int}", media_blob),
        Route("/api/metrics", metrics),
        Route("/api/scalars", scalars),
        Route("/api/artifacts", artifacts),
        Route("/api/alerts", alerts),
        Route("/api/collections", collections),
        Route("/api/collections", collection_save, methods=["POST"]),
        Route("/api/views", view_save, methods=["POST"]),
        Route("/api/views/{project:path}/{name}", view_get),
        Route("/api/stream", stream),
        Route("/", index),
    ]
    if (STATIC / "assets").exists():
        routes.append(Mount("/assets", StaticFiles(directory=STATIC / "assets")))
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


class _NotFound(Exception):
    pass
