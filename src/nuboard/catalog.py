"""Discovery of run folders and a disposable SQLite cache of their metadata.

The catalog lives on local disk (``~/.cache/NAME/<hash>.sqlite``), never next
to the runs, so run folders can sit on network filesystems. It is a cache: if
it is missing or its schema version differs, it is rebuilt. No migrations.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import _fs
from ._meta import ENV_PREFIX, NAME
from .collection import attach

SCHEMA_VERSION = 4
STALE_AFTER_S = 120.0  # a "running" run without a heartbeat for this long is "lost"
_SKIP_DIRS = {
    "artifacts",
    "views",
    "collections",
    "node_modules",
    "__pycache__",
    "files",
    "site-packages",
}


def find_runs(root: Path, max_depth: int = 8) -> Iterator[tuple[str, Path]]:
    """Yield ``(project, run_path)`` for every ``<project>/runs/<run>/run.json`` under root.

    ``root`` may be a single run folder, a project, a ``runs/`` folder, or any
    folder tree of projects. ``project`` is the project folder's path relative
    to ``root`` (POSIX separators), or its name if it is ``root`` itself.
    """
    for project, path in _find(str(Path(root).resolve()), max_depth):
        if os.path.exists(os.path.join(path, "run.json")):
            yield project, Path(path)


def _find(root: str, max_depth: int) -> Iterator[tuple[str, str]]:
    """String-based walk (pathlib is too slow for thousands of runs).

    Yields every folder inside a ``runs/`` folder without checking for
    ``run.json``; callers stat it anyway.
    """
    if os.path.exists(os.path.join(root, "run.json")):
        yield os.path.basename(os.path.dirname(os.path.dirname(root))), root
        return
    if os.path.basename(root) == "runs":
        project = os.path.basename(os.path.dirname(root))
        for run in _subdirs(root):
            yield project, run
        return
    stack = [(root, 0)]
    prefix = len(root) + 1
    while stack:
        d, depth = stack.pop()
        for sub in _subdirs(d):
            name = os.path.basename(sub)
            if name == "runs":
                project = d[prefix:].replace(os.sep, "/") if d != root else os.path.basename(root)
                for run in _subdirs(sub):
                    yield project, run
            elif depth < max_depth and name not in _SKIP_DIRS and not name.startswith("."):
                stack.append((sub, depth + 1))


def find_projects(root: Path, max_depth: int = 8) -> list[str]:
    return sorted({p for p, _ in find_runs(root, max_depth)})


def _subdirs(d: str) -> list[str]:
    try:
        with os.scandir(d) as it:
            return sorted(e.path for e in it if e.is_dir(follow_symlinks=False))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []


def _mtime(path: str) -> int:
    try:
        st = os.stat(path)
        return st.st_mtime_ns ^ (st.st_size << 1)
    except FileNotFoundError:
        return 0


def cache_dir() -> Path:
    env = os.environ.get(f"{ENV_PREFIX}_CACHE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / NAME


def effective_status(meta: dict[str, Any], now: float | None = None) -> str:
    status = meta.get("status") or "unknown"
    if status == "running":
        beat = meta.get("heartbeat") or meta.get("started") or 0
        if (now or time.time()) - beat > STALE_AFTER_S:
            return "lost"
    return status


def make_record(
    key: str, project: str, rel: str, meta: dict[str, Any], ann: dict[str, Any]
) -> dict[str, Any]:
    started = meta.get("started") or meta.get("created")
    ended = meta.get("ended")
    beat = meta.get("heartbeat")
    status = effective_status(meta)
    end_for_duration = ended or (beat if status != "running" else time.time())
    git = meta.get("git") or {}
    env = meta.get("env") or {}
    return {
        "key": key,
        "id": meta.get("run_id") or Path(rel).name,
        "project": project,
        "path": rel,
        "name": meta.get("name") or Path(rel).name,
        "status": status,
        "created": meta.get("created"),
        "started": started,
        "ended": ended,
        "heartbeat": beat,
        "duration": (end_for_duration - started) if started and end_for_duration else None,
        "config": meta.get("config") or {},
        "tags": sorted(set(meta.get("tags") or []) | set(ann.get("tags") or [])),
        "notes": ann.get("notes") if ann.get("notes") is not None else (meta.get("notes") or ""),
        "starred": bool(ann.get("starred")),
        "archived": bool(ann.get("archived")),
        "reviewed": bool(ann.get("reviewed")),
        "group": meta.get("group"),
        "summary": meta.get("summary") or {},
        "commit": (git.get("commit") or "")[:10] or None,
        "dirty": bool(git.get("dirty")),
        "host": env.get("host"),
        "world_size": (meta.get("distributed") or {}).get("world_size", 1),
        "fork": meta.get("fork"),
        "inputs": meta.get("inputs") or [],
        "outputs": meta.get("outputs") or [],
        "error": (meta.get("exit") or {}).get("error"),
        "fields": ann.get("fields") or {},
        "alerts": meta.get("alerts") or [],
        "compacted": bool(meta.get("compacted")),
    }


class Catalog:
    """Metadata of every run under ``root``, kept fresh by cheap ``stat`` calls."""

    def __init__(self, root: str | os.PathLike[str], cache: Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.version = 0
        self._rows: dict[str, dict[str, Any]] = {}  # key -> record
        self._state: dict[str, tuple[str, int, int]] = {}  # key -> (path, run_mtime, ann_mtime)
        self._db = self._open_db(cache or cache_dir())
        self._load_db()
        self._last_full = 0.0

    # -- sqlite ---------------------------------------------------------------
    def _open_db(self, directory: Path) -> sqlite3.Connection:
        digest = hashlib.sha1(str(self.root).encode("utf-8")).hexdigest()[:16]
        try:
            directory.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(directory / f"{digest}.sqlite", check_same_thread=False)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                db.execute("DROP TABLE IF EXISTS runs")
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error:
            db = sqlite3.connect(":memory:", check_same_thread=False)
        db.execute(
            "CREATE TABLE IF NOT EXISTS runs (key TEXT PRIMARY KEY, path TEXT, project TEXT,"
            " record TEXT, run_mtime INTEGER, ann_mtime INTEGER)"
        )
        db.commit()
        return db

    def _load_db(self) -> None:
        now = time.time()
        for key, rel, _project, record, rm, am in self._db.execute("SELECT * FROM runs"):
            self._state[key] = (rel, rm, am)
            row = self._rows[key] = json.loads(record)
            if row["status"] == "running" and now - (row["heartbeat"] or 0) > STALE_AFTER_S:
                row["status"] = "lost"

    # -- refresh ----------------------------------------------------------------
    def refresh(self, full: bool = True) -> set[str]:
        """Re-stat run folders; re-read only those that changed. Returns changed keys.

        ``full=False`` only re-checks runs that are currently running, which is
        what the live-update loop does between full scans.
        """
        changed: set[str] = set()
        with self.lock:
            if full or not self._rows:
                seen: set[str] = set()
                taken: dict[str, str] = {}
                root = str(self.root)
                for project, path in _find(root, 8):
                    rel = path[len(root) + 1 :].replace(os.sep, "/") if path != root else "."
                    name = os.path.basename(path)
                    key = name if name not in taken else rel
                    taken[name] = rel
                    if self._check(key, project, path, rel):
                        changed.add(key)
                    if key in self._rows:
                        seen.add(key)
                for key in set(self._rows) - seen:
                    del self._rows[key]
                    del self._state[key]
                    self._db.execute("DELETE FROM runs WHERE key = ?", (key,))
                    changed.add(key)
                self._last_full = time.time()
            else:
                for key, row in list(self._rows.items()):
                    if row["status"] in ("running", "lost"):
                        path = self.path_of(key)
                        if path and self._check(key, row["project"], str(path), row["path"]):
                            changed.add(key)
                        elif (
                            row["status"] == "running"
                            and effective_status(
                                {"status": "running", "heartbeat": row["heartbeat"]}
                            )
                            == "lost"
                        ):
                            row["status"] = "lost"
                            changed.add(key)
            if changed:
                self._db.commit()
                self.version += 1
        return changed

    def _check(self, key: str, project: str, path: str, rel: str) -> bool:
        run_json = os.path.join(path, "run.json")
        ann_json = os.path.join(path, "annotations.json")
        # annotations.json is always replaced atomically, which bumps the folder's mtime
        rm, am = _mtime(run_json), _mtime(path)
        if rm == 0:
            return False
        old = self._state.get(key)
        if old is not None and old[1] == rm and old[2] == am:
            return False
        meta = _fs.read_json(run_json, None)
        if meta is None:  # mid-write on a filesystem without atomic rename; next time
            return False
        ann = _fs.read_json(ann_json, {}) or {}
        self._state[key] = (rel, rm, am)
        self._rows[key] = make_record(key, project, rel, meta, ann)
        self._db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            (key, rel, project, json.dumps(self._rows[key], default=str), rm, am),
        )
        return True

    # -- access -----------------------------------------------------------------
    def runs(self) -> list[dict[str, Any]]:
        """Every run record, with ``collections`` filled from the project folders."""
        with self.lock:
            rows = list(self._rows.values())
            pairs = []
            for row in rows:
                path = self.path_of(row["key"])
                if path is not None:
                    pairs.append((row, path))
            attach(pairs)
            return rows

    def get(self, key: str) -> dict[str, Any] | None:
        return self._rows.get(key)

    def path_of(self, key: str) -> Path | None:
        state = self._state.get(key)
        if state is None:
            return None
        return self.root if state[0] == "." else self.root / state[0]

    def projects(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in self._rows.values():
            counts[row["project"]] = counts.get(row["project"], 0) + 1
        return [{"name": p, "runs": n} for p, n in sorted(counts.items())]
