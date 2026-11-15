"""Helpers shared by the viewer's route modules."""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)

from ..reader import MediaEntry, RunReader
from .runfiles import IMAGE_SUFFIXES

ANNOTATION_FIELDS = {
    "starred": bool,
    "archived": bool,
    "reviewed": bool,
    "notes": str,
    "tags": list,
    "fields": dict,
}


TEXT_LIMIT = 2_000_000


def query_int(request: Request, name: str, default: int) -> int:
    """Return an integer query parameter; a value that is not one is a 400 error.

    Raises:
        HTTPException: With status 400 if the parameter is not an integer.
    """
    raw = request.query_params.get(name)

    if raw is None or raw == "":
        return default

    try:
        return int(raw)
    except ValueError:
        raise HTTPException(400, f"{name} must be a number") from None


def media_entry(reader: RunReader | None, uid: int, rank: int) -> MediaEntry | None:
    """Return the media item of `rank` whose `MediaEntry.uid` is `uid`, or None."""

    return None if reader is None else reader.media_item(uid, rank)


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
        options: dict[str, Any] = {"ensure_ascii": False, "separators": (",", ":"), "default": str}

        try:  # most content has no NaN: encode it directly, without a walk over every value
            return json.dumps(content, allow_nan=False, **options).encode("utf-8")
        except (ValueError, TypeError):  # NaN or infinity, or keys JSON cannot take
            return json.dumps(_safe(content), **options).encode("utf-8")


def _read_only(what: str = "reports") -> JSONResponse:
    """The response to a change of `what` (reports or hypotheses) on a server that locks it."""
    return JSON(
        {"error": f"{what} are read-only on this server (--read-only-{what})"},
        status_code=403,
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


_NO_EXPECT = object()  # a save that does not say what it last saw


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


class _NotFound(Exception):
    """Raised by route handlers for an unknown run key; answered with a JSON 404."""


def text_part(target: Path, tail: bool) -> Response:
    """Send the first (or with `tail`, the last) `TEXT_LIMIT` bytes of a file as text.

    Only those bytes are read, so a large file (a checkpoint, a long log) costs
    no more than a small one. `X-Truncated` says whether the file was longer.
    """
    size = target.stat().st_size

    with target.open("rb") as f:
        if tail:
            f.seek(max(0, size - TEXT_LIMIT))

        data = f.read(TEXT_LIMIT)

    return PlainTextResponse(
        data.decode("utf-8", errors="replace"),
        headers={"X-Truncated": "1" if size > TEXT_LIMIT else "0"},
    )


def send_file(target: Path, download: bool) -> Response:
    """Send a file as is: images inline, anything else (or with `download`) as a download.

    Nothing is ever served as HTML or script, so a logged file cannot run in
    the viewer's origin.
    """
    image = IMAGE_SUFFIXES.get(target.suffix.lower())
    download = download or image is None
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


def with_notes(item: dict[str, Any], notes: dict[str, Any]) -> dict[str, Any]:
    """Add the notes of an audio item to its media list entry."""
    found = notes.get(f"{item['key']}@{item['step']}")
    return {**item, "notes": found} if found else item
