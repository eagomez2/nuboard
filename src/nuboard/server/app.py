"""Starlette application behind `nuboard up`."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import time
from collections.abc import AsyncIterator, Callable
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
    Response,
    StreamingResponse,
)
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from .._meta import NAME
from ..artifacts import (
    find_artifact_projects,
    remove_stale_staging,
)
from ..catalog import Catalog
from ..reports import (
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_BYTES,
)
from .auth import Guard
from .common import JSON, _NotFound
from .context import Context
from .data import Store, path_inside
from .routes import artifacts, media, projects, reports, runs, select

STATIC = Path(__file__).resolve().parent.parent / "static"


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
        # Project files watched for changes, announced as a `directions` event: a function that
        # returns their signature (set by `create_app`, which knows the project folders).
        self.directions_sig: Callable[[], object] | None = None
        self._directions_last: object = None

    async def run(self) -> None:
        """Poll for changes forever while clients are connected.

        Every 1.5 s, the catalog is refreshed (only running runs, plus a full
        rescan every 8 s) and live runs' logs are checked for growth. Changed
        runs are announced as a `runs` event and grown logs as a `data` event,
        and a changed `directions.json` in any project (from any viewer, a merge or
        a hand edit) as a `directions` event. Errors while polling are ignored so
        the loop keeps running.
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

            await self._check_directions()

    async def _check_directions(self) -> None:
        """Send a `directions` event when a watched `directions.json` changed since last time."""

        if self.directions_sig is None:
            return

        try:
            sig = await run_in_threadpool(self.directions_sig)
        except Exception:  # pragma: no cover - keep the loop alive
            return

        if self._directions_last is not None and sig != self._directions_last:
            self._send("directions", {"changed": []})

        self._directions_last = sig

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
    local_only: bool = False,
    edit_artifacts: bool = False,
    read_only_reports: bool = False,
    read_only_hypotheses: bool = False,
    lock_directions: bool = False,
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
        local_only: The viewer is for this computer only (loopback, no token):
            refuse requests that came through a proxy or tunnel (see `auth.Guard`).
        edit_artifacts: Allow adding artifact versions (as references to paths
            on this machine, or from a run's files by copy or reference) and
            unlinking and restoring them. Without it those requests are refused.
        read_only_reports: Refuse every change to reports: saving, snapshots
            and uploads, as on a shared server.
        read_only_hypotheses: Refuse every change to hypothesis boards.
        lock_directions: Refuse changes to which way is better (`directions.json`); views can still
            flip a direction for themselves.
        max_image_bytes: Size limit of an image uploaded into a report.
        max_text_bytes: Size limit of a text file uploaded into a report.
        max_audio_bytes: Size limit of an audio file uploaded into a report.

    Returns:
        The app. Its `state.store` holds the `Store` it reads runs through.
    """
    catalog = Catalog(root, cache=cache_dir)
    # names this server process in `hello`: the catalog version restarts from 0 with it
    server_id = secrets.token_hex(8)
    catalog.refresh()
    store = Store(catalog)
    ctx = Context(
        catalog=catalog,
        store=store,
        cache_dir=cache_dir,
        edit_artifacts=edit_artifacts,
        read_only_reports=read_only_reports,
        read_only_hypotheses=read_only_hypotheses,
        lock_directions=lock_directions,
        max_image_bytes=max_image_bytes,
        max_text_bytes=max_text_bytes,
        max_audio_bytes=max_audio_bytes,
    )
    hub = Hub(store)

    def directions_sig() -> tuple[tuple[str, int], ...]:
        """The modification time of every project's `directions.json` (0 when it has none)."""
        out = []

        for p in catalog.projects():
            pdir = ctx.project_dir(p["name"])
            f = pdir / "directions.json" if pdir else None

            try:
                out.append((p["name"], f.stat().st_mtime_ns if f else 0))
            except OSError:
                out.append((p["name"], 0))

        return tuple(out)

    hub.directions_sig = directions_sig

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
                hello = json.dumps({"version": catalog.version, "server": server_id})
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
                headers=_NO_FRAMING,
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

        if edit_artifacts:  # versions abandoned mid-copy by an earlier viewer or script

            def sweep() -> None:
                for pdir in find_artifact_projects(catalog.root):
                    with contextlib.suppress(OSError):
                        for e in os.scandir(pdir / "artifacts"):
                            if e.is_dir() and not e.name.startswith("."):
                                remove_stale_staging(Path(e.path))

            asyncio.get_running_loop().run_in_executor(None, sweep)

        try:
            yield
        finally:
            hub._task.cancel()

    routes: list[BaseRoute] = [
        *runs.routes(ctx),
        *media.routes(ctx),
        *artifacts.routes(ctx),
        *projects.routes(ctx),
        *reports.routes(ctx),
        *select.routes(ctx),
        Route("/api/stream", stream),
        Route("/", index),
    ]

    if (STATIC / "assets").exists():
        routes.append(Mount("/assets", _SharedAssets(directory=STATIC / "assets")))

    routes.append(Route("/{path:path}", static_file))
    middleware = [
        Middleware(Guard, token=token, local_only=local_only),
        Middleware(GZipMiddleware, minimum_size=2048, compresslevel=5),
    ]

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


class _SharedAssets(StaticFiles):
    """Built JS/CSS, readable from the sandboxed figure frame (opaque origin)."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        """Return the file response with `Access-Control-Allow-Origin: *` added."""
        response = super().file_response(*args, **kwargs)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
