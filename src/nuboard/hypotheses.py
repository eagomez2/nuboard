"""Hypothesis boards: why runs were made and what came of them.

A project can have several boards, one folder each in
`<project>/hypotheses/<board>/` (the first one is usually `main`):

- `board.json` holds the board's optional title and description, the verdict
  and outcome categories, the number shown on run chips and the metrics the
  run panel lists;
- `<id>.json` holds one hypothesis: its title, note, the run that led to it
  and why, the runs that tested it (each with an outcome, a conclusion and a
  star), its verdict, linked reports and where its card sits on the canvas.

Everything is plain JSON written atomically, so a board can be committed to
git, copied with the project, or edited by hand. Reading never fails on a
missing, corrupt or hand-edited file: unknown values fall back to defaults and
files that are not JSON objects are skipped. Runs and reports are referenced by
id and name only, so a deleted run or report simply shows as "not found".

Standard library only.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import _fs

FOLDER = "hypotheses"
BOARD_FILE = "board.json"
#: The board used when none is named.
DEFAULT_BOARD = "main"

#: Colors a category can take: the viewer's series colors and a grey.
COLORS = ("s4", "s5", "s1", "s2", "s3", "s6", "s7", "gray")
#: Icons a verdict can take.
ICONS = ("check", "x", "circle", "star", "question", "pause")
#: Summaries a run chip can show for its metric.
STATS = ("min", "max", "last")
#: Card widths on the board (S, M, L, XL); M is the width cards always had.
WIDTHS = ("s", "m", "l", "xl")
#: Most categories in each list.
MAX_CATEGORIES = 8
#: Most metrics the run panel lists when they are chosen by hand.
MAX_PANEL_METRICS = 50

DEFAULT_VERDICTS: list[dict[str, Any]] = [
    {"id": "supported", "label": "Supported", "color": "s4", "icon": "check"},
    {"id": "rejected", "label": "Rejected", "color": "s5", "icon": "x"},
    {"id": "open", "label": "Open", "color": "s1", "icon": "circle"},
]
DEFAULT_OUTCOMES: list[dict[str, Any]] = [
    {"id": "continued", "label": "Continued", "color": "s4", "dead_end": False},
    {"id": "open", "label": "Open", "color": "s1", "dead_end": False},
    {"id": "dropped", "label": "Dropped", "color": "gray", "dead_end": True},
]

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class HypothesisError(ValueError):
    """A hypothesis or board that cannot be saved as given (bad id, a loop, ...)."""


def _folder(project_dir: str | os.PathLike[str], board: str = DEFAULT_BOARD) -> Path:
    """Return the folder of one board of a project: `hypotheses/<board>/`."""
    return Path(project_dir) / FOLDER / check_board_name(board)


def _text(value: Any, limit: int) -> str:
    """Return `value` as a string cut to `limit` characters ("" for non-strings)."""
    return value[:limit] if isinstance(value, str) else ""


def _finite(value: Any) -> float:
    """Return `value` as a finite float, or 0.0."""

    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0

    return f if math.isfinite(f) else 0.0


def check_board_name(value: Any) -> str:
    """Return `value` if it is a valid board name; raise `HypothesisError` otherwise."""

    if not isinstance(value, str) or not _ID.match(value):
        raise HypothesisError("a board name is 1-64 letters, digits, '-' or '_'")

    return value


def _check_id(value: Any) -> str:
    """Return `value` if it is a valid hypothesis id; raise `HypothesisError` otherwise."""

    if not isinstance(value, str) or not _ID.match(value):
        raise HypothesisError("a hypothesis id is 1-64 letters, digits, '-' or '_'")

    return value


def _categories(raw: Any, defaults: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Clean a list of verdict or outcome categories.

    Ids are kept when valid and unique (else derived from the label), labels
    are cut to 40 characters, unknown colors and icons fall back to the first
    allowed one, and the list is cut to `MAX_CATEGORIES`. An empty or invalid
    list gives the defaults.

    Args:
        raw: The categories as given.
        defaults: Returned (copied) when nothing valid is left.
        kind: `verdict` (with an icon) or `outcome` (with `dead_end`).

    Returns:
        The cleaned categories.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue

        label = _text(c.get("label"), 40).strip() or "Untitled"
        cid = c.get("id")

        if not isinstance(cid, str) or not _ID.match(cid) or cid in seen:
            cid = _fs.sanitize(label.lower(), kind)[:40]

            while cid in seen:
                cid = f"{cid[:33]}-{_fs.random_suffix(4)}"

        seen.add(cid)
        item: dict[str, Any] = {
            "id": cid,
            "label": label,
            "color": c.get("color") if c.get("color") in COLORS else COLORS[len(out) % len(COLORS)],
        }

        if kind == "verdict":
            item["icon"] = c.get("icon") if c.get("icon") in ICONS else "circle"
        else:
            item["dead_end"] = bool(c.get("dead_end"))

        out.append(item)

        if len(out) == MAX_CATEGORIES:
            break

    return out or [dict(d) for d in defaults]


def _card(raw: Any) -> dict[str, Any] | None:
    """Clean the "number on run chips" setting: a metric, a summary and which end ranks first.

    `stat` is `min`, `max` or `last`; `top` (`min` or `max`) says which run of a
    hypothesis is marked as its top one: the lowest or highest number. It
    follows `stat` for `min` and `max`. Older boards had `stat: "best"` and a
    `higher` flag: `best` becomes `max` when `higher`, else `min`,
    and `higher` gives `top`.

    Returns None (no number) when `raw` has no metric name.
    """

    if not isinstance(raw, dict) or not isinstance(raw.get("metric"), str) or not raw["metric"]:
        return None

    legacy = "max" if raw.get("higher") else "min"
    stat = raw.get("stat") if raw.get("stat") in STATS else legacy
    top = raw.get("top") if raw.get("top") in ("min", "max") else legacy

    return {
        "metric": raw["metric"][:200],
        "stat": stat,
        "top": stat if stat != "last" else top,
    }


def _names(raw: Any, limit: int) -> list[str]:
    """Clean a list of metric names: strings only, no blanks or repeats, at most `limit`."""

    out: list[str] = []

    for v in raw if isinstance(raw, list) else []:
        if isinstance(v, str) and v.strip() and v[:200] not in out:
            out.append(v[:200])

        if len(out) == limit:
            break

    return out


def clean_board(raw: Any) -> dict[str, Any]:
    """Return a board with every field present and valid.

    Args:
        raw: The board as read or sent; anything that is not a dict counts as empty.

    Returns:
        `title`, `description`, `verdicts`, `outcomes`, `card` (None when
        run chips show no number), `panel_metrics` (the metrics the run
        panel lists, in order; empty for the default choice) and
        `card_width` (`s`, `m`, `l` or `xl`; `m` by default).
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "title": _text(raw.get("title"), 200).strip(),
        "description": _text(raw.get("description"), 5000).strip(),
        "verdicts": _categories(raw.get("verdicts"), DEFAULT_VERDICTS, "verdict"),
        "outcomes": _categories(raw.get("outcomes"), DEFAULT_OUTCOMES, "outcome"),
        "card": _card(raw.get("card")),
        "panel_metrics": _names(raw.get("panel_metrics"), MAX_PANEL_METRICS),
        "card_width": raw.get("card_width") if raw.get("card_width") in WIDTHS else "m",
    }


def clean_hypothesis(raw: Any, hid: str) -> dict[str, Any]:
    """Return a hypothesis with every field present and valid.

    Unknown verdict or outcome ids are kept as they are: the viewer shows them
    as the first category, and they come back if the category is restored.
    A run listed twice keeps its first entry.

    Args:
        raw: The hypothesis as read or sent.
        hid: Its id (the file name wins over an `id` inside the file).

    Returns:
        The cleaned hypothesis.
    """
    raw = raw if isinstance(raw, dict) else {}
    runs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for r in raw.get("runs") if isinstance(raw.get("runs"), list) else []:
        if isinstance(r, str):
            r = {"id": r}

        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"]:
            continue

        if r["id"] in seen:
            continue

        seen.add(r["id"])
        runs.append(
            {
                "id": r["id"][:200],
                "outcome": _text(r.get("outcome"), 64) or "open",
                "conclusion": _text(r.get("conclusion"), 2000),
                "star": bool(r.get("star")),
            }
        )

    also = []

    for a in raw.get("also") if isinstance(raw.get("also"), list) else []:
        if isinstance(a, dict) and isinstance(a.get("run"), str) and a["run"]:
            also.append({"run": a["run"][:200], "reason": _text(a.get("reason"), 500)})

    position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    folded = raw.get("folded")
    parent = raw.get("parent_run")
    now = time.time()
    return {
        "id": hid,
        "title": _text(raw.get("title"), 300).strip() or "Untitled hypothesis",
        "note": _text(raw.get("note"), 100_000),
        "parent_run": parent[:200] if isinstance(parent, str) and parent else None,
        "reason": _text(raw.get("reason"), 500),
        "show_reason": raw.get("show_reason") is not False,
        "also": also,
        "runs": runs,
        "verdict": _text(raw.get("verdict"), 64) or "open",
        "star": bool(raw.get("star")),
        "reports": [_text(n, 200) for n in raw.get("reports") or [] if isinstance(n, str) and n][
            :50
        ]
        if isinstance(raw.get("reports"), list)
        else [],
        "position": {"dx": _finite(position.get("dx")), "dy": _finite(position.get("dy"))},
        "folded": folded if isinstance(folded, bool) else None,
        "card": _card(raw.get("card")),
        "width": raw.get("width") if raw.get("width") in WIDTHS else None,
        "created": _finite(raw.get("created")) or now,
        "updated": _finite(raw.get("updated")) or now,
    }


def list_boards(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """List a project's boards.

    Args:
        project_dir: The project folder.

    Returns:
        `{"name", "title", "count"}` for each board folder, by name; `count`
        is the number of hypotheses. Folders with invalid names are skipped.
    """
    root = Path(project_dir) / FOLDER
    out = []

    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or not _ID.match(d.name):
                continue

            title = clean_board(_fs.read_json(d / BOARD_FILE, {}))["title"]
            count = sum(1 for p in d.glob("*.json") if p.name != BOARD_FILE and _ID.match(p.stem))
            out.append({"name": d.name, "title": title, "count": count})

    return out


def load_board(project_dir: str | os.PathLike[str], board: str = DEFAULT_BOARD) -> dict[str, Any]:
    """Read one board of a project and its hypotheses.

    Args:
        project_dir: The project folder.
        board: The board name.

    Returns:
        `{"board": ..., "hypotheses": [...]}`, hypotheses oldest first. A
        board that does not exist yet gives the default settings and no
        hypotheses.

    Raises:
        HypothesisError: If the board name is invalid.
    """
    folder = _folder(project_dir, board)
    settings = clean_board(_fs.read_json(folder / BOARD_FILE, {}))
    items = []

    if folder.is_dir():
        for p in sorted(folder.glob("*.json")):
            if p.name == BOARD_FILE or not _ID.match(p.stem):
                continue

            data = _fs.read_json(p, None)

            if isinstance(data, dict):
                items.append(clean_hypothesis(data, p.stem))

    items.sort(key=lambda h: (h["created"], h["id"]))
    return {"board": settings, "hypotheses": items}


def save_board(
    project_dir: str | os.PathLike[str], patch: dict[str, Any], board: str = DEFAULT_BOARD
) -> dict[str, Any]:
    """Create a board, or update its title, description, categories or chip number.

    Only the keys present in `patch` change; the result is cleaned and written
    atomically.

    Args:
        project_dir: The project folder.
        patch: Any of `title`, `description`, `verdicts`, `outcomes`, `card`,
            `panel_metrics`, `card_width`.
        board: The board name; a new name creates the board.

    Returns:
        The board as written.

    Raises:
        HypothesisError: If the board name is invalid.
    """
    path = _folder(project_dir, board) / BOARD_FILE
    current = clean_board(_fs.read_json(path, {}))
    keys = ("title", "description", "verdicts", "outcomes", "card", "panel_metrics", "card_width")
    settings = clean_board({**current, **{k: v for k, v in patch.items() if k in keys}})
    path.parent.mkdir(parents=True, exist_ok=True)
    _fs.atomic_write_json(path, settings)
    return settings


def _owner(hypotheses: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map each run id to the id of the hypothesis that lists it."""
    return {r["id"]: h["id"] for h in hypotheses for r in h["runs"]}


def save_hypothesis(
    project_dir: str | os.PathLike[str], data: dict[str, Any], board: str = DEFAULT_BOARD
) -> dict[str, Any]:
    """Create or replace a hypothesis on a board.

    A run belongs to one hypothesis of a board at a time: listing it here
    removes it from any other hypothesis of the same board (which is
    rewritten). Other boards are not touched, so a run can be on several. A parent run that
    would make a loop (this hypothesis, directly or through its descendants,
    leading to itself) is refused.

    Args:
        project_dir: The project folder.
        data: The hypothesis. Without an `id`, a new one is made.
        board: The board name; a new name creates the board.

    Returns:
        The hypothesis as written.

    Raises:
        HypothesisError: If the id or board name is invalid, or the parent
            would make a loop.
    """
    folder = _folder(project_dir, board)
    hid = _check_id(data["id"]) if data.get("id") else f"h-{_fs.random_suffix(8)}"
    old = _fs.read_json(folder / f"{hid}.json", None)
    item = clean_hypothesis(
        {**data, "created": (old or {}).get("created") if isinstance(old, dict) else None}, hid
    )
    item["updated"] = time.time()
    others = [h for h in load_board(project_dir, board)["hypotheses"] if h["id"] != hid]
    owner = _owner(others)
    mine = {r["id"] for r in item["runs"]}
    seen = {hid}
    run = item["parent_run"]

    while run is not None:
        if run in mine:
            raise HypothesisError(
                "that parent run would make a loop: it comes after this hypothesis"
            )

        parent = next((h for h in others if h["id"] == owner.get(run)), None)

        if parent is None or parent["id"] in seen:
            break

        seen.add(parent["id"])
        run = parent["parent_run"]

    folder.mkdir(parents=True, exist_ok=True)

    for h in others:
        kept = [r for r in h["runs"] if r["id"] not in mine]

        if len(kept) != len(h["runs"]):
            h["runs"] = kept
            h["updated"] = item["updated"]
            _fs.atomic_write_json(folder / f"{h['id']}.json", h)

    _fs.atomic_write_json(folder / f"{hid}.json", item)
    return item


def delete_hypothesis(
    project_dir: str | os.PathLike[str], hid: str, board: str = DEFAULT_BOARD
) -> bool:
    """Delete a hypothesis's file.

    Follow-up hypotheses keep their parent run; with no hypothesis listing it,
    the viewer draws them as starting points.

    Args:
        project_dir: The project folder.
        hid: The hypothesis id.
        board: The board name.

    Returns:
        True if it existed and was deleted.

    Raises:
        HypothesisError: If the id or board name is invalid.
    """
    path = _folder(project_dir, board) / f"{_check_id(hid)}.json"

    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def delete_board(project_dir: str | os.PathLike[str], board: str) -> bool:
    """Delete a board's folder with its hypotheses. Runs and reports are not touched.

    Args:
        project_dir: The project folder.
        board: The board name.

    Returns:
        True if the board existed and was deleted.

    Raises:
        HypothesisError: If the board name is invalid.
    """
    folder = _folder(project_dir, board)

    if not folder.is_dir():
        return False

    shutil.rmtree(folder)
    return True
