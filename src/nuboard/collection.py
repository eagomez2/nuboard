"""Collections: named, hand-picked sets of runs in ``<project>/collections/<name>.json``.

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
    return project_dir / "collections" / f"{_fs.sanitize(name, 'collection')}.json"


def list_collections(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
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
    """Create or update a collection: add and remove run ids, keep order of addition."""
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
    path = _path(Path(project_dir), name)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


_CACHE: dict[str, tuple[tuple[int, ...], dict[str, list[str]]]] = {}


def memberships(project_dir: str | os.PathLike[str]) -> dict[str, list[str]]:
    """``{run id: [collection names]}`` for one project, cached on file mtimes."""
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
    """Set ``record["collections"]`` from the collections of each run's project."""
    per_project: dict[Path, dict[str, list[str]]] = {}
    for record, run_path in records:
        pdir = run_path.parent.parent
        if pdir not in per_project:
            per_project[pdir] = memberships(pdir)
        record["collections"] = per_project[pdir].get(record["id"], [])
