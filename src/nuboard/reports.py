"""Markdown reports and typed run properties stored in a project folder.

Reports are plain Markdown files in `<project>/reports/<name>.md`. A logged
image, audio clip, figure, HTML page or text is embedded with an image line whose
target is a media reference:

    ![Reconstructions at the best step](media:20261016T0815-bc799713/samples/recon@1200)

that is `media:<run id>/<media key>@<step>`. The viewer renders the item in
place, and `export_report` writes a zip with the Markdown and the files.

A chart saved from the viewer is a PNG snapshot in `reports/files/` whose image
title describes the chart (`![loss](files/x.png "chart:metric=loss&runs=...")`);
the viewer draws it live, other Markdown viewers show the snapshot.

Images and text files uploaded in the editor are stored in `reports/files/` too,
named by a hash of their content (see `save_upload`). An image is a plain image
line; an attached text file is a link titled `attachment`
(`[train.log](files/3f2a....log "attachment")`), which the viewer shows as a
collapsible block.

Properties are typed custom fields. Their definitions live in
`<project>/fields.json`; the values stay in each run's `annotations.json`.

Standard library only.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from . import _fs
from ._waveform import waveform_bundle

REF = re.compile(r"!\[(?P<alt>[^\]]*)\]\(media:(?P<ref>[^)\s]+)\)")
# a report-local image such as a chart snapshot: `![caption](files/x.png "chart:...")`
LOCAL = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<path>files/[^)\s"]+)(?:\s+"[^"]*")?\)')
# a link to a report-local file, such as an attachment: `[a.log](files/x.log "attachment")`
LOCAL_LINK = re.compile(r'(?<!!)\[(?P<label>[^\]]*)\]\((?P<path>files/[^)\s"]+)(?:\s+"[^"]*")?\)')
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
    # a waveform figure: a zip of its audio, signals and metadata (see `_waveform.py`)
    "application/x-nuboard-waveform": ".zip",
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
        text: Such as `20261016T0815-bc799713/samples/recon@1200`.

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
    saved as files with a link to them. A waveform figure becomes its bundle
    (a `.zip` with `audio.wav`, one `.npy` per signal and `metadata.json`).
    References that no longer resolve are replaced by a note.

    Args:
        text: The report's Markdown.
        resolve: Returns `(item, data)` for a reference, where `item` holds at
            least `kind` and `mime` (and `text` for text entries; `run_name`
            and `project` name the run in a waveform bundle), or None when it
            is missing.
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

            label = alt or f"{ref.key} at step {ref.step}"

            if name not in zf.namelist():
                if mime == "application/x-nuboard-waveform":
                    run = {
                        "id": ref.run_id,
                        "name": item.get("run_name", ref.run_id),
                        "project": item.get("project"),
                    }
                    data = waveform_bundle(item, data, run=run, key=ref.key, step=ref.step)

                zf.writestr(name, data)

            if mime.startswith("image/"):
                return f"![{alt}]({name})"

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

        def copy_linked(match: re.Match[str]) -> str:
            """Copy one linked report-local file (an attachment) into the zip."""
            path = match.group("path")
            data = local(path) if local else None

            if data is None:
                return f"*(missing: {path})*"

            if path not in zf.namelist():
                zf.writestr(path, data)

            return f"[{match.group('label')}]({path})"

        # local files first
        body = REF.sub(replace, LOCAL_LINK.sub(copy_linked, LOCAL.sub(copy_local, text)))
        zf.writestr(f"{_fs.sanitize(title, 'report')}.md", body)

    return buf.getvalue()


def save_snapshot(project_dir: Path, report: str, png: bytes) -> str:
    """Store a chart snapshot next to the reports and return its report-relative path.

    Args:
        project_dir: The project's folder.
        report: The report the snapshot belongs to; used in the file name.
        png: The image: a PNG, or an SVG drawing without scripts, event handlers, links or
            embedded HTML (the Timeline is saved as SVG so its hover titles survive).

    Returns:
        The path to write in the report, such as `files/findings-1a2b3c4d.png`.

    Raises:
        ValueError: If `png` is neither a PNG image nor such an SVG drawing.
    """

    if png.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif _safe_svg(png):
        ext = "svg"
    else:
        raise ValueError("not a PNG image or a plain SVG drawing")

    stem = _fs.sanitize(report.removesuffix(".md"), "report")
    name = f"{stem}-{hashlib.sha1(png).hexdigest()[:8]}.{ext}"
    folder = project_dir / "reports" / "files"
    folder.mkdir(parents=True, exist_ok=True)
    _fs.atomic_write_bytes(folder / name, png)
    return f"files/{name}"


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
# Report files are served with a type chosen from their extension here, never guessed
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
AUDIO_TYPES = {
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}
TEXT_EXTENSIONS = frozenset(
    ".txt .md .markdown .log .csv .tsv .json .jsonl .yaml .yml .toml .ini .cfg .conf .xml "
    ".py .ipynb .sh .bash .zsh .ps1 .bat .js .mjs .ts .tsx .jsx .c .h .cc .cpp .hpp .cu .cuh "
    ".rs .go .java .kt .scala .swift .rb .php .pl .lua .r .jl .m .sql .tex .bib .rst "
    ".diff .patch .proto .gradle .cmake .mk .dockerfile .env".split()
)


class UploadError(ValueError):
    """An upload that was refused: too large, of the wrong type, or not UTF-8 text."""


def image_type(data: bytes) -> str | None:
    """Return the extension of a PNG, JPEG, GIF or WebP image from its first bytes, or None."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"

    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"

    return None


def audio_type(data: bytes) -> str | None:
    """Return the extension of a WAV, FLAC, MP3, Ogg, M4A or WebM file from its first bytes.

    None when the bytes are none of these.
    """

    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"

    if data.startswith(b"fLaC"):
        return ".flac"

    # an ID3 tag, or an MPEG audio frame: 11 sync bits, then a layer that is not 0 (that is AAC)
    if data.startswith(b"ID3") or (
        len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0 and data[1] & 0x06
    ):
        return ".mp3"

    if data.startswith(b"OggS"):
        return ".ogg"

    if data[4:8] == b"ftyp":
        return ".m4a"

    if data.startswith(b"\x1a\x45\xdf\xa3"):  # EBML, the container of WebM
        return ".webm"

    return None


def save_upload(
    project_dir: Path,
    data: bytes,
    filename: str,
    kind: str,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Check an image, audio or text file uploaded into a report and store it in `reports/files/`.

    The type is decided from the bytes, never from the file name or the
    browser: an image must be a PNG, JPEG, GIF or WebP (or an SVG drawing that
    passes the same check as chart snapshots), audio a WAV, FLAC, MP3, Ogg,
    M4A or WebM file, and a text file must decode as UTF-8 with no NUL bytes.
    Nothing is decoded or converted: the file is stored as uploaded, named by
    the first 16 hex digits of its SHA-256, so identical uploads are stored
    once.

    Args:
        project_dir: The project's folder.
        data: The file's bytes.
        filename: The name it was uploaded with; only its extension is used, for
            a text file (`.txt` when it is not a known text extension).
        kind: `image`, `audio` or `text`.
        max_bytes: The size limit, or None for `MAX_IMAGE_BYTES`,
            `MAX_AUDIO_BYTES` or `MAX_TEXT_BYTES`.

    Returns:
        `path` (to write in the report, such as `files/3f2a9c0d1e2b4a5f.png`),
        `kind`, `size` and `name` (the uploaded file name, without folders).

    Raises:
        UploadError: If the file is empty, too large or not of an accepted type.
    """
    name = re.split(r"[\\/]", filename)[-1] or "file"

    limits = {"image": MAX_IMAGE_BYTES, "audio": MAX_AUDIO_BYTES, "text": MAX_TEXT_BYTES}

    if kind not in limits:
        raise UploadError(f"unknown upload kind {kind!r}; expected image, audio or text")

    limit = max_bytes if max_bytes is not None else limits[kind]

    if not data:
        raise UploadError(f"{name} is empty")

    if len(data) > limit:
        raise UploadError(
            f"{name} is {len(data) / 1e6:.1f} MB; {kind} files can be at most {limit / 1e6:.0f} MB"
        )

    if kind == "image":
        ext = image_type(data) or (".svg" if _safe_svg(data) else None)

        if ext is None:
            raise UploadError(
                f"{name} is not a PNG, JPEG, GIF or WebP image (or a plain SVG drawing)"
            )
    elif kind == "audio":
        ext = audio_type(data)

        if ext is None:
            raise UploadError(f"{name} is not a WAV, FLAC, MP3, Ogg, M4A or WebM audio file")
    else:
        if b"\x00" in data:
            raise UploadError(f"{name} is not a text file: it has NUL bytes")

        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadError(f"{name} is not UTF-8 text") from None

        suffix = Path(name).suffix.lower()
        ext = suffix if suffix in TEXT_EXTENSIONS else ".txt"

    stored = f"{hashlib.sha256(data).hexdigest()[:16]}{ext}"
    folder = project_dir / "reports" / "files"
    folder.mkdir(parents=True, exist_ok=True)

    if not (folder / stored).exists():
        _fs.atomic_write_bytes(folder / stored, data)

    return {"path": f"files/{stored}", "kind": kind, "size": len(data), "name": name}


def served_type(name: str) -> tuple[str, bool]:
    """Return the `Content-Type` a report file is served with, and whether it is a download.

    Images and audio are shown inline with their type, text files are sent as UTF-8
    `text/plain` attachments, and anything else as an `application/octet-stream`
    attachment, so a file renamed to `.html` never renders.
    """
    ext = Path(name).suffix.lower()

    if ext in IMAGE_TYPES:
        return IMAGE_TYPES[ext], False

    if ext in AUDIO_TYPES:
        return AUDIO_TYPES[ext], False

    if ext in TEXT_EXTENSIONS:
        return "text/plain; charset=utf-8", True

    return "application/octet-stream", True


_UNSAFE_SVG = re.compile(
    rb"<script|<foreignobject|<iframe|<object|<embed|javascript:|href\s*=|\son\w+\s*=", re.I
)


def _safe_svg(data: bytes) -> bool:
    """Return whether `data` is an SVG drawing with nothing that could run or load anything."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False

    return text.lstrip().startswith("<svg") and not _UNSAFE_SVG.search(data)


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


def check_field(field: dict[str, Any], value: Any) -> None:
    """Check that a value fits a property definition.

    Args:
        field: The definition, as returned by `read_fields`.
        value: The value to store (null or empty values clear a field and are
            not checked).

    Raises:
        ValueError: If the value does not fit the property's type or options.
    """

    if value is None or value == "" or value == []:
        return

    name = field["name"]
    kind = field.get("type", "text")
    options = field.get("options") or []

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} is a number property; {value!r} is not a number")

    elif kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{name} is a yes/no property; use true or false")

    elif kind == "choice":
        if not isinstance(value, str) or (options and value not in options):
            raise ValueError(f"{name} must be one of: {', '.join(options)}")

    elif kind == "tags":
        if not isinstance(value, list) or (options and any(v not in options for v in value)):
            raise ValueError(f"{name} takes tags from: {', '.join(options)}")

    elif kind == "date":
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{name} is a date property; use YYYY-MM-DD")

    elif kind == "link":
        if not isinstance(value, str) or not re.match(r"https?://\S+$", value):
            raise ValueError(f"{name} is a link property; use an http:// or https:// address")


def clean_audio_notes(notes: Any) -> list[dict[str, Any]]:
    """Validate the notes of one audio item.

    Args:
        notes: A list of `{id, start, end, text}` objects, times in seconds.

    Returns:
        The notes sorted by start time, with text trimmed to 2,000 characters.

    Raises:
        ValueError: If a note is not an object with numeric times and text.
    """

    if not isinstance(notes, list):
        raise ValueError("notes must be a list")

    out = []

    for n in notes:
        if not isinstance(n, dict):
            raise ValueError("each note is an object with start, end and text")

        start, end, text = n.get("start"), n.get("end"), n.get("text")

        if any(isinstance(t, bool) or not isinstance(t, (int, float)) for t in (start, end)):
            raise ValueError("a note's start and end are numbers of seconds")

        start, end = float(start), float(end)  # pyright: ignore[reportArgumentType]

        if not isinstance(text, str) or not text.strip():
            raise ValueError("a note needs some text")

        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end < start:
            raise ValueError("a note ends after it starts, at or after 0 s")

        note_id = str(n.get("id") or f"{start:.3f}-{end:.3f}")[:64]
        out.append({"id": note_id, "start": start, "end": end, "text": text.strip()[:2000]})

    return sorted(out, key=lambda n: (n["start"], n["end"]))


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
