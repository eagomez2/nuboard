"""Which way is better for each scalar or table column of a project, in `<project>/directions.json`.

The viewer guesses a direction from the name (`loss` is better lower) until someone saves one;
a saved direction is kept here, the one place it is stored, so everyone viewing the folder ranks
and colors the same way. The file holds

    {"directions": {"train/loss": "min", "val/acc": "max", "eval/samples › pesq": "max"}}

A table column is stored under its table's key and the column name joined by ` › `, so it never
shares a direction with a scalar of the same name.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path

from . import _fs

DIRECTIONS = ("min", "max")
MAX_DIRECTIONS = 2000
COLUMN_SEP = " › "  # between a table's key and a column name
_lock = threading.Lock()


class DirectionConflict(Exception):
    """A direction changed since the viewer read it; `current` is what it is now (or None)."""

    def __init__(self, name: str, current: str | None) -> None:
        super().__init__(f"{name} was changed meanwhile: it is now {current or 'unset'}")
        self.current = current


def column_key(table: str, column: str) -> str:
    """The name a table column's direction is stored under."""
    return f"{table}{COLUMN_SEP}{column}"


def read_directions(project_dir: Path) -> dict[str, str]:
    """Return the directions saved for a project, by scalar name or `column_key`."""
    data = _fs.read_json(project_dir / "directions.json", {}) or {}
    directions = data.get("directions") if isinstance(data, dict) else None

    if not isinstance(directions, dict):
        return {}

    return {k: v for k, v in directions.items() if isinstance(k, str) and k and v in DIRECTIONS}


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on `path` (created if missing), across processes.

    Two viewers serving the same folder then never interleave a read and a write of
    `directions.json`. Where the platform has no lock (or the folder refuses one), only the
    in-process lock applies.
    """

    with _lock:
        try:
            f = open(path, "a+b")
        except OSError:
            yield
            return

        try:
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except OSError:  # pragma: no cover - a filesystem without locks
            pass

        try:
            yield
        finally:
            f.close()  # releases the lock


_UNSET = object()


def change_direction(
    project_dir: Path, name: str, direction: str | None, expect: str | object | None = _UNSET
) -> dict[str, str]:
    """Set (or with None, clear) the direction of `name` and return the directions as written.

    Each change re-reads the file under a lock held across processes, so directions saved by
    others since are kept.

    Args:
        project_dir: The project folder.
        name: A scalar name or a `column_key`.
        direction: `min` (lower is better), `max`, or None to clear it.
        expect: What the caller last saw for `name` (`min`, `max` or None for unset). When
            given and the file says otherwise, nothing is written.

    Raises:
        ValueError: If `name` is empty or too long, `direction` is not `min`, `max` or None, or the
            project has `MAX_DIRECTIONS` already.
        DirectionConflict: If `name` no longer has the direction in `expect`.
        OSError: If `directions.json` cannot be written.
    """
    name = name.strip()

    if not name or len(name) > 512:
        raise ValueError("a direction needs the name of a scalar or column")

    if direction is not None and direction not in DIRECTIONS:
        raise ValueError(f"a direction is 'min' or 'max', not {direction!r}")

    with _file_lock(project_dir / ".directions.lock"):
        directions = read_directions(project_dir)

        if expect is not _UNSET and directions.get(name) != expect:
            raise DirectionConflict(name, directions.get(name))

        if direction is None:
            directions.pop(name, None)
        else:
            if name not in directions and len(directions) >= MAX_DIRECTIONS:
                raise ValueError(f"a project has at most {MAX_DIRECTIONS} directions")

            directions[name] = direction

        _fs.atomic_write_json(
            project_dir / "directions.json", {"directions": dict(sorted(directions.items()))}
        )
        return directions
