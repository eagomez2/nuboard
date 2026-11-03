"""Versioned artifacts: `<project>/artifacts/<name>/v<N>/` plus `manifest.json`.

A version either holds a copy of its files in `files/`, or is a reference: it
records where the files live (`reference`) and a fingerprint of each file
(size and modification time, plus SHA-256 when asked), and copies nothing.
A referenced path may contain environment variables, as in
`${NUBOARD_DATA_DIR}/fineweb-edu`, which are expanded where the artifact is
used, so the same version points at each machine's own copy of the data. A
path inside `$NUBOARD_DATA_DIR` is stored that way automatically.

A reference to a path inside the artifact's own project, such as a checkpoint
in one of its runs (`runs/<run>/files/best.pt`), is stored relative to the
project folder (`"reference_base": "project"`). It keeps working when the
project is copied, rsynced or merged, and never points outside the project.
`promote_run_path` makes such versions, or copies, from a run's files.

References to an artifact (`ref`) are `"name"`, `"name:latest"` or
`"name:v<N>"`, optionally after a project, as in `"datasets/fineweb-edu:v2"`:
everything before the last `/` is the project, resolved against the same root
folder as the run's own project.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import shlex
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _fs
from ._meta import ENV_PREFIX, NAME

_VERSION_RE = re.compile(r"^v(\d+)$")
UNLINKED = ".unlinked"
"""Folder under `<project>/artifacts/` that holds unlinked versions, by artifact name."""
DATA_ENV = f"{ENV_PREFIX}_DATA_DIR"
"""Environment variable naming each machine's data folder, for portable references."""
_UNSET_RE = re.compile(r"\$\{?(\w+)")


@dataclass(frozen=True)
class Artifact:
    """One version of a named artifact stored in a project.

    Attributes:
        name: The artifact's (sanitized) name.
        version: Version number, starting at 1.
        path: The version's folder, `<project>/artifacts/<name>/v<version>/`.
        manifest: Contents of the version's `manifest.json`: name, version, type,
            metadata, the files with their size and SHA-256, creation time and the id
            of the run that produced it.
    """

    name: str
    version: int
    path: Path
    manifest: dict[str, Any]

    @property
    def ref(self) -> str:
        """Reference string for this version, `<name>:v<version>`."""
        return f"{self.name}:v{self.version}"

    @property
    def project_dir(self) -> Path:
        """The project the version belongs to, linked or unlinked."""
        up = self.path.parent.parent  # <project>/artifacts or <project>/artifacts/.unlinked
        return up.parent.parent if up.name == UNLINKED else up.parent

    @property
    def in_project(self) -> bool:
        """True for a reference stored relative to the project folder."""
        m = self.manifest
        return bool(m.get("reference")) and m.get("reference_base") == "project"

    def _resolve(self, stored: str) -> Path:
        """Return a stored path as a path on this machine."""
        return self.project_dir / stored if self.in_project else _expand(stored)

    @property
    def reference(self) -> Path | None:
        """The referenced file or folder, or None if the version holds a copy.

        Environment variables in the stored path, such as `${NUBOARD_DATA_DIR}`,
        are expanded with this machine's values; a path relative to the project
        (`reference_base` is `"project"`) is taken from the project folder.
        """
        ref = self.manifest.get("reference")
        return self._resolve(ref) if ref else None

    @property
    def files(self) -> Path:
        """Folder holding the artifact's files.

        For a copy this is `<version>/files/`; for a reference to a folder it is
        that folder, and for a reference to one file the folder holding it, so
        `files / <name>` reaches each listed file either way.
        """
        ref = self.reference

        if ref is None:
            return self.path / "files"

        return self._resolve(self.manifest.get("root") or self.manifest["reference"])

    def verify(self) -> list[str]:
        """Check the files against the manifest by size, without reading them.

        Modification times are recorded but not compared, since a copy of the
        data on another machine usually has its own.

        Returns:
            One line per file that is missing or whose size changed since the
            version was made, or a single line naming an environment variable
            the reference needs and this machine does not set; empty when
            everything matches.
        """
        stored = "" if self.in_project else self.manifest.get("reference") or ""
        unset = _UNSET_RE.search(os.path.expandvars(stored))

        if unset:
            return [f"{unset.group(1)} is not set: the files are under ${{{unset.group(1)}}}"]

        problems = []
        root = self.files

        for f in self.manifest.get("files") or []:
            try:
                st = (root / f["path"]).stat()
            except OSError:
                problems.append(f"missing: {f['path']}")
                continue

            if st.st_size != f.get("size"):
                problems.append(f"changed: {f['path']}")

        return problems


def split_ref(ref: str) -> tuple[str | None, str, str]:
    """Split an artifact reference into project, name and version.

    Args:
        ref: Such as `"model"`, `"model:v3"` or `"datasets/fineweb-edu:latest"`.

    Returns:
        `(project, name, version)`; `project` is None when `ref` names none, and
        `version` is `""` when `ref` gives none.
    """
    path, _, version = ref.partition(":")
    project, _, name = path.strip("/").rpartition("/")
    return project or None, name, version


def _created_by() -> dict[str, str | None]:
    """Return who and what is creating a version: user, host and command line."""

    try:
        user: str | None = getpass.getuser()
    except Exception:  # no user name in the environment, as in some containers
        user = None

    return {"user": user, "host": socket.gethostname(), "command": shlex.join(sys.argv)}


def _expand(path: str) -> Path:
    """Return `path` with environment variables and a leading `~` expanded."""
    return Path(os.path.expanduser(os.path.expandvars(path)))


def _portable(path: Path) -> str:
    """Return `path` as `${NUBOARD_DATA_DIR}/...` when it is inside that folder, else as is."""
    data = os.environ.get(DATA_ENV)

    if data:
        try:
            rel = path.relative_to(_expand(data).resolve())
        except ValueError:
            pass
        else:
            return "/".join(["${" + DATA_ENV + "}", *rel.parts])

    return str(path)


def _inside(path: Path, base: Path) -> str | None:
    """Return `path` relative to `base` with `/` separators, or None if it is outside."""

    try:
        rel = path.relative_to(base)
    except ValueError:
        return None

    return rel.as_posix() if rel.parts else None


def find_artifact_projects(root: Path, max_depth: int = 8) -> list[Path]:
    """Find the folders under `root` that hold an `artifacts/` folder.

    `runs/` and `artifacts/` folders and hidden folders are not searched.

    Args:
        root: The folder to search.
        max_depth: How many levels below `root` to search.

    Returns:
        The project folders, sorted.
    """
    found = []
    todo = [(root, 0)]

    while todo:
        d, depth = todo.pop()

        try:
            with os.scandir(d) as it:
                subdirs = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue

        for e in subdirs:
            if e.name == "artifacts":
                found.append(Path(d))
            elif depth < max_depth and not e.name.startswith(".") and e.name != "runs":
                todo.append((Path(e.path), depth + 1))

    return sorted(found)


def _versions(adir: Path) -> list[int]:
    """Return the version numbers present in an artifact folder, in ascending order."""

    if not adir.is_dir():
        return []

    return sorted(int(m.group(1)) for e in os.listdir(adir) if (m := _VERSION_RE.match(e)))


def version_folders(project_dir: Path) -> list[tuple[str, int, Path, bool]]:
    """Return `(name, version, folder, unlinked)` of every artifact version of a project.

    Only folders are listed; no manifest is read.
    """
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


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read in 1 MiB chunks."""
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)

    return h.hexdigest()


def add_artifact(
    project_dir: Path,
    name: str,
    src: str | os.PathLike[str],
    *,
    type: str | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
    reference: bool = False,
    checksum: bool = False,
    description: str | None = None,
    source: dict[str, Any] | None = None,
) -> Artifact:
    """Copy a file or folder into a new version of an artifact, or reference it.

    The files are copied into a staging folder, listed in `manifest.json` with their
    size and SHA-256, and the folder is then renamed to `v<N>`. The rename is atomic,
    so concurrent writers each get their own version number. With `reference`, the
    staging folder holds only the manifest, which records where the files are.

    Args:
        project_dir: The project's folder.
        name: Artifact name; it is sanitized to be safe as a folder name.
        src: File or folder to copy. A folder's contents are copied recursively; a
            single file keeps its name.
        type: Optional free-form type, such as `"model"` or `"dataset"`.
        metadata: Optional extra data stored in the manifest.
        run_id: Id of the run that produced the artifact, if any.
        reference: Record where `src` is instead of copying it. Each file's size and
            modification time are recorded, which is quick even for large datasets.
            Environment variables in `src`, such as `"${DATA}/fineweb"`, are kept
            in the stored path and expanded where the artifact is used; a path
            inside `$NUBOARD_DATA_DIR` is stored relative to it, and a path
            inside `project_dir` relative to the project.
        checksum: With `reference`, also hash each file (SHA-256), which reads all
            of the data. Copies are always hashed.
        description: Optional free text saying what this version is.
        source: Where the files came from, such as `{"run": <id>, "path": ...}`
            for a version made from a run's files; stored as `source`.

    Returns:
        The new version.

    The manifest also records who created the version (`created_by`: user,
    host and command line).

    Raises:
        FileNotFoundError: If `src` does not exist.
        OSError: If the staging folder cannot be renamed for a reason other than
            another writer claiming the same version.
    """
    name = _fs.sanitize(name, "artifact")
    raw = os.fspath(src)
    src = _expand(raw)

    if not src.exists():
        raise FileNotFoundError(src)

    adir = project_dir / "artifacts" / name
    adir.mkdir(parents=True, exist_ok=True)
    staging = adir / f".staging-{_fs.random_suffix()}"
    files_dir = staging / "files"

    extra: dict[str, Any] = {}

    if reference:
        src = src.resolve()
        files_dir = src if src.is_dir() else src.parent
        listed = sorted(files_dir.rglob("*")) if src.is_dir() else [src]
        staging.mkdir()
        inside = _inside(src, project_dir.resolve())

        if inside is not None:  # relative to the project, so it moves with it
            stored = inside
            root = stored if src.is_dir() else (Path(stored).parent.as_posix())
            extra = {"reference": stored, "root": root, "reference_base": "project"}
        else:
            stored = raw.rstrip("/\\") if "$" in raw else _portable(src)
            root = stored if src.is_dir() else str(Path(stored).parent)
            extra = {"reference": stored, "root": root}
    elif src.is_dir():
        shutil.copytree(src, files_dir)
        listed = sorted(files_dir.rglob("*"))
    else:
        files_dir.mkdir(parents=True)
        shutil.copy2(src, files_dir / src.name)
        listed = [files_dir / src.name]

    entries = []

    for p in listed:
        if p.is_file():
            st = p.stat()
            rel = p.relative_to(files_dir).as_posix()
            entry: dict[str, Any] = {"path": rel, "size": st.st_size}

            if reference:
                entry["mtime_ns"] = st.st_mtime_ns

            if not reference or checksum:
                entry["sha256"] = _sha256(p)

            entries.append(entry)

    while True:  # claim the next version number; rename is atomic
        # unlinked versions keep their numbers, so a number never points at other data
        version = max([0, *_versions(adir), *_versions(adir.parent / UNLINKED / name)]) + 1
        manifest = {
            "name": name,
            "version": version,
            "type": type,
            "description": description or "",
            "metadata": metadata or {},
            "files": entries,
            "created": time.time(),
            "producer_run": run_id,
            "created_by": _created_by(),
            **({"source": source} if source else {}),
            **extra,
        }
        _fs.atomic_write_json(staging / "manifest.json", manifest)

        try:
            os.rename(staging, adir / f"v{version}")
            break
        except OSError:
            if not (adir / f"v{version}").exists():
                raise

    return Artifact(name, version, adir / f"v{version}", manifest)


def promote_run_path(
    run_dir: str | os.PathLike[str],
    path: str,
    name: str,
    *,
    copy: bool = True,
    type: str | None = None,
    metadata: dict[str, Any] | None = None,
    checksum: bool = False,
    description: str | None = None,
) -> Artifact:
    """Make an artifact version from a file or folder of a run, in the run's project.

    With `copy`, the files are copied into the version as by `add_artifact`, so the
    version stays the same whatever happens to the run. Without it, the version
    references the files where they are, by a path relative to the project
    (`runs/<run>/<path>`); the run must have finished, and `NAME rm` then refuses
    to delete it while the version is linked.

    The run's folder is never changed: the run is recorded as the version's
    `producer_run`, and `source` holds the run id and the path.

    Args:
        run_dir: The run's folder, `<project>/runs/<run>/`.
        path: File or folder inside the run folder, with `/` separators, such as
            `"files/checkpoints/best.pt"`.
        name: Artifact name; a new version is added if it exists.
        copy: Copy the files (the default) rather than reference them.
        type: Optional free-form type, such as `"checkpoint"`.
        metadata: Optional extra data stored in the manifest.
        checksum: With a reference, also hash each file (copies always are).
        description: Optional free text saying what this version is.

    Returns:
        The new version.

    Raises:
        ValueError: If `path` leaves the run folder, names a file NuBoard writes
            itself (`run.json`, the event logs, ...), or asks for a reference
            to a run that is still running.
        FileNotFoundError: If the run or `path` does not exist.
    """
    run_dir = Path(run_dir).resolve()
    meta = _fs.read_json(run_dir / "run.json", None)

    if not isinstance(meta, dict):
        raise FileNotFoundError(f"no run at {run_dir}")

    rel = path.replace("\\", "/").rstrip("/")
    target = (run_dir / rel).resolve()

    if not rel or rel.startswith("/") or _inside(target, run_dir) is None:
        raise ValueError(f"{path!r} is not inside the run folder")

    rel = _inside(target, run_dir) or rel

    if _fs.RUN_INTERNAL.match(rel):
        raise ValueError(f"{rel} is written by {NAME} itself and cannot be an artifact")

    if not target.exists():
        raise FileNotFoundError(f"{rel} does not exist in the run")

    if not copy and meta.get("status") == "running":
        raise ValueError("the run is still running, so its files may change: copy them instead")

    run_id = str(meta.get("run_id") or run_dir.name)
    return add_artifact(
        run_dir.parent.parent,
        name,
        target,
        type=type,
        metadata=metadata,
        run_id=run_id,
        reference=not copy,
        checksum=checksum,
        description=description,
        source={"run": run_id, "path": rel},
    )


def versions_needing(run_dir: Path) -> list[Artifact]:
    """Return the linked versions of the run's project that reference files in the run.

    Args:
        run_dir: The run's folder, `<project>/runs/<run>/`.

    Returns:
        The versions whose project-relative reference lies inside the run folder.
    """
    prefix = f"runs/{run_dir.name}"
    return [
        a
        for a in list_artifacts(run_dir.parent.parent)
        if a.in_project
        and (a.manifest["reference"] == prefix or a.manifest["reference"].startswith(prefix + "/"))
    ]


def resolve_artifact(project_dir: Path, ref: str) -> Artifact:
    """Find the artifact version a reference points to.

    Args:
        project_dir: The project's folder.
        ref: `"name"` or `"name:latest"` for the newest version, or `"name:v<N>"`
            for a specific one. A project in `ref` is ignored here; callers pick
            `project_dir` from it.

    Returns:
        The matching version.

    Raises:
        FileNotFoundError: If the artifact has no versions or the requested version
            does not exist.
    """
    _, name, version = split_ref(ref)
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
    """List every version of every artifact in a project.

    Args:
        project_dir: The project's folder.

    Returns:
        All versions, sorted by artifact name and then version.
    """
    root = project_dir / "artifacts"
    out = []

    if root.exists():
        for name in sorted(os.listdir(root)):
            if name.startswith("."):  # unlinked versions and staging folders
                continue

            for v in _versions(root / name):
                path = root / name / f"v{v}"
                out.append(Artifact(name, v, path, _fs.read_json(path / "manifest.json", {})))

    return out


def list_unlinked(project_dir: Path) -> list[Artifact]:
    """List the versions unlinked with `unlink_artifact`.

    Args:
        project_dir: The project's folder.

    Returns:
        The unlinked versions, sorted by artifact name and then version.
    """
    root = project_dir / "artifacts" / UNLINKED
    out = []

    if root.exists():
        for name in sorted(os.listdir(root)):
            for v in _versions(root / name):
                path = root / name / f"v{v}"
                out.append(Artifact(name, v, path, _fs.read_json(path / "manifest.json", {})))

    return out


def unlink_artifact(project_dir: Path, name: str, version: int | None = None) -> list[int]:
    """Hide one version, or every version, of an artifact without deleting anything.

    Each version folder moves to `<project>/artifacts/.unlinked/<name>/`, files and
    manifest included; referenced data is never touched. `restore_artifact` moves it
    back. Version numbers stay taken, so a later version never reuses one.

    Args:
        project_dir: The project's folder.
        name: Artifact name.
        version: The version to unlink, or None for all of them.

    Returns:
        The unlinked version numbers.

    Raises:
        FileNotFoundError: If the artifact or version does not exist.
    """
    adir = project_dir / "artifacts" / name
    versions = _versions(adir) if version is None else [version]

    if not versions or not all((adir / f"v{v}").is_dir() for v in versions):
        what = "versions" if version is None else f"v{version}"
        raise FileNotFoundError(f"no {what} of artifact {name!r}")

    into = project_dir / "artifacts" / UNLINKED / name
    into.mkdir(parents=True, exist_ok=True)

    for v in versions:
        os.rename(adir / f"v{v}", into / f"v{v}")

    try:
        adir.rmdir()  # only when nothing is left
    except OSError:
        pass

    return versions


def restore_artifact(project_dir: Path, name: str, version: int) -> Artifact:
    """Move an unlinked version back, under its own number.

    Args:
        project_dir: The project's folder.
        name: Artifact name.
        version: The version to restore.

    Returns:
        The restored version.

    Raises:
        FileNotFoundError: If that version is not unlinked.
    """
    src = project_dir / "artifacts" / UNLINKED / name / f"v{version}"

    if not src.is_dir():
        raise FileNotFoundError(f"v{version} of {name!r} is not unlinked")

    adir = project_dir / "artifacts" / name
    adir.mkdir(parents=True, exist_ok=True)
    os.rename(src, adir / f"v{version}")

    try:
        src.parent.rmdir()
    except OSError:
        pass

    return resolve_artifact(project_dir, f"{name}:v{version}")
