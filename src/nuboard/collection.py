"""Collections: named, hand-picked sets of runs in `<project>/collections/<name>.json`.

A collection lists run ids, so it survives moving the project folder. It is
plain JSON written atomically; deleting the file deletes the collection.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import _fs


def _path(project_dir: Path, name: str) -> Path:
    """Return the JSON file of collection `name`, with the name sanitized."""
    return project_dir / "collections" / f"{_fs.sanitize(name, 'collection')}.json"


def list_collections(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """List the collections of one project, sorted by file name.

    Files that are not a JSON object are skipped.

    Args:
        project_dir: The project folder.

    Returns:
        One dict per collection, as stored on disk, with `name` defaulting to
        the file name and `runs` normalized to a list of run id strings.
    """
    folder = Path(project_dir) / "collections"
    out = []

    if folder.is_dir():
        for p in sorted(folder.glob("*.json")):
            data = _fs.read_json(p, None)

            if isinstance(data, dict):
                data.setdefault("name", p.stem)
                data["runs"] = [str(r) for r in data.get("runs") or []]
                out.append(data)

    return out


def save_collection(
    project_dir: str | os.PathLike[str],
    name: str,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    description: str | None = None,
) -> dict[str, Any]:
    """Create or update a collection by adding and removing run ids.

    Runs keep their order of addition. A run id listed in both `add` and
    `remove` is removed. The file is written atomically.

    Args:
        project_dir: The project folder.
        name: Collection name; it is sanitized to form the file name.
        add: Run ids to append if not already present.
        remove: Run ids to drop.
        description: New description; `None` leaves the current one.

    Returns:
        The collection as written.
    """
    project_dir = Path(project_dir)
    path = _path(project_dir, name)
    data = _fs.read_json(path, None) or {"name": path.stem, "created": time.time(), "runs": []}
    gone = set(remove)
    runs = [r for r in data.get("runs") or [] if r not in gone]

    for r in add:
        if r not in runs and r not in gone:
            runs.append(r)

    data["runs"] = runs

    if description is not None:
        data["description"] = description

    data["updated"] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    _fs.atomic_write_json(path, data)
    return data


def delete_collection(project_dir: str | os.PathLike[str], name: str) -> bool:
    """Delete a collection's file.

    Args:
        project_dir: The project folder.
        name: Collection name.

    Returns:
        True if the collection existed and was deleted, False otherwise.
    """
    path = _path(Path(project_dir), name)

    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


_CACHE: dict[str, tuple[tuple[int, ...], dict[str, list[str]]]] = {}


def memberships(project_dir: str | os.PathLike[str]) -> dict[str, list[str]]:
    """Map each run id of one project to the collections that contain it.

    The result is cached per project and reused while the modification times
    of the collection files are unchanged; do not mutate it.

    Args:
        project_dir: The project folder.

    Returns:
        `{run id: [collection names]}`; empty if the project has no
        `collections/` folder.
    """
    folder = os.path.join(os.fspath(project_dir), "collections")

    try:
        with os.scandir(folder) as it:
            stamp = tuple(sorted(e.stat().st_mtime_ns for e in it if e.name.endswith(".json")))
    except (FileNotFoundError, NotADirectoryError):
        return {}

    cached = _CACHE.get(folder)

    if cached is not None and cached[0] == stamp:
        return cached[1]

    out: dict[str, list[str]] = {}

    for c in list_collections(project_dir):
        for run_id in c["runs"]:
            out.setdefault(run_id, []).append(c["name"])

    _CACHE[folder] = (stamp, out)
    return out


def attach(records: Iterable[tuple[dict[str, Any], Path]]) -> None:
    """Set `record["collections"]` from the collections of each run's project.

    Args:
        records: `(record, run_path)` pairs, where `record` is a run record
            with an `id` key and `run_path` is `<project>/runs/<run>`.
    """
    per_project: dict[Path, dict[str, list[str]]] = {}

    for record, run_path in records:
        pdir = run_path.parent.parent

        if pdir not in per_project:
            per_project[pdir] = memberships(pdir)

        record["collections"] = per_project[pdir].get(record["id"], [])
