"""Routes for reports: listing, saving, uploads, snapshots and exports."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    PlainTextResponse,
    Response,
)
from starlette.routing import BaseRoute, Route

from ...reports import (
    MediaRef,
    UploadError,
    export_report,
    report_names,
    report_path,
    save_report,
    save_snapshot,
    save_upload,
    served_type,
)
from ..common import (
    JSON,
    _read_only,
    media_entry,
)
from ..context import Context
from ..data import path_inside


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the reports routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    store = ctx.store
    read_only_reports = ctx.read_only_reports
    max_image_bytes = ctx.max_image_bytes
    max_text_bytes = ctx.max_text_bytes
    max_audio_bytes = ctx.max_audio_bytes
    project_dir = ctx.project_dir
    find_item = ctx.find_item

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
            entry = media_entry(reader, item["index"], 0)

            if reader is None or entry is None:
                return None

            return item, reader.read_media(entry)

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

    return [
        Route("/api/reports", reports),
        Route("/api/reports", report_save, methods=["POST"]),
        Route("/api/reports/snapshot", report_snapshot, methods=["POST"]),
        Route("/api/reports/upload", report_upload, methods=["POST"]),
        Route("/api/reports/{project:path}/files/{file}", report_asset),
        Route("/api/reports/{project:path}/{name}/export", report_export),
        Route("/api/reports/{project:path}/{name}", report_get),
    ]
