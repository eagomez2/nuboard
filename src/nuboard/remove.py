"""Delete runs from the command line: `NAME rm`.

Runs are picked by a query (the language of `ls` and the viewer) or by id or
name. `plan` finds them without touching anything, `render` lists them with
their sizes, and `apply` deletes them. Each run folder is first moved out of
`runs/` into the project's hidden `.rm-tmp/` folder, then removed, so a run is
either fully listed or gone, never half there. Running runs are skipped unless
asked for, and the artifact versions a run produced are kept.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _fs
from .catalog import find_runs, make_record

TMP = ".rm-tmp"


@dataclass
class Target:
    """One run to delete."""

    project: str
    path: Path
    id: str
    name: str
    status: str
    bytes: int
    outputs: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """The runs a deletion would remove, and the running runs it skips."""

    root: Path
    targets: list[Target] = field(default_factory=list)
    skipped: list[Target] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        """Total size of the runs to delete."""
        return sum(t.bytes for t in self.targets)


def _size(path: Path) -> int:
    """Total size in bytes of the files under `path`, not following symlinks."""
    total = 0

    for d, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass

    return total


def _human(n: float) -> str:
    """`n` bytes as `12.3 MB`."""

    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"

        n /= 1000

    return f"{n:.1f} TB"


def plan(
    root: str | os.PathLike[str],
    query: str = "",
    runs: list[str] | None = None,
    include_running: bool = False,
) -> Plan:
    """Find the runs under `root` matching `query` and/or named in `runs`.

    Args:
        root: A folder of projects, a project, or a single run folder.
        query: Query in the language of `ls`; empty matches every run.
        runs: Run ids or names; a run matches if it is listed here or matches
            the query (when both are given, it must do both).
        include_running: Also delete runs that are still logging.

    Returns:
        The plan. Nothing is written.

    Raises:
        ValueError: If `root` is missing, neither `query` nor `runs` is given,
            or the query is invalid.
    """
    from .jobs import read_meta
    from .query import parse

    base = Path(root).resolve()

    if not base.exists():
        raise ValueError(f"{base} does not exist")

    if not query.strip() and not runs:
        raise ValueError("give a query (-q) or run ids (--run) to choose the runs to delete")

    q = parse(query)
    wanted = set(runs or [])
    seen: set[str] = set()
    p = Plan(base)

    for project, path in find_runs(base):
        meta = read_meta(path) or {}
        ann = _fs.read_json(path / "annotations.json", {}) or {}
        record = make_record(path.name, project, path.name, meta, ann)

        if wanted:
            hits = wanted & {record["id"], record["name"], path.name}

            if not hits:
                continue

            seen |= hits

        if query.strip() and not q.matches(record):
            continue

        outputs = [
            f"{o['artifact']}:v{o.get('version')}"
            for o in record["outputs"]
            if isinstance(o, dict) and "artifact" in o
        ]
        target = Target(
            project,
            path,
            str(record["id"]),
            str(record["name"]),
            record["status"],
            _size(path),
            outputs,
        )

        if record["status"] == "running" and not include_running:
            p.skipped.append(target)
        else:
            p.targets.append(target)

    p.unknown = sorted(wanted - seen)
    return p


def render(p: Plan) -> str:
    """Return the plan as text: every run to delete, the skipped ones and the total."""
    lines = [f"Deleting runs under {p.root}", ""]

    for t in p.targets:
        lines.append(f"  - {t.status:<9} {t.project:<20} {t.id}  {t.name}  ({_human(t.bytes)})")

        if t.outputs:
            lines.append(f"      produced {', '.join(t.outputs)} (the versions are kept)")

    for t in p.skipped:
        lines.append(f"  ! running   {t.project:<20} {t.id}  skipped (pass --include-running)")

    for name in p.unknown:
        lines.append(f"  ? {name}: no such run")

    if p.targets or p.skipped or p.unknown:
        lines.append("")

    lines.append(f"Total: {len(p.targets)} run(s), {_human(p.bytes)}")
    return "\n".join(lines)


def apply(p: Plan) -> list[Target]:
    """Delete the runs of `p`; returns the ones deleted.

    A run already gone is passed over. Each run is moved into its project's
    `.rm-tmp/` folder before it is removed, so a failure part way leaves it
    there rather than half deleted in `runs/`.
    """
    done = []

    for t in p.targets:
        if not t.path.exists():
            continue

        tmp = t.path.parent.parent / TMP
        tmp.mkdir(exist_ok=True)
        moved = tmp / f"{t.path.name}-{time.time_ns()}"
        os.replace(t.path, moved)
        shutil.rmtree(moved)
        done.append(t)

        try:
            tmp.rmdir()
        except OSError:
            pass

    return done


def main(
    root: str,
    *,
    query: str,
    runs: list[str] | None,
    include_running: bool,
    dry_run: bool,
    yes: bool,
) -> int:
    """Run `rm` from the command line: list the runs, ask, delete.

    Returns:
        The exit code: 0 when done (or nothing to delete), 2 on an error or
        when not confirmed.
    """

    try:
        p = plan(root, query, runs, include_running)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    print(render(p))

    if dry_run:
        return 0

    if not p.targets:
        print("Nothing to delete.")
        return 0

    if not yes:
        import sys

        if not sys.stdin.isatty():
            print("Not a terminal: nothing deleted. Pass --yes to delete without asking.")
            return 2

        answer = input("This cannot be undone. Delete these runs? [y/N] ").strip().lower()

        if answer not in ("y", "yes"):
            print("Nothing deleted.")
            return 2

    done = apply(p)
    print(f"Deleted {len(done)} run(s).")
    return 0
