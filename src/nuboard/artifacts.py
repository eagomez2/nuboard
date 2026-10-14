"""Versioned artifacts: ``<project>/artifacts/<name>/v<N>/`` plus ``manifest.json``."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _fs

_VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True)
class Artifact:
    name: str
    version: int
    path: Path
    manifest: dict[str, Any]

    @property
    def ref(self) -> str:
        return f"{self.name}:v{self.version}"

    @property
    def files(self) -> Path:
        """Folder holding the artifact's files."""
        return self.path / "files"


def _versions(adir: Path) -> list[int]:
    if not adir.exists():
        return []
    return sorted(int(m.group(1)) for e in os.listdir(adir) if (m := _VERSION_RE.match(e)))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log_artifact(
    project_dir: Path,
    name: str,
    src: str | os.PathLike[str],
    *,
    type: str | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> Artifact:
    name = _fs.sanitize(name, "artifact")
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    adir = project_dir / "artifacts" / name
    adir.mkdir(parents=True, exist_ok=True)
    staging = adir / f".staging-{_fs.random_suffix()}"
    files_dir = staging / "files"
    if src.is_dir():
        shutil.copytree(src, files_dir)
    else:
        files_dir.mkdir(parents=True)
        shutil.copy2(src, files_dir / src.name)
    entries = []
    for p in sorted(files_dir.rglob("*")):
        if p.is_file():
            entries.append(
                {
                    "path": p.relative_to(files_dir).as_posix(),
                    "size": p.stat().st_size,
                    "sha256": _sha256(p),
                }
            )
    while True:  # claim the next version number; rename is atomic
        version = (_versions(adir) or [0])[-1] + 1
        manifest = {
            "name": name,
            "version": version,
            "type": type,
            "metadata": metadata or {},
            "files": entries,
            "created": time.time(),
            "producer_run": run_id,
        }
        _fs.atomic_write_json(staging / "manifest.json", manifest)
        try:
            os.rename(staging, adir / f"v{version}")
            break
        except OSError:
            if not (adir / f"v{version}").exists():
                raise
    return Artifact(name, version, adir / f"v{version}", manifest)


def resolve_artifact(project_dir: Path, ref: str) -> Artifact:
    name, _, version = ref.partition(":")
    adir = project_dir / "artifacts" / name
    versions = _versions(adir)
    if not versions:
        raise FileNotFoundError(f"no artifact {name!r} in {project_dir}")
    if version in ("", "latest"):
        v = versions[-1]
    else:
        m = _VERSION_RE.match(version)
        if not m or int(m.group(1)) not in versions:
            raise FileNotFoundError(f"no version {version!r} of artifact {name!r}")
        v = int(m.group(1))
    path = adir / f"v{v}"
    return Artifact(name, v, path, _fs.read_json(path / "manifest.json", {}))


def list_artifacts(project_dir: Path) -> list[Artifact]:
    root = project_dir / "artifacts"
    out = []
    if root.exists():
        for name in sorted(os.listdir(root)):
            for v in _versions(root / name):
                path = root / name / f"v{v}"
                out.append(Artifact(name, v, path, _fs.read_json(path / "manifest.json", {})))
    return out
