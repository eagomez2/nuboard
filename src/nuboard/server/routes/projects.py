"""Routes for project settings: collections, hypotheses, views, queries, fields, pins and more."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
)
from starlette.routing import BaseRoute, Route

from ... import _fs
from ...collection import delete_collection, list_collections, save_collection
from ...directions import DirectionConflict, change_direction, read_directions
from ...hypotheses import (
    DEFAULT_BOARD,
    HypothesisConflict,
    HypothesisError,
    delete_board,
    delete_hypothesis,
    list_boards,
    load_board,
    save_board,
    save_hypothesis,
)
from ...query import QueryError, parse
from ...reports import (
    read_fields,
    report_names,
    save_fields,
)
from ..common import (
    _NO_EXPECT,
    JSON,
    _flat_config,
    _read_only,
)
from ..context import Context
from ..data import path_inside
from ..runfiles import change_pins, read_pins

QUERIES_FILE = "queries.json"
"""Saved queries of the query bar, in the root folder of the workspace."""
MAX_QUERIES = 200
MAX_QUERY = 2000
MAX_QUERY_NAME = 200


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the projects routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    read_only_hypotheses = ctx.read_only_hypotheses
    lock_directions = ctx.lock_directions
    project_dir = ctx.project_dir

    def collections(request: Request) -> Response:
        """Return the saved collections, optionally only those of the `project` query parameter."""
        out = []
        want = request.query_params.get("project")

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            if pdir is not None:
                out += [{**c, "project": p["name"]} for c in list_collections(pdir)]

        return JSON({"collections": out})

    async def collection_save(request: Request) -> Response:
        """Create, update or delete a collection in each project its runs belong to.

        The JSON body holds `name` (required), `add` and `remove` (run keys),
        `project` (also save it there when no run is given), `description` and
        `delete` (delete the collection instead). Returns the saved collections.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        name = str(body.get("name") or "").strip()

        if not name:
            return JSON({"error": "a collection needs a name"}, status_code=400)

        # run keys are grouped by project; each project keeps its own collection file
        per_project: dict[str, tuple[list[str], list[str]]] = {}

        for field, slot in (("add", 0), ("remove", 1)):
            for key in body.get(field) or []:
                record = catalog.get(str(key))

                if record is not None:
                    per_project.setdefault(record["project"], ([], []))[slot].append(record["id"])

        if body.get("project"):
            per_project.setdefault(str(body["project"]), ([], []))

        if not per_project:
            return JSON({"error": "no known runs or project"}, status_code=400)

        saved = []

        for project, (add, remove) in per_project.items():
            pdir = project_dir(project)

            if pdir is None:
                continue

            if body.get("delete"):
                delete_collection(pdir, name)
                continue

            saved.append(
                {
                    **save_collection(
                        pdir, name, add=add, remove=remove, description=body.get("description")
                    ),
                    "project": project,
                }
            )

        return JSON({"collections": saved})

    def hypothesis_boards(request: Request) -> Response:
        """Return the hypothesis boards of every project, or of the `project` query parameter.

        Each entry has `project`, `name`, `title` and `count` (hypotheses).
        """
        want = request.query_params.get("project")
        out = []

        for p in catalog.projects():
            if want and p["name"] != want:
                continue

            pdir = project_dir(p["name"])

            if pdir is not None:
                out += [{"project": p["name"], **b} for b in list_boards(pdir)]

        return JSON({"boards": out})

    def hypotheses(request: Request) -> Response:
        """Return one hypothesis board of a project, with the runs and reports it refers to.

        Query parameters: `project` (required) and `board` (a board name; by
        default the first board, or `main` when there is none yet). `boards`
        lists every board of the project. `runs` maps each run id the
        board mentions to a short record (`key`, `name`, `status`, times,
        `summary`, flattened `config`); ids of runs that are gone are left out,
        so the viewer shows them as "not found". `reports` lists the names of
        the project's reports that exist.
        """
        name = request.query_params.get("project", "")
        pdir = project_dir(name) if name else None

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=404)

        boards = list_boards(pdir)
        board = request.query_params.get("board") or (
            boards[0]["name"] if boards else DEFAULT_BOARD
        )

        try:
            data = load_board(pdir, board)
        except HypothesisError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        wanted = {
            rid
            for h in data["hypotheses"]
            for rid in (
                [r["id"] for r in h["runs"]] + [h["parent_run"]] + [a["run"] for a in h["also"]]
            )
            if rid
        }
        found: dict[str, Any] = {}

        for r in catalog.runs():
            if r["project"] == name and r["id"] in wanted and r["id"] not in found:
                found[r["id"]] = {
                    "key": r["key"],
                    "id": r["id"],
                    "name": r["name"],
                    "status": r["status"],
                    "created": r.get("created"),
                    "started": r.get("started"),
                    "summary": r.get("summary") or {},
                    "config": _flat_config(r.get("config") or {}),
                }

        return JSON(
            {
                "project": name,
                "name": board,
                "boards": boards,
                **data,
                "runs": found,
                "reports": [r["name"] for r in report_names(pdir)],
                "read_only": read_only_hypotheses,
            }
        )

    async def hypothesis_save(request: Request) -> Response:
        """Save or delete a hypothesis, or create, change or delete a board.

        The JSON body holds `project`, `board` (the board name, `main` if
        left out) and one of `hypothesis` (the hypothesis to create or
        replace), `delete` (a hypothesis id to delete), `settings` (fields of
        the board to change; a new board name creates the board) or
        `delete_board: true`. Returns the saved item, or what was deleted.
        A hypothesis can come with `base`, the hypothesis as the editor loaded
        it: a change made meanwhile is merged field by field, and a save that
        changes the same field is refused with a 409 holding `conflict` (the
        fields) and `current` (null if it was deleted), unless `force` is true.
        Refused on a server started with `--read-only-hypotheses`.
        """

        if read_only_hypotheses:
            return _read_only("hypotheses")

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()

        if not isinstance(body, dict):
            return JSON({"error": "expected a JSON object"}, status_code=400)

        pdir = project_dir(str(body.get("project") or ""))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=404)

        board = body.get("board") or DEFAULT_BOARD

        try:
            if isinstance(body.get("hypothesis"), dict):
                base = body.get("base") if isinstance(body.get("base"), dict) else None
                saved = save_hypothesis(
                    pdir, body["hypothesis"], board, base=base, force=body.get("force") is True
                )
                return JSON({"hypothesis": saved})

            if body.get("delete"):
                hid = str(body["delete"])
                return JSON({"deleted": hid, "existed": delete_hypothesis(pdir, hid, board)})

            if isinstance(body.get("settings"), dict):
                return JSON({"board": save_board(pdir, body["settings"], board)})

            if body.get("delete_board") is True:
                return JSON({"deleted_board": board, "existed": delete_board(pdir, board)})
        except HypothesisConflict as exc:
            return JSON(
                {"error": str(exc), "conflict": exc.fields, "current": exc.current},
                status_code=409,
            )
        except HypothesisError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON(
            {"error": "send a hypothesis, settings, an id to delete or delete_board"},
            status_code=400,
        )

    def view_item(request: Request) -> Response:
        """Return a saved view of a project (`GET`) or delete it (`DELETE`).

        Returns the view, or `{"deleted": <name>}`; an unknown view is a 404 error.
        """
        pdir = project_dir(request.path_params["project"])
        target = path_inside(pdir / "views", request.path_params["name"]) if pdir else None

        if target is None or not target.is_file() or target.suffix != ".json":
            return JSON({"error": "no such view"}, status_code=404)

        if request.method == "DELETE":
            target.unlink()
            return JSON({"deleted": target.name})

        return JSON(_fs.read_json(target, {}))

    async def view_save(request: Request) -> Response:
        """Save a view (page and URL parameters) under the project's `views/` folder.

        The JSON body holds `project`, `name` and `state` (`page` and `params`;
        the `cmp` and `tab` parameters are dropped). Returns the saved file name.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        name = _fs.sanitize(str(body.get("name", "view")).removesuffix(".json"), "view") + ".json"
        (pdir / "views").mkdir(exist_ok=True)
        state = body.get("state") or {}
        params = {k: v for k, v in (state.get("params") or {}).items() if k not in ("cmp", "tab")}
        _fs.atomic_write_json(
            pdir / "views" / name, {"page": state.get("page", "charts"), "params": params}
        )
        return JSON({"saved": name})

    queries_file = catalog.root / QUERIES_FILE

    def read_queries() -> list[dict[str, str]]:
        """Return the saved queries of the workspace, skipping malformed entries."""
        got = _fs.read_json(queries_file, {})
        items = got.get("queries") if isinstance(got, dict) else None
        out = []

        for q in items if isinstance(items, list) else []:
            if isinstance(q, dict) and isinstance(q.get("query"), str) and q["query"].strip():
                name = q.get("name")
                out.append(
                    {
                        "name": name if isinstance(name, str) and name.strip() else q["query"],
                        "query": q["query"],
                    }
                )

        return out

    def queries_get(request: Request) -> Response:
        """Return the saved queries of the workspace (`queries.json` in the root folder)."""
        return JSON({"queries": read_queries()})

    async def queries_save(request: Request) -> Response:
        """Add a saved query or delete one, and return the saved queries.

        The JSON body is `{"add": {"name": ..., "query": ...}}` or `{"delete": <query>}`.
        Adding a query that is saved already renames it. A query that does not parse is
        refused, and so are names and queries longer than the limits below.
        """

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        items = read_queries()
        body = body if isinstance(body, dict) else {}
        add = body.get("add")

        if isinstance(add, dict):
            query = str(add.get("query", "")).strip()
            name = str(add.get("name", "")).strip() or query

            if not query:
                return JSON({"error": "the query is empty"}, status_code=400)

            if len(query) > MAX_QUERY or len(name) > MAX_QUERY_NAME:
                return JSON({"error": "the name or the query is too long"}, status_code=400)

            try:
                parse(query)
            except QueryError as exc:
                return JSON({"error": f"not a valid query: {exc}"}, status_code=400)

            items = [q for q in items if q["query"] != query]

            if len(items) >= MAX_QUERIES:
                return JSON({"error": f"at most {MAX_QUERIES} saved queries"}, status_code=400)

            items.append({"name": name, "query": query})
        elif isinstance(body.get("delete"), str):
            items = [q for q in items if q["query"] != body["delete"]]
        else:
            return JSON({"error": "expected add or delete"}, status_code=400)

        _fs.atomic_write_json(queries_file, {"queries": items})
        return JSON({"queries": items})

    def fields_get(request: Request) -> Response:
        """Return the property definitions of the `project` query parameter."""
        pdir = project_dir(request.query_params.get("project", ""))
        return JSON({"fields": read_fields(pdir) if pdir else []})

    async def fields_save(request: Request) -> Response:
        """Replace a project's property definitions (JSON body: `project`, `fields`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        try:
            fields = save_fields(pdir, list(body.get("fields") or []))
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)

        return JSON({"fields": fields})

    def pins_get(request: Request) -> Response:
        """Return the pinned files of the `project` query parameter."""
        pdir = project_dir(request.query_params.get("project", ""))
        return JSON({"pins": read_pins(pdir) if pdir else []})

    async def pins_save(request: Request) -> Response:
        """Pin or unpin one file of a project (JSON body: `project`, and `add` or `remove`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        add = body.get("add")
        remove = body.get("remove")

        try:
            pins = change_pins(
                pdir,
                add=str(add) if add is not None else None,
                remove=str(remove) if remove is not None else None,
            )
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSON({"error": f"pins.json could not be saved: {exc}"}, status_code=409)

        return JSON({"pins": pins})

    def directions_get(request: Request) -> Response:
        """Return the directions set in every project, as `{project: {name: "min" | "max"}}`."""
        out: dict[str, dict[str, str]] = {}

        for p in catalog.projects():
            pdir = project_dir(p["name"])
            directions = read_directions(pdir) if pdir else {}

            if directions:
                out[p["name"]] = directions

        return JSON({"directions": out})

    async def directions_save(request: Request) -> Response:
        """Set or clear one direction of a project.

        JSON body: `project`, `name`, `direction` (`min`, `max` or null) and `expect`, what the
        viewer last saw for it (`min`, `max` or null). When the file says otherwise, someone
        changed it meanwhile: nothing is written and the answer is 409 with the `current` value.
        Refused (403) when the viewer was started with `--read-only-directions`.
        """

        if lock_directions:
            return JSON({"error": "directions are locked on this viewer"}, status_code=403)

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        direction = body.get("direction")
        expect = body.get("expect") if "expect" in body else _NO_EXPECT

        try:
            directions = change_direction(
                pdir,
                str(body.get("name", "")),
                str(direction) if direction is not None else None,
                *(() if expect is _NO_EXPECT else (expect,)),
            )
        except DirectionConflict as exc:
            return JSON({"error": str(exc), "current": exc.current}, status_code=409)
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSON({"error": f"directions.json could not be saved: {exc}"}, status_code=409)

        return JSON({"directions": directions})

    def sweep_settings_get(request: Request) -> Response:
        """Return the Sweeps settings of the `project` query parameter (`<project>/sweeps.json`).

        `hide` is a filter in the syntax of the settings filter (`!seed !.path`):
        parameters it lets through are offered, the others are hidden.
        """
        pdir = project_dir(request.query_params.get("project", ""))
        data = _fs.read_json(pdir / "sweeps.json", {}) if pdir else {}
        hide = data.get("hide") if isinstance(data, dict) else None
        return JSON({"hide": hide if isinstance(hide, str) else ""})

    async def sweep_settings_save(request: Request) -> Response:
        """Save the Sweeps hide rules of a project (JSON body: `project`, `hide`)."""

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        pdir = project_dir(str(body.get("project", "")))

        if pdir is None:
            return JSON({"error": "unknown project"}, status_code=400)

        hide = " ".join(str(body.get("hide") or "").split())

        if len(hide) > 1000:
            return JSON({"error": "hide rules are at most 1000 characters"}, status_code=400)

        try:
            data = _fs.read_json(pdir / "sweeps.json", {}) or {}
            data = {**(data if isinstance(data, dict) else {}), "hide": hide}
            _fs.atomic_write_json(pdir / "sweeps.json", data)
        except OSError as exc:
            return JSON({"error": f"sweeps.json could not be saved: {exc}"}, status_code=409)

        return JSON({"hide": hide})

    return [
        Route("/api/directions", directions_get),
        Route("/api/directions", directions_save, methods=["POST"]),
        Route("/api/sweep-settings", sweep_settings_get),
        Route("/api/sweep-settings", sweep_settings_save, methods=["POST"]),
        Route("/api/collections", collections),
        Route("/api/collections", collection_save, methods=["POST"]),
        Route("/api/hypothesis-boards", hypothesis_boards),
        Route("/api/hypotheses", hypotheses),
        Route("/api/hypotheses", hypothesis_save, methods=["POST"]),
        Route("/api/views", view_save, methods=["POST"]),
        Route("/api/views/{project:path}/{name}", view_item, methods=["GET", "DELETE"]),
        Route("/api/queries", queries_get),
        Route("/api/queries", queries_save, methods=["POST"]),
        Route("/api/fields", fields_get),
        Route("/api/fields", fields_save, methods=["POST"]),
        Route("/api/pins", pins_get),
        Route("/api/pins", pins_save, methods=["POST"]),
    ]
