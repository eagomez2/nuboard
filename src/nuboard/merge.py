"""Merge one folder of projects into another: `NAME merge SRC DEST`.

A project logged on two machines ends up as two folders. Runs never clash
(each run folder is named by its id), but artifact versions, collections,
reports, views and project settings with the same name can. `plan` reads both
trees and lists what a merge would do without writing anything; `render` shows
that plan; `apply` checks that nothing changed since the plan was made and
carries it out. Nothing in SRC or DEST is overwritten or deleted: a run that
is replaced by a newer copy is moved to `<project>/.merge-replaced/`, and a
report or view that differs is copied next to DEST's under a new name.

Projects are matched by their path relative to SRC and DEST, so give two roots
(`~/from-gpu ~/exp`) or two project folders.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import _fs
from .catalog import effective_status

# What a project folder can hold besides runs; a folder holding any of these is a project.
_PROJECT_ENTRIES = (
    "runs",
    "artifacts",
    "collections",
    "views",
    "reports",
    "sweeps.json",
    "fields.json",
)
_NOT_PROJECTS = {"runs", "artifacts", "collections", "views", "reports", "node_modules"}
TMP = ".merge-tmp"  # staging inside a DEST project; hidden folders are never indexed
REPLACED = ".merge-replaced"

ADD, SAME, UPDATE, ATTENTION = "+", "=", "~", "!"


@dataclass
class Action:
    """One step of a merge.

    Attributes:
        project: Project path relative to SRC and DEST (`""` when they are projects).
        kind: `run`, `artifact`, `collection`, `report`, `report-file`, `view`,
            `sweeps.json`, `fields.json` or `annotations`.
        op: `+` copy, `=` nothing to do, `~` update or combine, `!` needs a look
            (a conflict that is skipped, a renamed copy, a renumbered artifact).
        name: What it is about: a run id, `name:vN`, a file name.
        detail: One line saying what happens.
        src: The source file or folder.
        dest: Where it goes in DEST.
        conflict: True when the item is skipped because the two sides disagree.
        data: What `apply` needs beyond copying (merged JSON, a new version).
        sig: A fingerprint of `src` and `dest`, compared again by `apply`.
    """

    project: str
    kind: str
    op: str
    name: str
    detail: str
    src: str | None = None
    dest: str | None = None
    conflict: bool = False
    data: Any = None
    sig: list[Any] = field(default_factory=list)


@dataclass
class Plan:
    """What merging `src` into `dest` does, as a list of actions."""

    src: str
    dest: str
    actions: list[Action]
    project: str | None = None
    include_running: bool = False

    @property
    def changes(self) -> list[Action]:
        """The actions that write something."""
        return [
            a
            for a in self.actions
            if a.op in (ADD, UPDATE) or (a.op == ATTENTION and not a.conflict)
        ]

    @property
    def conflicts(self) -> list[Action]:
        """The actions skipped because the two sides disagree."""
        return [a for a in self.actions if a.conflict]

    def to_json(self) -> dict[str, Any]:
        """Return the plan as JSON-ready data (for `--json`)."""
        return {
            "src": self.src,
            "dest": self.dest,
            "actions": [
                {k: v for k, v in asdict(a).items() if k not in ("data", "sig")}
                for a in self.actions
            ],
        }


# ---- reading ----


def _fingerprint(path: Path) -> list[Any]:
    """Return `[files, bytes, newest mtime_ns]` of a file or folder; `[]` when absent."""

    if not path.exists():
        return []

    if path.is_file():
        st = path.stat()
        return [1, st.st_size, st.st_mtime_ns]

    n = size = newest = 0

    for dirpath, _, files in os.walk(path):
        for f in files:
            st = os.stat(os.path.join(dirpath, f))
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)

    return [n, size, newest]


def _tree(path: Path, skip: tuple[str, ...] = ()) -> dict[str, int]:
    """Return `{relative path: size}` of every file under `path`, leaving out `skip` names."""
    out = {}

    for dirpath, _, files in os.walk(path):
        for f in files:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, path).replace(os.sep, "/")

            if rel not in skip:
                out[rel] = os.path.getsize(full)

    return out


def _same_bytes(a: Path, b: Path) -> bool:
    """Return whether two files hold the same bytes."""

    if a.stat().st_size != b.stat().st_size:
        return False

    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x = fa.read(1 << 20)

            if x != fb.read(1 << 20):
                return False

            if not x:
                return True


def find_projects(root: Path, max_depth: int = 8) -> list[str]:
    """List the project folders under `root`, as paths relative to it (`""` for `root` itself).

    A folder is a project when it holds `runs/`, `artifacts/`, `collections/`,
    `views/`, `reports/`, `sweeps.json` or `fields.json`.
    """
    found = []
    todo = [(root, 0)]

    while todo:
        d, depth = todo.pop()

        if any((d / e).exists() for e in _PROJECT_ENTRIES):
            found.append(d.relative_to(root).as_posix() if d != root else "")

        if depth >= max_depth:
            continue

        try:
            subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue

        for e in subs:
            if not e.name.startswith(".") and e.name not in _NOT_PROJECTS:
                todo.append((Path(e.path), depth + 1))

    return sorted(found)


# ---- planning ----


def _run_folders(project_dir: Path) -> dict[str, Path]:
    """Return the run folders (`runs/<id>/` with a `run.json`) of a project by id."""
    runs = project_dir / "runs"

    if not runs.is_dir():
        return {}

    return {
        e.name: Path(e.path)
        for e in os.scandir(runs)
        if e.is_dir() and not e.name.startswith(".") and (Path(e.path) / "run.json").exists()
    }


def _merge_annotations(
    dest: dict[str, Any], src: dict[str, Any], src_newer: bool
) -> dict[str, Any]:
    """Combine two `annotations.json`.

    Flags are set if either sets them, tags and audio notes are joined, the
    newer notes are kept, and DEST's property values win over SRC's.
    """
    out = dict(dest)

    for flag in ("starred", "archived", "reviewed"):
        if dest.get(flag) or src.get(flag):
            out[flag] = True

    if "tags" in src or "tags" in dest:
        out["tags"] = list(dict.fromkeys([*(dest.get("tags") or []), *(src.get("tags") or [])]))

    if src.get("notes") and (src_newer or not dest.get("notes")):
        out["notes"] = src["notes"]

    out["fields"] = {**(src.get("fields") or {}), **(dest.get("fields") or {})}

    if not out["fields"]:
        del out["fields"]

    audio = dict(dest.get("audio_notes") or {})

    for key, notes in (src.get("audio_notes") or {}).items():
        ids = {n.get("id") for n in audio.get(key, [])}
        audio[key] = [*audio.get(key, []), *(n for n in notes if n.get("id") not in ids)]

    if audio:
        out["audio_notes"] = audio

    return out


def _run_action(
    base: dict[str, Any], op: str, detail: str, conflict: bool = False, data: Any = None
) -> Action:
    """Return an action about a run; `base` holds its project, name, paths and fingerprint."""
    return Action(kind="run", op=op, detail=detail, conflict=conflict, data=data, **base)


def _plan_runs(
    project: str,
    sp: Path,
    dp: Path,
    include_running: bool,
    src_root: Path,
    mapping: dict[str, int],
) -> list[Action]:
    """Plan the runs of one project (and their `annotations.json`).

    `run.json` is compared as it will be in DEST, with its artifact versions
    renumbered by `mapping`, so a run copied by an earlier merge is identical.
    """
    out = []
    dest_runs = _run_folders(dp)

    for rid, src in sorted(_run_folders(sp).items()):
        dest = dp / "runs" / rid
        meta = _fs.read_json(src / "run.json", {}) or {}
        label = f"{rid} ({meta.get('name') or 'run'})"
        sig = [_fingerprint(src), _fingerprint(dest)]

        base = {"project": project, "name": label, "src": str(src), "dest": str(dest), "sig": sig}

        if effective_status(meta) == "running" and not include_running:
            out.append(
                _run_action(
                    base, ATTENTION, "still running in SRC, skipped (use --include-running)", True
                )
            )
            continue

        if rid not in dest_runs:
            out.append(_run_action(base, ADD, "copied"))
            continue

        skip = ("annotations.json", "run.json")
        a, b = _tree(src, skip), _tree(dest, skip)
        dest_meta = _fs.read_json(dest / "run.json", {}) or {}
        moved = json.loads(json.dumps(meta))
        _repoint(moved, project, src_root, sp, mapping)
        same = (
            a == b
            and moved == dest_meta
            and all(_same_bytes(src / f, dest / f) for f in a if f.endswith((".json", ".txt")))
        )

        if not same:
            grows = lambda x, y: all(f in x and x[f] >= y[f] for f in y)  # noqa: E731
            src_beat = meta.get("heartbeat") or meta.get("ended") or 0
            dest_beat = dest_meta.get("heartbeat") or dest_meta.get("ended") or 0

            if grows(a, b) and src_beat >= dest_beat:
                out.append(
                    _run_action(
                        base,
                        UPDATE,
                        f"SRC has a later copy: replaced, DEST's kept in {REPLACED}/",
                        data={"replace": True},
                    )
                )
            elif grows(b, a) and dest_beat >= src_beat:
                out.append(_run_action(base, SAME, "DEST has a later copy, kept"))
            else:
                out.append(_run_action(base, ATTENTION, "same id, different files: skipped", True))

            continue

        sa = _fs.read_json(src / "annotations.json", None)
        da = _fs.read_json(dest / "annotations.json", None)

        if not isinstance(sa, dict) or sa == da:
            out.append(_run_action(base, SAME, "identical"))
            continue

        newer = (src / "annotations.json").stat().st_mtime > (
            (dest / "annotations.json").stat().st_mtime if da is not None else 0
        )
        merged = _merge_annotations(da if isinstance(da, dict) else {}, sa, newer)

        if merged == da:
            out.append(_run_action(base, SAME, "identical"))
        else:
            out.append(
                Action(
                    project,
                    "annotations",
                    UPDATE,
                    label,
                    "notes, tags and stars combined",
                    str(src / "annotations.json"),
                    str(dest / "annotations.json"),
                    data=merged,
                    sig=sig,
                )
            )

    return out


def _versions(project_dir: Path) -> dict[tuple[str, int], tuple[Path, bool]]:
    """Return `{(name, version): (folder, unlinked)}` of a project's artifact versions."""
    from .artifacts import version_folders

    return {(n, v): (p, unlinked) for n, v, p, unlinked in version_folders(project_dir)}


def _content(manifest: dict[str, Any]) -> Any:
    """What makes two artifact versions the same: type, reference and files."""
    files = sorted(
        (f.get("path"), f.get("size"), f.get("sha256")) for f in manifest.get("files") or []
    )
    return [manifest.get("type"), manifest.get("reference"), files]


def _plan_artifacts(
    project: str, sp: Path, dp: Path
) -> tuple[list[Action], dict[tuple[str, int], int]]:
    """Plan the artifact versions of one project.

    Returns:
        The actions, and the new number of each SRC version that DEST gets
        under another number (`(name, old version) -> new version`).
    """
    src = {k: v for k, v in _versions(sp).items() if not v[1]}  # unlinked versions stay behind
    dest = _versions(dp)
    taken = {k for k in dest}
    content = {
        k: _content(_fs.read_json(p / "manifest.json", {}) or {}) for k, (p, _) in dest.items()
    }
    out, renumber, later = [], {}, []

    for (name, v), (path, _) in sorted(src.items()):
        mine = _content(_fs.read_json(path / "manifest.json", {}) or {})
        sig = [_fingerprint(path), _fingerprint(dp / "artifacts" / name / f"v{v}")]
        same = next(
            (dv for (dn, dv), c in sorted(content.items()) if dn == name and c == mine), None
        )

        if same is not None:
            if same != v:
                renumber[(name, v)] = same

            detail = (
                "identical, skipped"
                if same == v
                else f"same files as DEST's v{same}: runs repointed"
            )
            out.append(
                Action(project, "artifact", SAME, f"{name}:v{v}", detail, str(path), None, sig=sig)
            )
        elif (name, v) not in taken:
            taken.add((name, v))
            dest_dir = dp / "artifacts" / name / f"v{v}"
            out.append(
                Action(
                    project,
                    "artifact",
                    ADD,
                    f"{name}:v{v}",
                    "copied",
                    str(path),
                    str(dest_dir),
                    sig=sig,
                )
            )
        else:
            later.append((name, v, path, sig))

    for name, v, path, sig in later:  # after the free numbers are kept, so they don't move
        new = max(n for (dn, n) in taken | set(src) if dn == name) + 1
        taken.add((name, new))
        renumber[(name, v)] = new
        dest_dir = dp / "artifacts" / name / f"v{new}"
        detail = f"copied as v{new} (DEST has a different v{v}); copied runs repointed"
        out.append(
            Action(
                project,
                "artifact",
                ATTENTION,
                f"{name}:v{v}",
                detail,
                str(path),
                str(dest_dir),
                data={"version": new},
                sig=sig,
            )
        )

    return out, renumber


def _free_name(folder: Path, stem: str, suffix: str, src_name: str) -> Path:
    """Return `<stem>-from-<src_name><suffix>` in `folder`, numbered if that is taken."""
    path = folder / f"{stem}-from-{src_name}{suffix}"
    n = 2

    while path.exists():
        path = folder / f"{stem}-from-{src_name}-{n}{suffix}"
        n += 1

    return path


def _plan_files(project: str, sp: Path, dp: Path, src_name: str) -> list[Action]:
    """Plan reports, report files, views, collections, `sweeps.json` and `fields.json`."""
    out = []

    def file_action(kind: str, src: Path, dest: Path, rename: bool) -> Action:
        """Copy `src` to `dest` if missing; if it differs, copy next to it (`rename`) or skip."""
        sig = [_fingerprint(src), _fingerprint(dest)]
        rel = dest.relative_to(dp).as_posix()

        if not dest.exists():
            return Action(project, kind, ADD, rel, "new", str(src), str(dest), sig=sig)

        if _same_bytes(src, dest):
            return Action(project, kind, SAME, rel, "identical", str(src), str(dest), sig=sig)

        if not rename:
            return Action(
                project,
                kind,
                ATTENTION,
                rel,
                "both differ: DEST's kept",
                str(src),
                str(dest),
                True,
                sig=sig,
            )

        for p in dest.parent.glob(f"{dest.stem}-from-{src_name}*{dest.suffix}"):
            if _same_bytes(src, p):  # copied by an earlier merge
                return Action(
                    project,
                    kind,
                    SAME,
                    rel,
                    f"already copied as {p.name}",
                    str(src),
                    str(p),
                    sig=sig,
                )

        new = _free_name(dest.parent, dest.stem, dest.suffix, src_name)
        detail = f"both differ: SRC's saved as {new.name}"
        return Action(project, kind, ATTENTION, rel, detail, str(src), str(new), sig=sig)

    for f in sorted((sp / "reports").glob("*.md")):
        out.append(file_action("report", f, dp / "reports" / f.name, True))

    files = sp / "reports" / "files"

    if files.is_dir():
        for f in sorted(p for p in files.iterdir() if p.is_file()):
            out.append(file_action("report-file", f, dp / "reports" / "files" / f.name, False))

    for f in sorted((sp / "views").glob("*.json")):
        out.append(file_action("view", f, dp / "views" / f.name, True))

    for f in sorted((sp / "collections").glob("*.json")):
        dest = dp / "collections" / f.name
        sig = [_fingerprint(f), _fingerprint(dest)]
        rel = dest.relative_to(dp).as_posix()
        mine = _fs.read_json(f, None)

        if not isinstance(mine, dict):
            continue

        theirs = _fs.read_json(dest, None)

        if not isinstance(theirs, dict):
            out.append(Action(project, "collection", ADD, rel, "new", str(f), str(dest), sig=sig))
            continue

        have = [str(r) for r in theirs.get("runs") or []]
        new = [str(r) for r in mine.get("runs") or [] if str(r) not in have]

        if new:
            merged = {**theirs, "runs": have + new, "updated": time.time()}
            detail = f"{len(new)} run id{'s' if len(new) > 1 else ''} added"
            out.append(
                Action(
                    project,
                    "collection",
                    UPDATE,
                    rel,
                    detail,
                    str(f),
                    str(dest),
                    data=merged,
                    sig=sig,
                )
            )
        else:
            out.append(
                Action(project, "collection", SAME, rel, "no new runs", str(f), str(dest), sig=sig)
            )

    sweeps = sp / "sweeps.json"

    if sweeps.is_file():
        dest = dp / "sweeps.json"
        sig = [_fingerprint(sweeps), _fingerprint(dest)]
        mine = str((_fs.read_json(sweeps, {}) or {}).get("hide") or "").split()
        theirs = str((_fs.read_json(dest, {}) or {}).get("hide") or "").split()

        if not dest.exists():
            out.append(
                Action(
                    project,
                    "sweeps.json",
                    ADD,
                    "sweeps.json",
                    "new",
                    str(sweeps),
                    str(dest),
                    sig=sig,
                )
            )
        elif set(mine) <= set(theirs):
            out.append(
                Action(
                    project,
                    "sweeps.json",
                    SAME,
                    "sweeps.json",
                    "nothing new",
                    str(sweeps),
                    str(dest),
                    sig=sig,
                )
            )
        elif all(
            t.startswith("!") for t in mine + theirs
        ):  # exclusions only: hide what either hides
            hide = " ".join(dict.fromkeys(theirs + mine))
            out.append(
                Action(
                    project,
                    "sweeps.json",
                    UPDATE,
                    "sweeps.json",
                    f"hide rules combined: {hide}",
                    str(sweeps),
                    str(dest),
                    data={"hide": hide},
                    sig=sig,
                )
            )
        else:
            detail = "both differ: DEST's hide rules kept"
            out.append(
                Action(
                    project,
                    "sweeps.json",
                    ATTENTION,
                    "sweeps.json",
                    detail,
                    str(sweeps),
                    str(dest),
                    True,
                    sig=sig,
                )
            )

    fields = sp / "fields.json"

    if fields.is_file():
        dest = dp / "fields.json"
        sig = [_fingerprint(fields), _fingerprint(dest)]
        mine = (_fs.read_json(fields, {}) or {}).get("fields") or []
        theirs = (_fs.read_json(dest, {}) or {}).get("fields") or []
        by_name = {f.get("name"): f for f in theirs}
        new = [f for f in mine if f.get("name") not in by_name]
        clash = [
            f.get("name") for f in mine if f.get("name") in by_name and by_name[f.get("name")] != f
        ]

        if not dest.exists():
            out.append(
                Action(
                    project,
                    "fields.json",
                    ADD,
                    "fields.json",
                    "new",
                    str(fields),
                    str(dest),
                    sig=sig,
                )
            )
        elif new:
            detail = f"{len(new)} propert{'ies' if len(new) > 1 else 'y'} added"
            out.append(
                Action(
                    project,
                    "fields.json",
                    UPDATE,
                    "fields.json",
                    detail,
                    str(fields),
                    str(dest),
                    data={"fields": theirs + new},
                    sig=sig,
                )
            )

        if dest.exists() and clash:
            detail = f"defined differently on each side, DEST's kept: {', '.join(map(str, clash))}"
            out.append(
                Action(
                    project,
                    "fields.json",
                    ATTENTION,
                    "fields.json",
                    detail,
                    str(fields),
                    str(dest),
                    True,
                    sig=sig,
                )
            )
        elif dest.exists() and not new:
            out.append(
                Action(
                    project,
                    "fields.json",
                    SAME,
                    "fields.json",
                    "identical",
                    str(fields),
                    str(dest),
                    sig=sig,
                )
            )

    return out


def plan(
    src: str | os.PathLike[str],
    dest: str | os.PathLike[str],
    project: str | None = None,
    include_running: bool = False,
) -> Plan:
    """Work out what merging `src` into `dest` does, without writing anything.

    Args:
        src: The folder to merge from: a root of projects, or a project folder.
        dest: The folder to merge into, of the same kind.
        project: Only this project (its path relative to `src`).
        include_running: Also copy runs that are still logging in `src`.

    Returns:
        The plan. Its actions cover every run, artifact version and project
        file of `src`, including those with nothing to do.

    Raises:
        ValueError: If `src` is not a folder, or `src` and `dest` overlap.
    """
    s, d = Path(src).resolve(), Path(dest).resolve()

    if not s.is_dir():
        raise ValueError(f"{s} is not a folder")

    if s == d or s in d.parents or d in s.parents:
        raise ValueError("SRC and DEST must be separate folders")

    projects = find_projects(s)

    if project is not None:
        projects = [p for p in projects if p == project.strip("/")]

        if not projects:
            raise ValueError(f"no project {project!r} in {s}")

    actions: list[Action] = []
    mapping: dict[str, int] = {}  # "project\0name\0old version" -> new version, for every project

    arts = {}

    for p in projects:  # artifacts first: runs of any project may use a renumbered version
        arts[p], renumber = _plan_artifacts(p, s / p, d / p)

        for (name, v), new in renumber.items():
            mapping[f"{p}\0{name}\0{v}"] = new

    for p in projects:
        sp, dp = s / p, d / p
        runs = _plan_runs(p, sp, dp, include_running, s, mapping)
        actions += runs + arts[p] + _plan_files(p, sp, dp, s.name)

    if mapping:  # copied runs, whichever project their artifacts are in, point at the new numbers
        for a in actions:
            if a.kind == "run" and a.op in (ADD, UPDATE):
                a.data = {**(a.data or {}), "map": mapping}

    out = Plan(str(s), str(d), actions, project, include_running)
    return out


# ---- showing ----

_ORDER = [
    "run",
    "annotations",
    "artifact",
    "collection",
    "report",
    "report-file",
    "view",
    "sweeps.json",
    "fields.json",
]
_TITLES = {"report-file": "report files", "annotations": "annotations"}


def _short(a: Action) -> str:
    """A run's name (`lr1e-3-s4`), or the item's name."""
    return a.name.split(" (", 1)[1][:-1] if a.kind == "run" and " (" in a.name else a.name


def render(p: Plan, verbose: bool = False) -> str:
    """Return the plan as text: per project and kind, every change and every conflict.

    Identical items are counted on one line; with `verbose`, they and the
    copied runs and report files are listed one by one.
    """
    lines = [f"Merging {p.src} into {p.dest}", ""]
    projects = sorted({a.project for a in p.actions})

    for proj in projects:
        lines.append(proj or "(project folder)")

        for kind in _ORDER:
            acts = [a for a in p.actions if a.project == proj and a.kind == kind]

            if not acts:
                continue

            title = _TITLES.get(kind, kind + ("s" if not kind.endswith(".json") else ""))
            rows = []

            for op in (ADD, UPDATE, ATTENTION, SAME):
                group = [a for a in acts if a.op == op]

                if not group:
                    continue

                summarise = (
                    not verbose
                    and (op == SAME or (op == ADD and kind in ("run", "report-file")))
                    and len(group) > 3
                )

                if summarise:
                    what = {ADD: "to copy", SAME: "nothing to do"}[op]
                    names = ", ".join(_short(a) for a in group[:3])
                    rows.append((op, f"{len(group)} {what}", f"{names}, ... (list with -v)"))
                else:
                    rows += [(op, a.name, a.detail) for a in group]

            for i, (op, name, detail) in enumerate(rows):
                head = title if i == 0 else ""
                lines.append(f"  {head:<13}{op} {name:<34} {detail}")

        lines.append("")

    runs = sum(1 for a in p.changes if a.kind == "run")
    arts = sum(1 for a in p.changes if a.kind == "artifact")
    files = sum(1 for a in p.changes if a.kind not in ("run", "artifact"))
    lines.append(f"Total: {runs} run(s), {arts} artifact version(s) and {files} file(s) to write.")
    renamed = [a for a in p.actions if a.op == ATTENTION and not a.conflict]

    if p.conflicts or renamed:
        lines.append(
            f"{len(p.conflicts)} conflict(s) skipped and {len(renamed)} renamed or renumbered "
            "item(s) need your attention (see ! above)."
        )

    return "\n".join(lines)


# ---- applying ----


def _signature(p: Plan) -> list[Any]:
    """What `apply` compares to make sure the folders did not change since the plan."""
    return [(a.project, a.kind, a.op, a.name, a.detail, a.dest, a.sig) for a in p.actions]


class StalePlan(RuntimeError):
    """SRC or DEST changed after the plan was made."""


def _repoint(
    meta: dict[str, Any],
    run_project: str,
    src_root: Path,
    project_dir: Path,
    mapping: dict[str, int],
) -> bool:
    """Rewrite a copied run's `inputs` and `outputs` to renumbered artifact versions."""
    changed = False

    for ref in [*(meta.get("inputs") or []), *(meta.get("outputs") or [])]:
        if not isinstance(ref, dict) or "artifact" not in ref:
            continue

        home = run_project

        if ref.get("project_path"):
            target = (project_dir / str(ref["project_path"])).resolve()

            try:
                home = target.relative_to(src_root).as_posix()
            except ValueError:
                continue

            home = "" if home == "." else home

        new = mapping.get(f"{home}\0{ref['artifact']}\0{ref.get('version')}")

        if new is not None:
            ref["version"] = new
            changed = True

    return changed


def apply(p: Plan) -> list[Action]:
    """Carry out a plan made by `plan`.

    The plan is made again first; if anything differs (a run finished, a file
    was edited), nothing is written.

    Args:
        p: The plan to apply.

    Returns:
        The actions that wrote something.

    Raises:
        StalePlan: If SRC or DEST changed since the plan was made.
    """
    again = plan(p.src, p.dest, p.project, p.include_running)

    if _signature(again) != _signature(p):
        raise StalePlan("SRC or DEST changed since the plan was made; run the merge again")

    src_root, dest_root = Path(p.src), Path(p.dest)
    done = []

    for a in p.changes:
        dest = Path(a.dest) if a.dest else None
        src = Path(a.src) if a.src else None

        if dest is None or src is None:
            continue

        project_dir = dest_root / a.project
        tmp = project_dir / TMP
        tmp.mkdir(parents=True, exist_ok=True)

        if a.kind == "run":
            staged = tmp / src.name
            shutil.copytree(src, staged)
            data = a.data or {}

            if data.get("map"):
                meta = _fs.read_json(staged / "run.json", {}) or {}

                if _repoint(meta, a.project, src_root, src_root / a.project, data["map"]):
                    _fs.atomic_write_json(staged / "run.json", meta)

            dest.parent.mkdir(parents=True, exist_ok=True)

            if data.get("replace") and dest.exists():
                keep = project_dir / REPLACED / f"{src.name}-{time.strftime('%Y%m%dT%H%M%S')}"
                keep.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dest, keep)

            os.replace(staged, dest)
        elif a.kind == "artifact":
            staged = tmp / f"{src.parent.name}-{dest.name}"
            shutil.copytree(src, staged)

            if a.data and "version" in a.data:
                manifest = _fs.read_json(staged / "manifest.json", {}) or {}
                manifest["version"] = a.data["version"]
                _fs.atomic_write_json(staged / "manifest.json", manifest)

            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, dest)
        elif a.data is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _fs.atomic_write_json(dest, a.data)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _fs.atomic_write_bytes(dest, src.read_bytes())

        done.append(a)

        try:
            tmp.rmdir()
        except OSError:
            pass

    return done


def main(
    src: str,
    dest: str,
    *,
    project: str | None,
    include_running: bool,
    dry_run: bool,
    yes: bool,
    verbose: bool,
    as_json: bool,
) -> int:
    """Run `merge` from the command line: show the plan, ask, apply.

    Returns:
        The exit code: 0 when done (or nothing to do), 1 for a dry run with
        conflicts, 2 when not confirmed or the plan went stale.
    """

    try:
        p = plan(src, dest, project, include_running)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    print(json.dumps(p.to_json(), indent=2) if as_json else render(p, verbose))

    if dry_run:
        return 1 if p.conflicts else 0

    if not p.changes:
        print("Nothing to merge.")
        return 0

    if not yes:
        import sys

        if not sys.stdin.isatty():
            print("Not a terminal: nothing written. Pass --yes to apply without asking.")
            return 2

        answer = input("Nothing has been written yet. Apply this merge? [y/N] ").strip().lower()

        if answer not in ("y", "yes"):
            print("Nothing written.")
            return 2

    try:
        done = apply(p)
    except StalePlan as exc:
        print(f"error: {exc}")
        return 2

    print(f"Done: {len(done)} item(s) written to {p.dest}.")
    return 0
