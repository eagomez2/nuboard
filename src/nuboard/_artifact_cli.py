"""`nuboard artifact`: add, list and show artifact versions from the command line.

`add` takes every value as a flag, or asks for what is missing one field at a
time. Each answer is checked as soon as it is entered, `<` goes back a field,
metadata can be added, edited and deleted, and nothing is written until the
review step is confirmed. With every required flag given, or without a
terminal, it never asks.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import (
    Artifact,
    _expand,
    _versions,
    find_artifact_projects,
    list_artifacts,
    resolve_artifact,
    split_ref,
)
from .run import add_artifact, data_root, project_dir

TYPES = ("dataset", "model", "checkpoint", "report", "other")
"""Artifact types the command accepts."""

STORES = ("copy", "reference")
_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_CASTS = ("str", "int", "float", "bool", "json")
BACK = "<"


class Invalid(ValueError):
    """A value that does not pass its check; the message says why and what to enter."""


# -- checks, shared by flags and prompts ---------------------------------------------


def check_name(text: str) -> str:
    """Return `project/name` cleaned of surrounding space and slashes.

    Raises:
        Invalid: If there is no project, or a part has characters other than
            letters, digits, `.`, `_` and `-`.
    """
    value = text.strip().strip("/")
    parts = value.split("/")

    if len(parts) < 2:
        raise Invalid("give the project too, as in datasets/fineweb-edu")

    for part in parts:
        if not _PART.match(part):
            raise Invalid(
                f"{part!r}: use letters, digits, '.', '_' and '-' (up to 64), "
                "starting with a letter or digit"
            )

    return value


def check_path(text: str) -> str:
    """Return the path as written, after checking that it exists and holds files.

    `~` and environment variables are expanded for the check but kept in the
    returned text, so a reference can keep them.

    Raises:
        Invalid: If the path is empty, does not exist, or is an empty folder.
    """
    value = text.strip()

    if not value:
        raise Invalid("enter the file or folder to add")

    path = _expand(value)

    if not path.exists():
        unset = re.search(r"\$\{?(\w+)", str(path))
        hint = f" ({unset.group(1)} is not set)" if unset else ""
        raise Invalid(f"{value} does not exist{hint}")

    if path.is_dir() and not any(p.is_file() for p in path.rglob("*")):
        raise Invalid(f"{value} has no files")

    return value


def check_store(text: str) -> str:
    """Return `"copy"` or `"reference"`, accepting any prefix such as `r`.

    Raises:
        Invalid: If the text is neither.
    """
    value = text.strip().lower()
    hits = [s for s in STORES if value and s.startswith(value)]

    if len(hits) != 1:
        raise Invalid("enter copy (store a copy) or reference (record where it is)")

    return hits[0]


def check_type(text: str) -> str:
    """Return one of `TYPES`, accepting a unique prefix.

    Raises:
        Invalid: If the text is not one of them.
    """
    value = text.strip().lower()
    hits = [t for t in TYPES if value and t.startswith(value)]

    if len(hits) != 1:
        raise Invalid(f"enter one of {', '.join(TYPES)}")

    return hits[0]


def check_description(text: str) -> str:
    """Return the description, which may not be empty.

    Raises:
        Invalid: If it is empty.
    """
    value = " ".join(text.split())

    if not value:
        raise Invalid("say in a few words what this version is; it is what you will read later")

    return value


def check_yes_no(text: str) -> bool:
    """Return True for yes and False for no (`y`, `yes`, `n`, `no`, `true`, `false`).

    Raises:
        Invalid: If the text is neither.
    """
    value = text.strip().lower()

    if value in ("y", "yes", "true"):
        return True

    if value in ("n", "no", "false"):
        return False

    raise Invalid("enter y or n")


def parse_value(text: str, cast: str | None = None) -> Any:
    """Return a metadata value with its type: given by `cast`, or read from the text.

    Without `cast`, `true`/`false` become booleans, whole numbers ints, other
    numbers floats, and anything else stays text.

    Raises:
        Invalid: If `cast` is unknown or the text cannot be read as it.
    """
    value = text.strip()

    if cast is None:
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        if _INT.match(value):
            return int(value)

        if _FLOAT.match(value):
            return float(value)

        return value

    if cast not in _CASTS:
        raise Invalid(f"unknown type {cast!r}; use one of {', '.join(_CASTS)}")

    try:
        if cast == "str":
            return value

        if cast == "int":
            return int(value)

        if cast == "float":
            return float(value)

        if cast == "bool":
            return check_yes_no(value)

        return json.loads(value)
    except (ValueError, Invalid):
        raise Invalid(f"{value!r} is not a valid {cast}") from None


def parse_meta(item: str) -> tuple[str, Any]:
    """Return `(key, value)` from `key=value` or `key:type=value`.

    Raises:
        Invalid: If there is no `=`, the key has other characters than letters,
            digits, `_`, `.`, `/` and `-`, or the value does not match its type.
    """
    key, sep, value = item.partition("=")

    if not sep:
        raise Invalid("write it as key=value, or key:int=value to set the type")

    key, _, cast = key.strip().partition(":")

    if not _KEY.match(key):
        raise Invalid(f"{key!r}: keys use letters, digits, '_', '.', '/' and '-'")

    return key, parse_value(value, cast or None)


def type_name(value: Any) -> str:
    """Return how a metadata value was read: text, int, float, bool or json."""

    if isinstance(value, bool):
        return "bool"

    if isinstance(value, (int, float)):
        return type(value).__name__

    return "text" if isinstance(value, str) else "json"


def scan(path: str) -> tuple[int, int]:
    """Return `(files, bytes)` under a path, as written (with `~` or variables)."""
    root = _expand(path)

    if root.is_file():
        return 1, root.stat().st_size

    count = size = 0

    for dirpath, _, names in os.walk(root):
        for n in names:
            try:
                size += os.stat(os.path.join(dirpath, n)).st_size
                count += 1
            except OSError:
                continue

    return count, size


def fmt_bytes(n: float) -> str:
    """Return a byte count as `812 GB`, `3.3 KB` and so on."""

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" or n >= 10 else f"{n:.1f} {unit}"

        n /= 1024

    return f"{n:.0f} TB"  # pragma: no cover


# -- the draft and its steps -----------------------------------------------------------


@dataclass
class Draft:
    """The values of a new version, filled from flags and prompts."""

    name: str | None = None
    path: str | None = None
    store: str | None = None
    type: str | None = None
    description: str | None = None
    checksum: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def missing(self) -> list[str]:
        """Return the required fields still empty, in the order they are asked."""
        required = ["name", "path", "store", "type", "description"]
        return [f for f in required if getattr(self, f) is None]


@dataclass
class Step:
    """One field the prompts ask for."""

    key: str
    label: str
    check: Callable[[str], Any]
    hint: str


STEPS = [
    Step("name", "Project/name", check_name, "such as datasets/fineweb-edu"),
    Step("path", "Path", check_path, "the file or folder; ~ and $VARS work"),
    Step("store", "Store", check_store, "copy, or reference to leave the files where they are"),
    Step("type", "Type", check_type, " | ".join(TYPES)),
    Step("description", "Description", check_description, "what this version is"),
    Step("checksum", "Hash every file?", check_yes_no, "y reads all the data once; n is quick"),
]


class Prompter:
    """Ask for the fields of a `Draft` one at a time, with checks, going back and review.

    Args:
        draft: The values given so far; they are the defaults.
        root: The root folder of the projects, for the next version number.
        ask: Reads one answer after showing a prompt (`input`).
        say: Writes one line of output (`print`).
    """

    def __init__(
        self,
        draft: Draft,
        root: Path,
        ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print,
    ) -> None:
        self.draft = draft
        self.root = root
        self.ask = ask
        self.say = say
        self._scanned: dict[str, tuple[int, int]] = {}

    def _steps(self) -> list[str]:
        """Return the step keys for the current draft; checksum only for references."""
        keys = [s.key for s in STEPS if s.key != "checksum" or self.draft.store == "reference"]
        return [*keys, "metadata", "review"]

    def run(self) -> bool:
        """Ask until the draft is reviewed. Returns True to write it, False to quit."""
        steps = self._steps()
        missing = self.draft.missing()
        i = steps.index(missing[0]) if missing else steps.index("review")
        back_to_review = False

        while True:
            steps = self._steps()
            key = steps[min(i, len(steps) - 1)]

            if key == "review":
                choice = self._review(steps)

                if choice in ("write", "quit"):
                    return choice == "write"

                if choice == BACK:
                    i = len(steps) - 2
                else:
                    i, back_to_review = steps.index(choice), True

                continue

            moved = self._metadata() if key == "metadata" else self._field(key)

            if moved == BACK:
                i = max(0, i - 1)
                back_to_review = False
            elif back_to_review:
                i, back_to_review = len(self._steps()) - 1, False
            else:
                i += 1

    def _field(self, key: str) -> str | None:
        """Ask one field until it passes its check; return `BACK` to go back."""
        step = next(s for s in STEPS if s.key == key)
        current = getattr(self.draft, key)
        shown = {True: "y", False: "n"}.get(current, current) if current is not None else None

        if key == "checksum" and shown is None:
            shown = "n"

        if key == "store" and shown is None:
            shown = "copy"

        while True:
            default = f" [{shown}]" if shown else ""
            answer = self.ask(f"{step.label} ({step.hint}){default}: ")

            if answer.strip() == BACK:
                return BACK

            if not answer.strip() and shown:
                answer = str(shown)

            try:
                value = step.check(answer)
            except Invalid as exc:
                self.say(f"  ✗ {exc}")
                continue

            setattr(self.draft, key, value)

            if key == "path":
                files, size = self._scan(value)
                self.say(f"  ✓ {files:,} files, {fmt_bytes(size)}")
            elif key == "name":
                self.say(f"  ✓ will be {value.rpartition('/')[2]}:v{self._next_version()}")

            if key == "store" and value == "copy":
                self.draft.checksum = None

            return None

    def _metadata(self) -> str | None:
        """Edit the metadata list until Enter on an empty line; return `BACK` to go back."""
        self.say("Metadata (optional)")
        self.say(
            "  key=value adds or replaces · 2 key=value edits line 2 · -2 deletes line 2 · "
            "key:int=5 sets the type · < back · Enter when done"
        )

        while True:
            items = list(self.draft.metadata.items())

            for n, (k, v) in enumerate(items, 1):
                self.say(f"  {n}  {k} = {json.dumps(v)}  ({type_name(v)})")

            answer = self.ask("metadata> ").strip()

            if not answer:
                return None

            if answer == BACK:
                return BACK

            try:
                self._edit_metadata(answer, items)
            except Invalid as exc:
                self.say(f"  ✗ {exc}")

    def _edit_metadata(self, answer: str, items: list[tuple[str, Any]]) -> None:
        """Apply one metadata command: add, edit line N or delete line N.

        Raises:
            Invalid: If the line number or the entry is not valid.
        """
        m = re.match(r"^(-?)(\d+)(?:\s+(.*))?$", answer)

        if m is None:
            key, value = parse_meta(answer)
            self.draft.metadata[key] = value
            return

        n = int(m.group(2))

        if not 1 <= n <= len(items):
            raise Invalid(f"there is no line {n}")

        old = items[n - 1][0]

        if m.group(1):
            del self.draft.metadata[old]
            return

        if not m.group(3):
            raise Invalid(f"write the new entry after the number, as in {n} {old}=value")

        key, value = parse_meta(m.group(3))
        rebuilt = {}

        for k, v in items:  # keep the line in place, under its new key
            if k == old:
                rebuilt[key] = value
            elif k != key:
                rebuilt[k] = v

        self.draft.metadata = rebuilt

    def _review(self, steps: list[str]) -> str:
        """Show the draft; return `"write"`, `"quit"`, `BACK` or the step to change."""
        fields = [s for s in steps if s != "review"]
        self.say("")
        self.say("Review")

        for n, key in enumerate(fields, 1):
            self.say(f"  {n}  {key:<12} {self._shown(key)}")

        while True:
            answer = self.ask(
                f"Write it? y = write · 1-{len(fields)} = change · < back · q = quit: "
            )
            answer = answer.strip().lower()

            if answer in ("y", "yes"):
                return "write"

            if answer in ("q", "quit"):
                return "quit"

            if answer == BACK:
                return BACK

            if answer.isdigit() and 1 <= int(answer) <= len(fields):
                return fields[int(answer) - 1]

            self.say(f"  ✗ enter y, a number from 1 to {len(fields)}, < or q")

    def _shown(self, key: str) -> str:
        """Return one field of the draft as shown on the review."""
        d = self.draft

        if key == "name":
            return f"{d.name}  (new version v{self._next_version()})"

        if key == "path" and d.path:
            files, size = self._scan(d.path)
            return f"{d.path}  ({files:,} files, {fmt_bytes(size)})"

        if key == "checksum":
            return "yes" if d.checksum else "no"

        if key == "metadata":
            if not d.metadata:
                return "none"

            return ", ".join(f"{k}={json.dumps(v)} ({type_name(v)})" for k, v in d.metadata.items())

        return str(getattr(d, key))

    def _scan(self, path: str) -> tuple[int, int]:
        """Return `scan(path)`, cached so a large folder is walked once."""

        if path not in self._scanned:
            self._scanned[path] = scan(path)

        return self._scanned[path]

    def _next_version(self) -> int:
        """Return the version number the draft's name would get now."""
        project, name, _ = split_ref(self.draft.name or "")
        adir = project_dir(project, self.root) / "artifacts" / name
        return (_versions(adir) or [0])[-1] + 1


# -- subcommands -------------------------------------------------------------------------


def add_parser(sub: Any, env_prefix: str, default_root: str) -> None:
    """Add `artifact add`, `artifact ls` and `artifact show` to the command line."""
    p = sub.add_parser(
        "artifact",
        help="add, list and show artifact versions",
        description="Add, list and show artifact versions without writing Python.",
    )
    asub = p.add_subparsers(dest="artifact_cmd", required=True)
    root_help = f"root folder for projects (default: ${env_prefix}_DIR or ./{default_root})"

    a = asub.add_parser(
        "add",
        help="add a version; asks for what is missing",
        description="Add a version of an artifact. Every value can be given as a flag; in a "
        "terminal, what is missing is asked for one field at a time, each checked as it is "
        "entered (< goes back), and nothing is written until you confirm the review. "
        "Without a terminal, or with --no-input, missing values are an error.",
    )
    a.add_argument("name", nargs="?", help="project/name, such as datasets/fineweb-edu")
    a.add_argument("path", nargs="?", help="the file or folder")
    store = a.add_mutually_exclusive_group()
    store.add_argument("--ref", action="store_true", help="record where the files are")
    store.add_argument("--copy", action="store_true", help="store a copy of the files")
    a.add_argument("-t", "--type", help=" | ".join(TYPES))
    a.add_argument("-d", "--description", help="what this version is")
    a.add_argument(
        "-m",
        "--meta",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="metadata; repeat for several; KEY:int=VALUE sets the type",
    )
    a.add_argument("--meta-file", help="a JSON object of metadata")
    a.add_argument("--checksum", action="store_true", help="with --ref, also hash every file")
    a.add_argument("--dir", default=None, help=root_help)
    a.add_argument("--dry-run", action="store_true", help="check and show, but write nothing")
    a.add_argument("--no-input", action="store_true", help="never ask; missing values are errors")

    ls = asub.add_parser("ls", help="list artifact versions")
    ls.add_argument("project", nargs="?", help="only this project")
    ls.add_argument("--dir", default=None, help=root_help)

    show = asub.add_parser("show", help="show a version and check its files")
    show.add_argument("ref", help="project/name, project/name:latest or project/name:v2")
    show.add_argument("--dir", default=None, help=root_help)


def main(
    args: argparse.Namespace,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    interactive: bool | None = None,
) -> int:
    """Run an `artifact` subcommand.

    Args:
        args: The parsed command line.
        ask: Reads one answer (`input`); for tests.
        say: Writes one line (`print`); for tests.
        interactive: Whether prompts may be shown. Defaults to whether stdin and
            stdout are terminals.

    Returns:
        The exit code: 0 on success, 1 when nothing was written by choice or a
        version was not found, 2 for invalid or missing values.
    """
    root = data_root(args.dir)

    if args.artifact_cmd == "ls":
        return _ls(root, args.project, say)

    if args.artifact_cmd == "show":
        return _show(root, args.ref, say)

    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

    return _add(args, root, ask, say, bool(interactive) and not args.no_input)


def _from_flags(args: argparse.Namespace) -> tuple[Draft, list[str]]:
    """Return the draft the flags describe and every error found in them."""
    draft = Draft()
    errors = []
    checks = [
        ("name", args.name, check_name),
        ("path", args.path, check_path),
        ("type", args.type, check_type),
        ("description", args.description, check_description),
    ]

    for key, value, check in checks:
        if value is not None:
            try:
                setattr(draft, key, check(value))
            except Invalid as exc:
                errors.append(f"{key}: {exc}")

    draft.store = "reference" if args.ref else "copy" if args.copy else None

    if args.checksum:
        if args.copy:
            errors.append("--checksum: copies are always hashed; use it with --ref")
        else:
            draft.checksum = True

    if args.meta_file:
        try:
            loaded = json.loads(Path(args.meta_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"--meta-file: {exc}")
        else:
            if not isinstance(loaded, dict):
                errors.append("--meta-file: the file must hold a JSON object")
            else:
                for k, v in loaded.items():
                    if _KEY.match(str(k)):
                        draft.metadata[str(k)] = v
                    else:
                        errors.append(f"--meta-file: {k!r} is not a valid key")

    for item in args.meta:
        try:
            k, v = parse_meta(item)
            draft.metadata[k] = v
        except Invalid as exc:
            errors.append(f"--meta {item}: {exc}")

    return draft, errors


def _add(
    args: argparse.Namespace,
    root: Path,
    ask: Callable[[str], str],
    say: Callable[[str], None],
    interactive: bool,
) -> int:
    """Run `artifact add`: check the flags, ask for what is missing, then write."""
    draft, errors = _from_flags(args)

    if errors:
        for e in errors:
            say(f"✗ {e}")

        return 2

    if draft.missing():
        if not interactive:
            flags = {"store": "--ref or --copy", "type": "--type", "description": "--description"}
            names = [flags.get(f, f.upper()) for f in draft.missing()]
            say(f"✗ missing: {', '.join(names)}")
            return 2

        try:
            _readline()
            prompter = Prompter(draft, root, ask, say)

            if not prompter.run():
                say("Nothing written.")
                return 1
        except (EOFError, KeyboardInterrupt):
            say("")
            say("Nothing written.")
            return 1

    if draft.store == "copy":
        draft.checksum = False

    project, name, _ = split_ref(draft.name or "")
    files, size = scan(draft.path or "")

    if args.dry_run:
        say(f"Would add {draft.name} ({draft.store}, {files:,} files, {fmt_bytes(size)})")
        say("Nothing written (--dry-run).")
        return 0

    art = add_artifact(
        project or "",
        name,
        draft.path or "",
        type=draft.type,
        metadata=draft.metadata,
        reference=draft.store == "reference",
        checksum=bool(draft.checksum),
        description=draft.description,
        dir=root,
    )
    say(f"Added {project}/{art.ref} ({draft.store}, {files:,} files, {fmt_bytes(size)})")

    if art.manifest.get("reference"):
        say(f"  path  {art.manifest['reference']}")

    say(f'Use it with: run.use_artifact("{project}/{art.ref}")')
    return 0


def _readline() -> None:
    """Load line editing (arrow keys, history) for the prompts, where Python has it."""

    try:
        import readline  # noqa: F401
    except ImportError:  # pragma: no cover - Windows without pyreadline
        pass


def _ls(root: Path, project: str | None, say: Callable[[str], None]) -> int:
    """List artifact versions, newest first within each name."""
    folders = [project_dir(project, root)] if project else find_artifact_projects(root)
    rows = []

    for folder in folders:
        name = folder.relative_to(root).as_posix() if folder != root else root.name

        for a in list_artifacts(folder):
            rows.append((name, a))

    if not rows:
        say("No artifacts.")
        return 0

    rows.sort(key=lambda r: (r[0], r[1].name, -r[1].version))

    for proj, a in rows:
        m = a.manifest
        size = sum(int(f.get("size") or 0) for f in m.get("files") or [])
        store = "ref " if m.get("reference") else "copy"
        when = _dt.datetime.fromtimestamp(m.get("created") or 0).strftime("%Y-%m-%d")
        ref = f"{proj}/{a.ref}"
        say(
            f"{ref:<36} {m.get('type') or '-':<11} {store} {fmt_bytes(size):>8}  {when}  "
            f"{(m.get('description') or '')[:50]}"
        )

    return 0


def _show(root: Path, ref: str, say: Callable[[str], None]) -> int:
    """Show one version's manifest and whether its files still match."""
    project, _, _ = split_ref(ref)

    try:
        art: Artifact = resolve_artifact(project_dir(project, root), ref)
    except FileNotFoundError as exc:
        say(f"✗ {exc}")
        return 1

    m = art.manifest
    by = m.get("created_by") or {}
    size = sum(int(f.get("size") or 0) for f in m.get("files") or [])
    created = _dt.datetime.fromtimestamp(m.get("created") or 0).strftime("%Y-%m-%d %H:%M")
    say(f"{project or 'default'}/{art.ref}")
    rows = [
        ("type", m.get("type") or "-"),
        ("description", m.get("description") or "-"),
        (
            "stored",
            f"reference to {m['reference']}" if m.get("reference") else f"copy in {art.files}",
        ),
        ("files", f"{len(m.get('files') or []):,}, {fmt_bytes(size)}"),
        ("created", f"{created} by {by.get('user') or '?'}@{by.get('host') or '?'}"),
        ("producer", m.get("producer_run") or "none (added outside a run)"),
    ]

    for k, v in rows:
        say(f"  {k:<12} {v}")

    for k, v in (m.get("metadata") or {}).items():
        say(f"  meta.{k:<7} {json.dumps(v)}")

    problems = art.verify()

    if problems:
        for p in problems[:20]:
            say(f"  ✗ {p}")

        if len(problems) > 20:
            say(f"  ✗ and {len(problems) - 20} more")

        return 1

    say("  ✓ files match the manifest")
    return 0
