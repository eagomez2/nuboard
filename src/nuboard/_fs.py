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
    """Make ``name`` safe as a path component on every OS (no colons, no spaces)."""
    cleaned = _SAFE.sub("-", name.strip()).strip(".-")
    return cleaned[:64] or fallback


def random_suffix(n: int = 6) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via a temp file and ``os.replace``.

    On Windows ``os.replace`` fails while another process has the target open,
    so it is retried briefly.
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
    data = json.dumps(obj, indent=2, ensure_ascii=False, default=_json_default)
    atomic_write_bytes(path, data.encode("utf-8"))


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
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
    """Raise if ``directory`` already holds ``name`` under a different case.

    Such a pair of names works on Linux but collides on macOS and Windows.
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
