"""Disk use of the served folder, measured only when the viewer asks.

`Meter.start` walks every project in a background thread: each run folder, each
artifact version and the rest of the project folder (reports, views, ...). It
only lists folders and reads sizes (`lstat`, so a symlink counts as the link,
not its target), and never opens a file. A referenced artifact version stores
only its manifest; the size of the files it points to is reported apart, as
`referenced`, and counts toward no total.

After `PAUSE_AFTER_S` of work the walk pauses until `resume` (or `stop`, which
keeps the partial result), so a huge folder never runs on unattended. The last
result is saved in the cache folder and survives a restart of the viewer.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import _fs
from ..artifacts import UNLINKED

PAUSE_AFTER_S = 10.0
RUNS_PER_PROJECT = 200  # largest runs listed per project; the rest are summed


def folder_size(path: str, skip: frozenset[str] = frozenset()) -> int:
    """Return the total size of the files under `path`, without following symlinks.

    Folders whose path is in `skip` are left out.
    """
    total = 0
    todo = [path]

    while todo:
        d = todo.pop()

        if d in skip:
            continue

        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            todo.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue

    return total


def run_parts(path: str) -> dict[str, int]:
    """Split a run folder's size into scalars, media, console, files and other."""
    parts = {"scalars": 0, "media": 0, "console": 0, "files": 0, "other": 0}

    try:
        entries = list(os.scandir(path))
    except OSError:
        return parts

    for e in entries:
        try:
            if e.name == "files" and e.is_dir(follow_symlinks=False):
                for f in os.scandir(e.path):
                    size = (
                        folder_size(f.path)
                        if f.is_dir(follow_symlinks=False)
                        else f.stat(follow_symlinks=False).st_size
                    )
                    is_console = f.name.startswith("output.") and f.name.endswith(".log")
                    parts["console" if is_console else "files"] += size
            elif e.is_dir(follow_symlinks=False):
                parts["other"] += folder_size(e.path)
            else:
                size = e.stat(follow_symlinks=False).st_size
                is_scalars = e.name.startswith("events.") or e.name == "data.parquet"
                kind = "scalars" if is_scalars else "media" if e.name.startswith("media.") else ""
                parts[kind or "other"] += size
        except OSError:
            continue

    return parts


class Meter:
    """Measures disk use on request, one walk at a time.

    Args:
        root: The served folder.
        projects: Returns the project folders to measure, each with its name.
        runs: Returns `(key, name, run folder)` of every run.
        cache: Folder where the last result is kept.
    """

    def __init__(
        self,
        root: Path,
        projects: Callable[[], list[tuple[str, Path]]],
        runs: Callable[[], list[tuple[str, str, Path]]],
        cache: Path,
    ) -> None:
        self.root = root
        self._projects = projects
        self._runs = runs
        digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:16]
        self._file = cache / f"{digest}.storage.json"
        self._lock = threading.Lock()
        self._go = threading.Event()
        self._stopping = False
        self.state = "idle"  # idle, measuring, paused
        self.progress: dict[str, Any] = {}
        self.result: dict[str, Any] | None = _fs.read_json(self._file, None)

    def status(self) -> dict[str, Any]:
        """Return the state, the progress of a walk under way, and the last result."""

        with self._lock:
            return {"state": self.state, "progress": dict(self.progress), "result": self.result}

    def start(self) -> None:
        """Start a walk, unless one is under way."""

        with self._lock:
            if self.state != "idle":
                return

            self.state = "measuring"
            self.progress = {"done": 0, "total": 0, "bytes": 0, "seconds": 0.0}
            self._stopping = False
            self._go.set()

        threading.Thread(target=self._walk, name="nuboard-storage", daemon=True).start()

    def resume(self) -> None:
        """Continue a paused walk."""

        with self._lock:
            if self.state == "paused":
                self.state = "measuring"
                self._go.set()

    def stop(self) -> None:
        """End a paused or running walk, keeping what it measured as a partial result."""

        with self._lock:
            self._stopping = True
            self._go.set()

    def _walk(self) -> None:
        """Measure every project and run; pause every `PAUSE_AFTER_S` of work."""
        began = time.time()
        projects = self._projects()
        runs_by_dir: dict[Path, list[tuple[str, str, Path]]] = {}

        for key, name, path in self._runs():
            runs_by_dir.setdefault(path.parent.parent, []).append((key, name, path))

        dirs = {str(p) for _, p in projects}
        units = sum(len(runs_by_dir.get(p, [])) for _, p in projects)
        units += sum(len(_versions(p)) for _, p in projects)
        self.progress["total"] = units
        out: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        worked, mark = 0.0, time.monotonic()
        partial = False

        def tick(size: int) -> bool:
            """Count one unit; pause when due. Return False to stop."""
            nonlocal worked, mark
            now = time.monotonic()
            worked += now - mark
            mark = now

            with self._lock:
                self.progress["done"] += 1
                self.progress["bytes"] += size
                self.progress["seconds"] = round(worked, 1)

                if worked >= PAUSE_AFTER_S * (1 + int(self.progress.get("pauses", 0))):
                    self.progress["pauses"] = int(self.progress.get("pauses", 0)) + 1
                    self.state = "paused"
                    self._go.clear()

            self._go.wait()
            mark = time.monotonic()
            return not self._stopping

        for pname, pdir in projects:
            if partial:
                break

            rows = []
            run_total = 0

            for key, name, path in runs_by_dir.get(pdir, []):
                parts = run_parts(str(path))
                size = sum(parts.values())
                run_total += size
                rows.append({"key": key, "name": name, "id": path.name, "bytes": size, **parts})

                if not tick(size):
                    partial = True
                    break

            art_total = 0

            for name, version, vdir, unlinked in _versions(pdir) if not partial else []:
                stored = folder_size(str(vdir))
                manifest = _fs.read_json(vdir / "manifest.json", {}) or {}
                ref = bool(manifest.get("reference"))
                referenced = sum(int(f.get("size") or 0) for f in manifest.get("files") or [])
                art_total += stored
                artifacts.append(
                    {
                        "project": pname,
                        "name": name,
                        "version": version,
                        "bytes": stored,
                        "reference": ref,
                        "referenced": referenced if ref else 0,
                        "unlinked": unlinked,
                    }
                )

                if not tick(stored):
                    partial = True
                    break

            mine = {str(pdir / "runs"), str(pdir / "artifacts")}
            other = 0 if partial else folder_size(str(pdir), frozenset(dirs - {str(pdir)} | mine))
            rows.sort(key=lambda r: -r["bytes"])
            rest = rows[RUNS_PER_PROJECT:]
            out.append(
                {
                    "name": pname,
                    "runs_bytes": run_total,
                    "artifacts_bytes": art_total,
                    "other_bytes": other,
                    "run_count": len(rows),
                    "runs": rows[:RUNS_PER_PROJECT],
                    "rest": {"count": len(rest), "bytes": sum(r["bytes"] for r in rest)},
                }
            )

        result = {
            "measured_at": time.time(),
            "seconds": round(time.time() - began, 1),
            "partial": partial,
            "projects": sorted(out, key=lambda p: -(p["runs_bytes"] + p["artifacts_bytes"])),
            "artifacts": artifacts,
        }

        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            _fs.atomic_write_bytes(self._file, json.dumps(result).encode("utf-8"))
        except OSError:
            pass  # kept in memory only

        with self._lock:
            self.result = result
            self.state = "idle"
            self.progress = {}


def _versions(project_dir: Path) -> list[tuple[str, int, Path, bool]]:
    """Return `(name, version, folder, unlinked)` of every artifact version of a project."""
    out = []

    art = project_dir / "artifacts"

    for base, unlinked in ((art, False), (art / UNLINKED, True)):
        try:
            names = [e for e in os.scandir(base) if e.is_dir() and not e.name.startswith(".")]
        except OSError:
            continue

        for n in names:
            try:
                for v in os.scandir(n.path):
                    if v.is_dir() and v.name[:1] == "v" and v.name[1:].isdigit():
                        out.append((n.name, int(v.name[1:]), Path(v.path), unlinked))
            except OSError:
                continue

    return sorted(out, key=lambda x: (x[0], x[1]))
