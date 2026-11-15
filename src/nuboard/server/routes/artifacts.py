"""Routes for artifacts and disk use."""

from __future__ import annotations

import contextlib
import os
import re
import time
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
)
from starlette.routing import BaseRoute, Route

from ... import _fs
from ..._meta import NAME
from ...artifacts import (
    UNLINKED,
    Artifact,
    add_artifact,
    find_artifact_projects,
    promote_run_path,
    restore_artifact,
    same_as_latest,
    unlink_artifact,
    version_folders,
)
from ...catalog import cache_dir as default_cache_dir
from ..common import (
    JSON,
    send_file,
)
from ..context import Context
from ..data import path_inside
from ..storage import Meter


def routes(ctx: Context) -> list[BaseRoute]:
    """Return the artifacts routes, served with what `ctx` holds."""
    catalog = ctx.catalog
    edit_artifacts = ctx.edit_artifacts
    name_of = ctx.name_of
    artifact_project = ctx.artifact_project
    storage_projects = ctx.storage_projects

    meter = Meter(
        catalog.root,
        storage_projects,
        lambda: [(r["key"], r["name"], catalog.root / r["path"]) for r in catalog.runs()],
        ctx.cache_dir or default_cache_dir(),
    )

    async def storage(request: Request) -> Response:
        """Return the disk use measured last, and the progress of a measurement under way.

        `POST {"action": "start" | "resume" | "stop"}` starts a measurement,
        continues one that paused, or ends it keeping a partial result. Nothing
        is measured otherwise.
        """

        if request.method == "POST":
            body = await request.json()
            action = body.get("action") if isinstance(body, dict) else None

            if action not in ("start", "resume", "stop"):
                return JSON({"error": "action must be start, resume or stop"}, status_code=400)

            getattr(meter, action)()

        return JSON(meter.status())

    # Manifests never change in place, so each is read once: a version with a
    # million files would otherwise be parsed on every load of the Artifacts page.
    summaries: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
    file_lists: dict[Path, tuple[tuple[int, int], list[dict[str, Any]]]] = {}

    def manifest_stamp(vdir: Path) -> tuple[int, int] | None:
        """Return the manifest's modification time and size, or None if it is missing."""

        try:
            st = (vdir / "manifest.json").stat()
        except OSError:
            return None

        return (st.st_mtime_ns, st.st_size)

    def summary_of(vdir: Path) -> dict[str, Any]:
        """Return a version's manifest without its file list, plus `file_count` and `size`."""
        stamp = manifest_stamp(vdir)
        cached = summaries.get(vdir)

        if cached and cached[0] == stamp:
            return cached[1]

        problem = ""

        try:
            manifest = _fs.read_json(vdir / "manifest.json", None)
        except (OSError, ValueError) as exc:  # unreadable, or not UTF-8
            manifest, problem = None, f"manifest.json cannot be read: {exc}"

        if not isinstance(manifest, dict):
            problem = problem or "manifest.json is missing or not valid JSON"
            manifest = {}

        files = manifest.pop("files", None)
        files = [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []
        size = 0

        for f in files:
            with contextlib.suppress(TypeError, ValueError):
                size += int(f.get("size") or 0)

        out = {"manifest": manifest, "file_count": len(files), "size": size, "problem": problem}

        if stamp is not None and not problem:  # a half-written manifest is read again
            summaries[vdir] = (stamp, out)

        return out

    def artifacts(request: Request) -> Response:
        """Return artifact versions with the runs that produced and used them.

        Artifacts are found in every folder under the root that has an
        `artifacts/` folder, including projects without runs, such as a project
        of shared datasets. A run's `inputs` and `outputs` may point at another
        project (`project_path`, relative to the run's project).

        Query parameter `project` limits the list to the artifacts of one project
        and those its runs produced or used. Unlinked versions are listed too,
        with `unlinked: true`.

        Each manifest comes without its file list, which can be huge; `file_count`
        and `size` sum it up, and `/api/artifacts/files` pages through it.
        """
        root = catalog.root.resolve()
        users: dict[tuple[str, str, int], list[str]] = {}
        makers: dict[tuple[str, str, int], list[str]] = {}
        by_id: dict[tuple[str, str], str] = {}
        project_of: dict[str, str] = {}

        for r in catalog.runs():
            by_id[(r["project"], r["id"])] = r["key"]
            project_of[r["key"]] = r["project"]
            run_path = catalog.path_of(r["key"])

            for field, into in (("inputs", users), ("outputs", makers)):
                for ref in r.get(field) or []:
                    project: str | None = r["project"]

                    if ref.get("project_path") and run_path is not None:
                        project = name_of(run_path.parent.parent / ref["project_path"])

                    if project is not None:
                        k = (project, ref.get("artifact"), ref.get("version"))
                        into.setdefault(k, []).append(r["key"])

        out = []
        want = request.query_params.get("project")

        for pdir in find_artifact_projects(root):
            project = name_of(pdir)

            if project is None:
                continue

            listed = sorted(version_folders(pdir), key=lambda v: (v[3], v[0], v[1]))

            for aname, version, vdir, unlinked in listed:
                k = (project, aname, version)
                producer = makers.get(k) or []
                consumers = users.get(k, [])
                summary = summary_of(vdir)
                pid = summary["manifest"].get("producer_run")

                if not producer and pid and (project, pid) in by_id:
                    producer = [by_id[(project, pid)]]

                linked = {project_of.get(key) for key in [*producer, *consumers]}

                if want and want != project and want not in linked:
                    continue

                out.append(
                    {
                        "project": project,
                        "name": aname,
                        "version": version,
                        **summary,
                        "producers": producer,
                        "consumers": consumers,
                        "unlinked": unlinked,
                    }
                )

        return JSON({"artifacts": out})

    def artifact_files(request: Request) -> Response:
        """Return a page of one version's files, in manifest order.

        Query parameters: `project`, `name`, `version`, `unlinked` (1 for an
        unlinked version), `find` (only paths containing it, ignoring case),
        `offset` and `limit` (default 1,000, at most 5,000). Returns `files`,
        `total` (files in the version) and `matched` (files that match `find`).
        """
        q = request.query_params
        pdir = artifact_project(q.get("project") or "")
        name = q.get("name") or ""

        try:
            version = int(q.get("version") or "")
            offset = max(int(q.get("offset") or 0), 0)
            limit = min(max(int(q.get("limit") or 1000), 1), 5000)
        except ValueError:
            return JSON({"error": "version, offset and limit must be numbers"}, status_code=400)

        if pdir is None or not name or name != _fs.sanitize(name, ""):
            return JSON({"error": "unknown project or artifact"}, status_code=400)

        base = pdir / "artifacts" / (UNLINKED if q.get("unlinked") == "1" else "")
        vdir = base / name / f"v{version}"
        stamp = manifest_stamp(vdir)

        if stamp is None:
            return JSON({"error": f"no v{version} of artifact {name!r}"}, status_code=404)

        cached = file_lists.get(vdir)

        if cached and cached[0] == stamp:
            files = cached[1]
        else:
            try:
                manifest = _fs.read_json(vdir / "manifest.json", {})
            except (OSError, ValueError):
                manifest = {}

            listed = manifest.get("files") if isinstance(manifest, dict) else None
            files = [f for f in listed if isinstance(f, dict)] if isinstance(listed, list) else []
            file_lists.clear()  # keep only the version being browsed
            file_lists[vdir] = (stamp, files)

        find = (q.get("find") or "").strip().lower()
        matched = [f for f in files if find in str(f.get("path", "")).lower()] if find else files
        page = matched[offset : offset + limit]
        return JSON({"files": page, "total": len(files), "matched": len(matched)})

    def artifact_raw(request: Request) -> Response:
        """Send one file of an artifact version, as `/api/runs/{key}/raw` sends a run file.

        Query parameters: `project`, `name`, `version`, `unlinked` (1 for an
        unlinked version), `path` (the file's path inside the version, as the
        manifest lists it) and `download` (1 to save it even if it is an image).
        Only files the manifest lists are sent; for a version stored by reference
        they are read from the referenced folder.
        """
        q = request.query_params
        pdir = artifact_project(q.get("project") or "")
        name = q.get("name") or ""

        try:
            version = int(q.get("version") or "")
        except ValueError:
            return PlainTextResponse("version must be a number", 400)

        if pdir is None or not name or name != _fs.sanitize(name, ""):
            return PlainTextResponse("unknown project or artifact", 400)

        base = pdir / "artifacts" / (UNLINKED if q.get("unlinked") == "1" else "")
        vdir = base / name / f"v{version}"

        try:
            manifest = _fs.read_json(vdir / "manifest.json", None)
        except (OSError, ValueError):
            manifest = None

        if not isinstance(manifest, dict):
            return PlainTextResponse("not found", 404)

        art = Artifact(name=name, version=version, path=vdir, manifest=manifest)
        rel = q.get("path") or ""

        if rel not in art:
            return PlainTextResponse("not found", 404)

        target = path_inside(art.files, rel.replace("\\", "/").strip("/"))

        if target is None or not target.is_file():
            return PlainTextResponse("not found", 404)

        return send_file(target, q.get("download") == "1")

    def artifact_source(raw: str) -> tuple[str, Path]:
        """Return what to pass to `add_artifact` for a typed path, and the path it points at.

        `~`, environment variables and absolute paths work as in the CLI; a relative
        path is taken from the served folder.
        """
        expanded = os.path.expanduser(os.path.expandvars(raw))

        if os.path.isabs(expanded):
            return raw, Path(expanded)

        target = (catalog.root / expanded).resolve()
        return str(target), target

    async def edit_body(request: Request) -> dict[str, Any] | Response:
        """Return the JSON body of an artifact change, or the error response that refuses it."""

        if not edit_artifacts:
            hint = f"start the viewer with `{NAME} up --edit-artifacts` to change artifacts"
            return JSON({"error": hint}, status_code=403)

        if not request.headers.get("content-type", "").startswith("application/json"):
            return PlainTextResponse("expected application/json", 415)

        body = await request.json()
        return body if isinstance(body, dict) else JSON({"error": "expected an object"}, 400)

    async def artifact_check(request: Request) -> Response:
        """Check a path for a new artifact version (JSON body: `path`).

        Returns `resolved` (the absolute path), `exists`, `kind` (`file` or
        `folder`), `files` and `size` (`partial` when the count stopped at 200,000
        files or 3 seconds), or `error`.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        raw = str(body.get("path") or "").strip()

        if not raw:
            return JSON({"error": "enter a path"})

        unset = re.search(r"\$\{?(\w+)", os.path.expandvars(raw))

        if unset:
            return JSON({"error": f"{unset.group(1)} is not set on this machine"})

        _, target = artifact_source(raw)

        def walk() -> dict[str, Any]:
            """Count the files and bytes under `target`, within the limits."""

            if target.is_file():
                return {"kind": "file", "files": 1, "size": target.stat().st_size, "partial": False}

            files = size = 0
            todo = [target]
            deadline = time.monotonic() + 3

            while todo:
                if files >= 200_000 or time.monotonic() > deadline:
                    return {"kind": "folder", "files": files, "size": size, "partial": True}

                try:
                    with os.scandir(todo.pop()) as it:
                        for e in it:
                            if e.is_dir(follow_symlinks=True):
                                todo.append(Path(e.path))
                            elif e.is_file():
                                files += 1
                                size += e.stat().st_size
                except OSError:
                    continue

            return {"kind": "folder", "files": files, "size": size, "partial": False}

        out: dict[str, Any] = {"resolved": str(target), "exists": target.exists()}

        if target.exists():
            out.update(await run_in_threadpool(walk))

        return JSON(out)

    def duplicate(name: str, version: int) -> Response:
        """Refuse a version with the same files as the latest; the form offers to add it anyway."""
        msg = f"these files are the same as {name}:v{version}, the latest version"
        return JSON({"error": msg, "duplicate_of": version}, status_code=409)

    async def artifact_add(request: Request) -> Response:
        """Add an artifact version that references a path on this machine.

        JSON body: `project`, `name`, `path` (as for `artifact_check`), and
        optionally `type`, `description`, `metadata` (an object), `checksum`
        (also hash every file) and `allow_duplicate`. Returns the new version as
        `{project, name, version}`, or a 409 with `duplicate_of` when the files are
        the same as the latest version's and `allow_duplicate` is not set.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        project = str(body.get("project") or "")
        pdir = artifact_project(project)
        name = _fs.sanitize(str(body.get("name") or ""), "")
        raw = str(body.get("path") or "").strip()
        metadata = body.get("metadata") or {}
        kind = body.get("type") or None

        if pdir is None:
            return JSON({"error": f"unknown project {project!r}"}, status_code=400)

        if not name:
            return JSON({"error": "enter a name"}, status_code=400)

        if not raw:
            return JSON({"error": "enter a path"}, status_code=400)

        if not isinstance(metadata, dict) or (kind is not None and not isinstance(kind, str)):
            return JSON({"error": "metadata must be an object and type a string"}, 400)

        src, target = artifact_source(raw)

        if not target.exists():
            return JSON({"error": f"{target} does not exist"}, status_code=400)

        if not body.get("allow_duplicate"):
            dup = await run_in_threadpool(same_as_latest, pdir, name, target)

            if dup is not None:
                return duplicate(name, dup)

        try:
            art = await run_in_threadpool(
                add_artifact,
                pdir,
                name,
                src,
                type=kind,
                metadata=metadata,
                reference=True,
                checksum=bool(body.get("checksum")),
                description=str(body.get("description") or ""),
            )
        except ValueError as exc:
            return JSON({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSON({"error": f"the version could not be added: {exc}"}, status_code=409)

        return JSON({"project": project, "name": art.name, "version": art.version})

    async def artifact_promote(request: Request) -> Response:
        """Add an artifact version from a file or folder of a run, in the run's project.

        JSON body: `run` (run key), `path` (inside the run folder), `name`, `store`
        (`copy`, the default, or `reference`), and optionally `type`,
        `description`, `metadata` (an object), `checksum` and `allow_duplicate`
        (as for `artifact_add`). A reference is stored relative to the project and
        needs a run that is not running. Returns the new version as
        `{project, name, version}`.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        key = str(body.get("run") or "")
        record = catalog.get(key)
        run_dir = catalog.path_of(key) if record else None
        name = _fs.sanitize(str(body.get("name") or ""), "")
        metadata = body.get("metadata") or {}
        kind = body.get("type") or None
        store = body.get("store") or "copy"

        if run_dir is None or record is None:
            return JSON({"error": f"unknown run {key!r}"}, status_code=400)

        if not name:
            return JSON({"error": "enter a name"}, status_code=400)

        if store not in ("copy", "reference"):
            return JSON({"error": "store must be copy or reference"}, status_code=400)

        if not isinstance(metadata, dict) or (kind is not None and not isinstance(kind, str)):
            return JSON({"error": "metadata must be an object and type a string"}, 400)

        rel = str(body.get("path") or "")

        if not body.get("allow_duplicate") and rel:
            target = path_inside(run_dir, rel)

            if target is not None:
                dup = await run_in_threadpool(same_as_latest, run_dir.parent.parent, name, target)

                if dup is not None:
                    return duplicate(name, dup)

        try:
            art = await run_in_threadpool(
                promote_run_path,
                run_dir,
                rel,
                name,
                copy=store == "copy",
                type=kind,
                metadata=metadata,
                checksum=bool(body.get("checksum")),
                description=str(body.get("description") or ""),
            )
        except (ValueError, FileNotFoundError) as exc:
            return JSON({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSON({"error": f"the version could not be added: {exc}"}, status_code=409)

        return JSON({"project": record["project"], "name": art.name, "version": art.version})

    async def artifact_unlink(request: Request) -> Response:
        """Unlink one version (`version`) or every version of an artifact, or restore one.

        JSON body: `project`, `name`, `version` (omit to unlink all) and
        `restore` (true to move that version back). Nothing is deleted.
        """
        body = await edit_body(request)

        if isinstance(body, Response):
            return body

        pdir = artifact_project(str(body.get("project") or ""))
        name = str(body.get("name") or "")
        version = body.get("version")

        if pdir is None or not name or name != _fs.sanitize(name, ""):
            return JSON({"error": "unknown project or artifact"}, status_code=400)

        if version is not None and (not isinstance(version, int) or isinstance(version, bool)):
            return JSON({"error": "version must be a number"}, status_code=400)

        try:
            if body.get("restore"):
                if version is None:
                    return JSON({"error": "name the version to restore"}, status_code=400)

                restore_artifact(pdir, name, version)
                return JSON({"restored": [version]})

            return JSON({"unlinked": unlink_artifact(pdir, name, version)})
        except FileNotFoundError as exc:
            return JSON({"error": str(exc)}, status_code=404)
        except OSError as exc:
            return JSON({"error": f"could not move the version: {exc}"}, status_code=409)

    return [
        Route("/api/storage", storage, methods=["GET", "POST"]),
        Route("/api/artifacts", artifacts),
        Route("/api/artifacts/files", artifact_files),
        Route("/api/artifacts/raw", artifact_raw),
        Route("/api/artifacts/check", artifact_check, methods=["POST"]),
        Route("/api/artifacts/add", artifact_add, methods=["POST"]),
        Route("/api/artifacts/promote", artifact_promote, methods=["POST"]),
        Route("/api/artifacts/unlink", artifact_unlink, methods=["POST"]),
    ]
