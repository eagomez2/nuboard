"""The files of a run folder, as listed and previewed by the viewer's Files tab."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .tensorfiles import SUFFIXES as TENSOR_SUFFIXES

MAX_FILES = 20_000  # files listed per run; the count and size still cover every file
SNIFF_FILES = 2_000  # files without a known suffix checked for text content
TEXT_SUFFIXES = {
    ".txt", ".log", ".md", ".rst", ".py", ".sh", ".yaml", ".yml", ".toml", ".json",
    ".jsonl", ".csv", ".tsv", ".patch", ".diff", ".ini", ".cfg", ".conf", ".xml",
    ".html", ".svg", ".js", ".ts", ".c", ".h", ".cpp", ".cu", ".lock", ".env", ".out", ".err",
}  # fmt: skip
IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}  # fmt: skip

# Files NuBoard writes itself, at the top of a run folder
_INTERNAL = re.compile(
    r"^(run\.json|annotations\.json|data\.parquet|events\.r\d+\.s\d+\.log|media\.r\d+\.pack)$"
)


def kind_of(rel: str, path: Path, sniff: bool) -> str:
    """The kind of a run file: `text`, `image`, `tensors` or `other`.

    Args:
        rel: Path inside the run folder, with `/` separators.
        path: The file.
        sniff: Look at the first bytes of a file whose suffix is not known.
    """
    suffix = Path(rel).suffix.lower()

    if suffix in TEXT_SUFFIXES:
        return "text"

    if suffix in IMAGE_SUFFIXES:
        return "image"

    if suffix in TENSOR_SUFFIXES:
        return "tensors"

    if sniff and looks_like_text(path):
        return "text"

    return "other"


def looks_like_text(path: Path) -> bool:
    """True when the first 4 KB of a file are UTF-8 without NUL bytes."""

    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return False

    if not head or b"\0" in head:
        return False

    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc.start > len(head) - 4  # a character cut at the end of the 4 KB

    return True


def list_files(run_dir: Path) -> dict[str, Any]:
    """List every file under a run folder.

    Symbolic links are skipped, so nothing outside the run folder is listed.

    Returns:
        `files` (each with `path`, `size`, `mtime`, `kind` and `internal`: written
        by NuBoard itself), `count` and `bytes` over every file, and `truncated`
        when more than `MAX_FILES` exist.
    """
    files: list[dict[str, Any]] = []
    count = 0
    total = 0
    sniffed = 0

    for root, dirs, names in os.walk(run_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        base = Path(root)

        for name in sorted(names):
            path = base / name

            try:
                st = path.lstat()
            except OSError:
                continue

            if not path.is_file() or path.is_symlink():
                continue

            count += 1
            total += st.st_size

            if len(files) >= MAX_FILES:
                continue

            rel = path.relative_to(run_dir).as_posix()
            sniff = sniffed < SNIFF_FILES and not Path(name).suffix and st.st_size > 0
            sniffed += sniff
            files.append(
                {
                    "path": rel,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "kind": kind_of(rel, path, sniff),
                    "internal": "/" not in rel and bool(_INTERNAL.match(rel)),
                }
            )

    return {"files": files, "count": count, "bytes": total, "truncated": count > len(files)}
