"""Small filesystem helpers that behave the same on Linux, macOS and Windows."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # lowercase only: no case collisions


def sanitize(name: str, fallback: str = "run") -> str:
    """Make `name` safe as a path component on every OS (no colons, no spaces).

    Runs of characters other than letters, digits, `.`, `_` and `-` become a single
    `-`; leading and trailing dots and dashes are dropped and the result is cut to 64
    characters.

    Args:
        name: The name to clean.
        fallback: Returned when nothing is left after cleaning.

    Returns:
        The cleaned name, or `fallback`.
    """
    cleaned = _SAFE.sub("-", name.strip()).strip(".-")
    return cleaned[:64] or fallback


def random_suffix(n: int = 6) -> str:
    """Return `n` random lowercase letters and digits.

    The alphabet leaves out look-alike characters (`l`, `o`, `0`, `1`) and has no
    uppercase, so suffixes never differ only by case.

    Args:
        n: Number of characters.

    Returns:
        The random suffix.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """Write `data` to `path` atomically via a temp file and `os.replace`.

    The temp file is written next to `path` and synced to disk before it replaces
    the target, so readers see either the old or the new content. On Windows
    `os.replace` fails while another process has the target open, so it is retried
    briefly (20 attempts, 50 ms apart).

    Args:
        path: Destination file.
        data: Content to write.

    Raises:
        PermissionError: If the target stays locked for every retry. The temp file
            is removed first.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{random_suffix(4)}.tmp")

    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                try:
                    os.unlink(tmp)
                finally:
                    raise

            time.sleep(0.05)


def atomic_write_json(path: str | os.PathLike[str], obj: Any) -> None:
    """Write `obj` to `path` as indented UTF-8 JSON, atomically.

    Values JSON cannot encode (NumPy scalars and arrays, paths, sets, ...) are
    converted on a best-effort basis, falling back to their `repr`.

    Args:
        path: Destination file.
        obj: The value to serialize.
    """
    data = json.dumps(obj, indent=2, ensure_ascii=False, default=_json_default)
    atomic_write_bytes(path, data.encode("utf-8"))


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """Read a JSON file, tolerating a missing or malformed file.

    Args:
        path: File to read.
        default: Returned when the file does not exist or is not valid JSON.

    Returns:
        The decoded value, or `default`.
    """

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _json_default(o: Any) -> Any:
    """Best-effort conversion of config values (numpy scalars, paths, sets...)."""

    if hasattr(o, "item") and callable(o.item):
        try:
            return o.item()
        except (TypeError, ValueError):
            pass

    if hasattr(o, "tolist"):
        return o.tolist()

    if isinstance(o, (set, frozenset, tuple)):
        return list(o)

    if isinstance(o, os.PathLike):
        return os.fspath(o)

    return repr(o)


def check_case_collision(directory: Path, name: str) -> None:
    """Raise if `directory` already holds `name` under a different case.

    Such a pair of names works on Linux but collides on macOS and Windows. A missing
    `directory` is fine.

    Args:
        directory: Folder to look in.
        name: Entry name about to be created there.

    Raises:
        FileExistsError: If an entry differing from `name` only by case exists.
    """

    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return

    lower = name.lower()

    for entry in entries:
        if entry != name and entry.lower() == lower:
            raise FileExistsError(
                f"{directory / name} would collide with existing {entry!r} on "
                "case-insensitive filesystems (macOS, Windows)"
            )
