"""Markdown reports and typed run properties stored in a project folder.

Reports are plain Markdown files in `<project>/reports/<name>.md`. A logged
image, audio clip, figure, HTML page or text is embedded with an image line whose
target is a media reference:

    ![Reconstructions at the best step](media:20261016-0815_baseline_ab12cd/samples/recon@1200)

that is `media:<run id>/<media key>@<step>`. The viewer renders the item in
place, and `export_report` writes a zip with the Markdown and the files.

A chart saved from the viewer is a PNG snapshot in `reports/files/` whose image
title describes the chart (`![loss](files/x.png "chart:metric=loss&runs=...")`);
the viewer draws it live, other Markdown viewers show the snapshot.

Properties are typed custom fields. Their definitions live in
`<project>/fields.json`; the values stay in each run's `annotations.json`.

Standard library only.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from . import _fs

REF = re.compile(r"!\[(?P<alt>[^\]]*)\]\(media:(?P<ref>[^)\s]+)\)")
# a report-local image such as a chart snapshot: `![caption](files/x.png "chart:...")`
LOCAL = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<path>files/[^)\s"]+)(?:\s+"[^"]*")?\)')
FIELD_TYPES = ("text", "number", "choice", "tags", "bool", "date", "link")
_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "audio/wav": ".wav",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/webm": ".webm",
    "text/html": ".html",
    "application/vnd.plotly.v1+json": ".plotly.json",
    "application/vnd.vegalite+json": ".vl.json",
    "application/vnd.bokeh+json": ".bokeh.json",
}


@dataclass(frozen=True)
class MediaRef:
    """A reference to one logged item of a run.

    Attributes:
        run_id: The run's id (its folder name).
        key: The media or text key.
        step: The step of the item.
    """

    run_id: str
    key: str
    step: int

    def __str__(self) -> str:
        """Return the reference as written after `media:`."""
        return f"{quote(self.run_id, safe='')}/{quote(self.key, safe='/')}@{self.step}"


def parse_ref(text: str) -> MediaRef:
    """Parse the part of a media reference after `media:`.

    Args:
        text: Such as `20261016-0815_baseline_ab12cd/samples/recon@1200`.

    Returns:
        The reference.

    Raises:
        ValueError: If `text` is not `<run id>/<key>@<step>`.
    """
    head, sep, step = unquote(text).rpartition("@")
    run_id, slash, key = head.partition("/")

    if not (sep and slash and run_id and key) or not re.fullmatch(r"-?\d+", step):
        raise ValueError(f"not a media reference: {text!r}")

    return MediaRef(run_id, key, int(step))


def report_names(project_dir: Path) -> list[dict[str, Any]]:
    """List a project's reports.

    Args:
        project_dir: The project's folder.

    Returns:
        One dict per report with `name` (file name without `.md`), `title`
        (its first heading, or the name) and `updated` (modification time),
        newest first.
    """
    folder = project_dir / "reports"

    if not folder.is_dir():
        return []

    out = []

    for path in folder.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        heading = re.search(r"^#\s+(.+)$", text, re.M)
        out.append(
            {
                "name": path.stem,
                "title": heading.group(1).strip() if heading else path.stem,
                "updated": path.stat().st_mtime,
            }
        )

    return sorted(out, key=lambda r: -r["updated"])


def report_path(project_dir: Path, name: str) -> Path:
    """Return the file of report `name`, sanitized to a safe file name."""
    return project_dir / "reports" / (_fs.sanitize(name.removesuffix(".md"), "report") + ".md")


def save_report(project_dir: Path, name: str, text: str) -> Path:
    """Write a report atomically, creating `reports/` if needed.

    Args:
        project_dir: The project's folder.
        name: The report's name; it is sanitized into a file name.
        text: The Markdown.

    Returns:
        The report's file.
    """
    path = report_path(project_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _fs.atomic_write_bytes(path, text.encode("utf-8"))
    return path


Resolver = Callable[[MediaRef], "tuple[dict[str, Any], bytes] | None"]


def export_report(
    text: str,
    resolve: Resolver,
    title: str = "report",
    local: Callable[[str], bytes | None] | None = None,
) -> bytes:
    """Bundle a report and the items it embeds into a zip.

    Images and audio become files in `files/` that the Markdown links to, text
    entries are inlined as code blocks, and interactive figures and HTML are
    saved as files with a link to them. References that no longer resolve are
    replaced by a note.

    Args:
        text: The report's Markdown.
        resolve: Returns `(item, data)` for a reference, where `item` holds at
            least `kind` and `mime` (and `text` for text entries), or None when
            it is missing.
        title: Base name of the Markdown file in the zip.
        local: Returns the bytes of a report-local file such as
            `files/chart.png` (a chart snapshot), or None when it is missing.

    Returns:
        The zip file's bytes.
    """
    buf = io.BytesIO()
    used: dict[str, str] = {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        def replace(match: re.Match[str]) -> str:
            """Return the Markdown that replaces one embedded item."""
            alt = match.group("alt")

            try:
                ref = parse_ref(match.group("ref"))
            except ValueError:
                return match.group(0)

            found = resolve(ref)

            if found is None:
                return f"*(missing: {ref.key} at step {ref.step} of run {ref.run_id})*"

            item, data = found

            if item.get("kind") == "text":
                body = str(item.get("text", ""))
                fence = "~~~~" if "```" in body else "```"
                caption = f"*{alt}*\n\n" if alt else ""
                return f"{caption}{fence}text\n{body}\n{fence}"

            mime = str(item.get("mime", ""))
            stem = _fs.sanitize(f"{ref.run_id}-{ref.key.replace('/', '_')}-{ref.step}", "item")
            name = used.setdefault(str(ref), f"files/{stem}{_EXT.get(mime, '.bin')}")

            if name not in zf.namelist():
                zf.writestr(name, data)

            if mime.startswith("image/"):
                return f"![{alt}]({name})"

            label = alt or f"{ref.key} at step {ref.step}"
            return f"[{label}]({name})"

        def copy_local(match: re.Match[str]) -> str:
            """Copy one report-local image into the zip, dropping the live-chart title."""
            path = match.group("path")
            data = local(path) if local else None

            if data is None:
                return f"*(missing: {path})*"

            if path not in zf.namelist():
                zf.writestr(path, data)

            return f"![{match.group('alt')}]({path})"

        body = REF.sub(replace, LOCAL.sub(copy_local, text))  # local files first
        zf.writestr(f"{_fs.sanitize(title, 'report')}.md", body)

    return buf.getvalue()


def save_snapshot(project_dir: Path, report: str, png: bytes) -> str:
    """Store a chart snapshot next to the reports and return its report-relative path.

    Args:
        project_dir: The project's folder.
        report: The report the snapshot belongs to; used in the file name.
        png: The PNG image.

    Returns:
        The path to write in the report, such as `files/findings-1a2b3c4d.png`.

    Raises:
        ValueError: If `png` is not a PNG image.
    """

    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG image")

    stem = _fs.sanitize(report.removesuffix(".md"), "report")
    name = f"{stem}-{hashlib.sha1(png).hexdigest()[:8]}.png"
    folder = project_dir / "reports" / "files"
    folder.mkdir(parents=True, exist_ok=True)
    _fs.atomic_write_bytes(folder / name, png)
    return f"files/{name}"


def read_fields(project_dir: Path) -> list[dict[str, Any]]:
    """Return a project's property definitions from `fields.json`.

    Args:
        project_dir: The project's folder.

    Returns:
        A list of definitions, each with `name` and `type`, and optionally
        `options` (choice and tags), `unit` (number) and `description`.
    """
    data = _fs.read_json(project_dir / "fields.json", {}) or {}
    fields = data.get("fields") if isinstance(data, dict) else None
    return [f for f in fields or [] if isinstance(f, dict) and f.get("name")]


def clean_fields(fields: list[Any]) -> list[dict[str, Any]]:
    """Validate property definitions.

    Args:
        fields: Definitions as sent by the viewer.

    Returns:
        The definitions with unknown keys dropped, types checked and names
        de-duplicated (the first one wins).

    Raises:
        ValueError: If a definition has no name or an unknown type.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for f in fields:
        if not isinstance(f, dict):
            raise ValueError("each property must be an object")

        name = str(f.get("name", "")).strip()
        kind = str(f.get("type", "text"))

        if not name:
            raise ValueError("a property needs a name")

        if kind not in FIELD_TYPES:
            raise ValueError(f"unknown property type {kind!r}; use one of {', '.join(FIELD_TYPES)}")

        if name in seen:
            continue

        seen.add(name)
        item: dict[str, Any] = {"name": name, "type": kind}

        if kind in ("choice", "tags"):
            item["options"] = [str(o) for o in f.get("options") or [] if str(o).strip()]

        if kind == "number" and f.get("unit"):
            item["unit"] = str(f["unit"])

        if f.get("description"):
            item["description"] = str(f["description"])

        out.append(item)

    return out


def save_fields(project_dir: Path, fields: list[Any]) -> list[dict[str, Any]]:
    """Validate and write a project's property definitions to `fields.json`.

    Args:
        project_dir: The project's folder.
        fields: The definitions, in display order.

    Returns:
        The definitions as written.

    Raises:
        ValueError: If a definition is invalid (see `clean_fields`).
    """
    cleaned = clean_fields(fields)
    _fs.atomic_write_json(project_dir / "fields.json", {"fields": cleaned})
    return cleaned
