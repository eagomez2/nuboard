"""Routes for media and text items, their audio notes, and media references."""

from __future__ import annotations

import math
import re
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
)
from starlette.routing import BaseRoute, Route

from ..._annotations import AnnotationsError, update_annotations
from ...reports import (
    clean_audio_notes,
    parse_ref,
)
from ..common import (
    JSON,
    _byte_range,
    media_entry,
    query_int,
    with_notes,
)
from ..context import Context


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the media routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    store = ctx.store
    record_or_404 = ctx.record_or_404
    find_item = ctx.find_item
    audio_notes_of = ctx.audio_notes_of

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

        def change(ann: dict[str, Any]) -> None:
            """Store the notes in the run's annotations."""
            per = dict(ann.get("audio_notes") or {})

            if notes:
                per[item] = notes
            else:
                per.pop(item, None)

            if per:
                ann["audio_notes"] = per
            else:
                ann.pop("audio_notes", None)

        try:
            await run_in_threadpool(update_annotations, path, change)
        except AnnotationsError as exc:
            return PlainTextResponse(str(exc), 409)

        return JSON({"notes": notes})

    def media_list(request: Request) -> Response:
        """Return a run's media and text entries.

        Query parameters: `rank` (default 0) and `key` (only entries with that
        media key). Media entries carry their `index` for `media_blob`: a number
        that keeps naming the same item after a resume (`MediaEntry.uid`). Where a
        later session logged a key again, the earlier session's items from that
        step on are left out, as for scalars.
        """
        key = request.path_params["key"]
        record_or_404(key)
        reader = store.fresh_reader(key)
        rank = query_int(request, "rank", 0)
        want = request.query_params.get("key")
        items: list[dict[str, Any]] = []
        notes = audio_notes_of(key) if rank == 0 else {}

        if reader is not None:
            for e in reader.media(rank=rank, latest=True):
                if want is None or e.key == want:
                    item = {"key": e.key, "step": e.step, "time": e.time, "index": e.uid, **e.meta}
                    items.append(with_notes(item, notes))

            for t in reader.texts(rank=rank, latest=True):
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
        """Return the bytes of the media entry `index` (its `uid`) of the `rank` query parameter.

        Responses are cached as immutable: an `index` names one item for good.
        HTML is sent with a sandbox CSP. Audio and video support single
        byte-range requests.
        """
        key = request.path_params["key"]
        record_or_404(key)
        reader = store.fresh_reader(key)
        rank = query_int(request, "rank", 0)
        entry = media_entry(reader, int(request.path_params["index"]), rank)

        if entry is None or reader is None:
            return PlainTextResponse("not found", 404)

        headers = {"Cache-Control": "max-age=31536000, immutable"}

        if entry.meta.get("mime") == "text/html":  # rendered only inside a sandboxed iframe
            headers["Content-Security-Policy"] = "sandbox allow-scripts"

        mime = str(entry.meta.get("mime", ""))

        # Already-compressed media skips gzip by declaring its own encoding
        # (gzip would also break byte ranges); SVG is text and still gains.
        if mime.startswith(("image/", "audio/", "video/")) and mime != "image/svg+xml":
            headers["Content-Encoding"] = "identity"

        if not mime.startswith(("audio/", "video/")):
            return Response(reader.read_media(entry), media_type=mime or None, headers=headers)

        # Players seek with Range requests: only the asked-for bytes are read
        headers["Accept-Ranges"] = "bytes"
        total = entry.length
        span = _byte_range(request.headers.get("range"), total)

        if span is None:
            return Response(reader.read_media(entry), media_type=mime, headers=headers)

        if isinstance(span, str):  # "invalid"
            headers["Content-Range"] = f"bytes */{total}"
            return Response(b"", status_code=416, headers=headers)

        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        return Response(
            reader.read_media(entry, start, end - start + 1),
            status_code=206,
            media_type=mime,
            headers=headers,
        )

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

            steps, _, values = reader.scalars(metric, copy=False)
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

    return [
        Route("/api/runs/{key}/media", media_list),
        Route("/api/runs/{key}/audio-notes", set_audio_notes, methods=["PUT"]),
        Route("/api/runs/{key}/media/{index:int}", media_blob),
        Route("/api/best", best_steps),
        Route("/api/media/ref", media_ref),
    ]
