"""Safe read-modify-write of a run's `annotations.json`.

Every edit, from the viewer (properties, tags, stars, notes, audio notes) or from
`Run.set_field` in Python, reads the file, changes it and writes it back. Three
rules keep those edits from losing data:

- One lock serializes the edits of this process, so two overlapping saves never
  read the same old file and drop each other's change.
- A file that exists but is not valid JSON is never overwritten: the edit is
  refused, so a broken file cannot turn into one holding only the new value.
- Just before the file is replaced, its stamp is checked again; if another
  process changed it meanwhile, it is read again and the edit applied on top.

Training never writes `annotations.json`. Two processes editing the same run in
the same instant are not fully covered: the check narrows that window but cannot
close it without file locks, which fail or hang on network filesystems.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import _fs

ANNOTATIONS = "annotations.json"

_lock = threading.Lock()


class AnnotationsError(Exception):
    """An edit of `annotations.json` that was refused, with a message for the user."""


class StaleEdit(AnnotationsError):
    """An edit started from values that changed since; `current` holds them as they are now."""

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("changed since it was opened; not saved")
        self.current = current


def _empty(v: Any) -> bool:
    """Return whether `v` means "no value", as a removed property or blank notes do."""
    return v is None or v == "" or v == []


def _same(a: Any, b: Any) -> bool:
    """Compare two annotation values, treating every empty value alike and `True != 1`."""

    if _empty(a) and _empty(b):
        return True

    if isinstance(a, bool) or isinstance(b, bool):
        return a is b

    return a == b


def check_expected(ann: dict[str, Any], expect: Any, logged_notes: str = "") -> None:
    """Refuse an edit whose starting values no longer match the annotations.

    `expect` holds what the editor showed when the edit began: `notes` (the text)
    and `fields` (property name to value, null when unset). Only these keys are
    compared, so other changes made meanwhile never block a save.

    Args:
        ann: The annotations as they are now.
        expect: The expected values; anything but a dict checks nothing.
        logged_notes: The notes from `run.json`, shown while `annotations.json`
            has none.

    Raises:
        StaleEdit: With the current value of every expected key, if any differs.
    """

    if not isinstance(expect, dict):
        return

    current: dict[str, Any] = {}
    stale = False

    if "notes" in expect:
        notes = ann.get("notes") if ann.get("notes") is not None else logged_notes
        current["notes"] = notes
        stale |= not _same(notes, expect["notes"])

    if isinstance(expect.get("fields"), dict):
        stored = ann.get("fields")
        fields: dict[str, Any] = stored if isinstance(stored, dict) else {}
        current["fields"] = {}

        for name, value in expect["fields"].items():
            now = fields.get(str(name))
            current["fields"][str(name)] = now
            stale |= not _same(now, value)

    if stale:
        raise StaleEdit(current)


def update_annotations(
    run_dir: Path,
    change: Callable[[dict[str, Any]], None],
    attempts: int = 5,
) -> dict[str, Any]:
    """Apply `change` to a run's annotations and write them back safely.

    Args:
        run_dir: The run folder.
        change: Changes the annotations in place. It may be called more than once
            (each time on a fresh read), so it must only depend on its argument.
        attempts: How many times to re-read when another process keeps changing
            the file between the read and the write.

    Returns:
        The annotations as written.

    Raises:
        AnnotationsError: If the file is not valid JSON, stays locked by another
            program, or keeps changing; the file is left as it was.
    """
    path = run_dir / ANNOTATIONS

    with _lock:
        for _ in range(attempts):
            before = _stamp(path)
            ann = _read_strict(path, run_dir)
            change(ann)

            if _stamp(path) != before:  # changed by another process: read it again
                continue

            try:
                _fs.atomic_write_json(path, ann)
            except PermissionError as exc:
                raise AnnotationsError(
                    f"{ANNOTATIONS} of {run_dir.name} is locked by another program; "
                    "not saved, try again"
                ) from exc

            return ann

    raise AnnotationsError(f"{ANNOTATIONS} of {run_dir.name} kept changing; not saved, try again")


def _read_strict(path: Path, run_dir: Path) -> dict[str, Any]:
    """Read the annotations, `{}` if there are none; refuse a file that cannot be read."""

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except (ValueError, OSError) as exc:  # bad UTF-8, or unreadable
        raise AnnotationsError(
            f"{ANNOTATIONS} of {run_dir.name} could not be read ({exc}); "
            "not saved, so nothing in it is lost"
        ) from exc

    if not text.strip():  # an empty file holds nothing to lose
        return {}

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AnnotationsError(
            f"{ANNOTATIONS} of {run_dir.name} could not be read ({exc}); "
            "not saved, so nothing in it is lost"
        ) from exc

    if not isinstance(data, dict):
        raise AnnotationsError(
            f"{ANNOTATIONS} of {run_dir.name} does not hold a JSON object; "
            "not saved, so nothing in it is lost"
        )

    return data


def _stamp(path: Path) -> tuple[int, int, int] | None:
    """Return what changes when the file is replaced or rewritten, or None if it is missing."""

    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None

    return st.st_mtime_ns, st.st_size, st.st_ino
