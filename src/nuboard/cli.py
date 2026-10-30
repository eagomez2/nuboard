"""Command line: `NAME up`, `demo`, `compact`, `ls`, `artifact`, `merge` and friends."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ._meta import DEFAULT_ROOT, ENV_PREFIX, NAME

DEFAULT_PORT = 6070


def _default_dir() -> str:
    """Return `$<PREFIX>_DIR` if set, else `DEFAULT_ROOT` if it is a folder, else `.`."""
    env = os.environ.get(f"{ENV_PREFIX}_DIR")

    if env:
        return env

    return DEFAULT_ROOT if Path(DEFAULT_ROOT).is_dir() else "."


def _free_port(host: str, port: int) -> int:
    """Return the first port from `port` to `port + 19` that can be bound on `host`.

    Wildcard hosts (`0.0.0.0`, `::`) are probed on `127.0.0.1`. Exits with
    `SystemExit` when none of the 20 ports is free.
    """

    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host if host not in ("0.0.0.0", "::") else "127.0.0.1", candidate))
                return candidate
            except OSError:
                continue

    raise SystemExit(f"no free port in {port}-{port + 19}")


def _need_viewer() -> None:
    """Exit with an install hint if the optional viewer dependencies are missing."""

    try:
        import numpy  # noqa: F401
        import pyarrow  # noqa: F401
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            f"{exc.name} is missing. Install the viewer with: pip install '{NAME}[viewer]'"
        ) from None


def up(
    directory: str,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    open_browser: bool = False,
    before_start: object = None,
    token: str | None = None,
    no_token: bool = False,
    edit_artifacts: bool = False,
    read_only_reports: bool = False,
    max_image_mb: float = 20,
    max_text_mb: float = 5,
    max_audio_mb: float = 50,
) -> None:
    """Serve a folder of runs with the web viewer until interrupted.

    When `host` is a loopback address, the app only accepts loopback `Host`
    headers. Otherwise it needs an access token: `token`, else
    `$NUBOARD_TOKEN`, else a random one, printed in the viewer's link. If `port`
    is taken, the next free port (up to 19 above it) is used.

    Args:
        directory: Folder holding the runs to view; `~` is expanded.
        host: Interface to listen on.
        port: Preferred port.
        open_browser: Open a browser tab on the viewer URL after about a second.
        before_start: Currently unused.
        token: Access token; also used on a loopback address when given.
        no_token: Serve a non-loopback address without a token.
        edit_artifacts: Allow adding, unlinking and restoring artifact versions.
        read_only_reports: Refuse changes to reports, including uploads.
        max_image_mb: Size limit, in MB, of an image uploaded into a report.
        max_text_mb: Size limit, in MB, of a text file uploaded into a report.
        max_audio_mb: Size limit, in MB, of an audio file uploaded into a report.

    Raises:
        SystemExit: If the viewer dependencies are missing, `directory` does not
            exist, or no free port is found.
    """
    _need_viewer()
    import uvicorn

    from .server import create_app

    root = Path(directory).expanduser()

    if not root.exists():
        raise SystemExit(f"{root} does not exist")

    loopback = host in ("127.0.0.1", "localhost", "::1")
    token = token or os.environ.get(f"{ENV_PREFIX}_TOKEN") or None

    if token is None and not loopback and not no_token:
        token = secrets.token_hex(24)

    if no_token:
        token = None

    app = create_app(
        root,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "::1"] if loopback else None,
        token=token,
        edit_artifacts=edit_artifacts,
        read_only_reports=read_only_reports,
        max_image_bytes=int(max_image_mb * 1024 * 1024),
        max_text_bytes=int(max_text_mb * 1024 * 1024),
        max_audio_bytes=int(max_audio_mb * 1024 * 1024),
    )
    port = _free_port(host, port)
    shown = "localhost" if loopback else socket.gethostname() if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    link = f"{url}?token={token}" if token else url
    runs = len(app.state.store.catalog.runs())
    print(f"{NAME} serving {root.resolve()} ({runs} runs) at {link}  (Ctrl+C to stop)")

    if token:
        print("  Open the link above once per browser; it signs the browser in.")
    elif not loopback:
        print("  Warning: no token, so anyone who can reach this address can use the viewer.")

    if edit_artifacts:
        print("  Artifact versions can be added, unlinked and restored from the viewer.")

    if read_only_reports:
        print("  Reports are read-only: they cannot be edited and nothing can be uploaded.")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(link)).start()

    # Open live-update streams end once Ctrl+C sets should_exit; the timeout
    # bounds the wait for any other request still in flight
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=3)
    )
    app.state.stopping = lambda: server.should_exit

    try:
        server.run()
    except KeyboardInterrupt:  # uvicorn re-raises the Ctrl+C once it has shut down
        pass


def _import_tensorboard(
    logdir: str, project: str | None, directory: str | None, tags: list[str] | None
) -> None:
    """Import TensorBoard logs and print one line per run.

    Raises:
        SystemExit: If `logdir` is missing or holds no event files.
    """
    from .tensorboard import import_logdir

    try:
        results = import_logdir(logdir, project, dir=directory, tags=tags)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None

    for r in results:
        if r.skipped:
            print(f"skipped   {r.name} (already imported as {r.run_id})")
            continue

        parts = [f"{r.scalars} scalars", f"{r.media} media"]

        if r.hparams:
            parts.append(f"{r.hparams} hparams")

        if r.ignored:
            parts.append("skipped " + ", ".join(f"{n} {k}" for k, n in sorted(r.ignored.items())))

        print(f"imported  {r.name}: {', '.join(parts)}")

    new = [r for r in results if not r.skipped]

    if new:
        root = new[0].path.parent.parent
        print(f"{len(new)} run(s) imported into {root}. View them with: {NAME} up {root.parent}")


def main(argv: list[str] | None = None) -> None:
    """Run the command line interface.

    Subcommands: `up` (start the viewer), `demo` (write a demo workspace and
    optionally serve it with a live run), `compact` (write `data.parquet` for
    finished runs), `ls` (list runs, optionally filtered by a query),
    `artifact` (add, list and show artifact versions), `merge` (merge one
    folder of projects into another), `import-tensorboard` (import
    TensorBoard logs) and `version`.

    Args:
        argv: Command line arguments without the program name. Defaults to
            `sys.argv[1:]`.
    """
    parser = argparse.ArgumentParser(prog=NAME, description="Local experiment tracker and viewer.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("up", help="start the viewer on a folder of runs")
    p.add_argument(
        "dir",
        nargs="?",
        default=None,
        help=f"folder to view (default: ${ENV_PREFIX}_DIR or ./{DEFAULT_ROOT})",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--open", action="store_true", help="open a browser tab")
    p.add_argument(
        "--token",
        default=None,
        help=f"access token (default: ${ENV_PREFIX}_TOKEN, or a random one when --host is "
        "not local); the printed link signs a browser in",
    )
    p.add_argument(
        "--no-token",
        action="store_true",
        help="serve a non-local --host without a token (anyone who reaches it can use it)",
    )
    p.add_argument(
        "--edit-artifacts",
        action="store_true",
        help="allow adding artifact versions (references to paths here) and unlinking them",
    )
    p.add_argument(
        "--read-only-reports",
        action="store_true",
        help="refuse changes to reports, including image and text uploads (for a shared server)",
    )
    p.add_argument(
        "--max-image-mb",
        type=float,
        default=20,
        help="size limit of an image uploaded into a report (default: 20)",
    )
    p.add_argument(
        "--max-text-mb",
        type=float,
        default=5,
        help="size limit of a text file uploaded into a report (default: 5)",
    )
    p.add_argument(
        "--max-audio-mb",
        type=float,
        default=50,
        help="size limit of an audio file uploaded into a report (default: 50)",
    )

    p = sub.add_parser(
        "demo", help="write a demo workspace (and optionally start the viewer with a live run)"
    )
    p.add_argument("dir", nargs="?", default="demo-runs")
    p.add_argument("--up", action="store_true", help="start the viewer and keep a live run logging")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--open", action="store_true")
    p.add_argument("--edit-artifacts", action="store_true", help="as for up")

    p = sub.add_parser("compact", help="write data.parquet for finished runs")
    p.add_argument("dir")
    p.add_argument("--force", action="store_true", help="also compact runs that look still running")

    p = sub.add_parser("ls", help="list runs, optionally filtered by a query")
    p.add_argument("dir", nargs="?", default=None)
    p.add_argument("-q", "--query", default="")

    p = sub.add_parser(
        "import-tensorboard",
        help="import TensorBoard logs (events.out.tfevents.*) as runs",
        description="Import every folder of TensorBoard event files under LOGDIR as a run. "
        "Scalars, images, audio, text and hyperparameters are kept; histograms and other "
        "plugins are skipped. Runs imported before are left unchanged.",
    )
    p.add_argument("logdir", help="the folder you would pass to tensorboard --logdir")
    p.add_argument("-p", "--project", help="project to import into (default: LOGDIR's name)")
    p.add_argument(
        "--dir",
        default=None,
        help=f"root folder for projects (default: ${ENV_PREFIX}_DIR or ./{DEFAULT_ROOT})",
    )
    p.add_argument(
        "--tag",
        action="append",
        dest="tags",
        help="tag for the imported runs; repeat for several (default: tensorboard)",
    )

    p = sub.add_parser(
        "merge",
        help="merge the projects of one folder into another (shows the plan and asks first)",
        description="Copy into DEST the runs, artifact versions, reports, views, collections and "
        "project settings of SRC that DEST lacks. Projects are matched by their path, so give two "
        "roots or two project folders. The full plan is shown and nothing is written until you "
        "confirm. Nothing is overwritten or deleted.",
    )
    p.add_argument("src", help="folder to merge from")
    p.add_argument("dest", help="folder to merge into")
    p.add_argument("--project", help="only this project (its path inside SRC)")
    p.add_argument("--dry-run", action="store_true", help="show the plan and exit (1 if conflicts)")
    p.add_argument("-y", "--yes", action="store_true", help="apply without asking")
    p.add_argument("-v", "--verbose", action="store_true", help="list every item")
    p.add_argument("--json", action="store_true", help="print the plan as JSON")
    p.add_argument(
        "--include-running", action="store_true", help="also copy runs still logging in SRC"
    )

    from . import _artifact_cli

    _artifact_cli.add_parser(sub, ENV_PREFIX, DEFAULT_ROOT)
    sub.add_parser("version", help="print the version")

    args = parser.parse_args(argv)

    if args.cmd == "merge":
        from . import merge

        raise SystemExit(
            merge.main(
                args.src,
                args.dest,
                project=args.project,
                include_running=args.include_running,
                dry_run=args.dry_run,
                yes=args.yes,
                verbose=args.verbose,
                as_json=args.json,
            )
        )

    if args.cmd == "artifact":
        from . import _artifact_cli

        raise SystemExit(_artifact_cli.main(args))

    if args.cmd == "up":
        up(
            args.dir or _default_dir(),
            args.host,
            args.port,
            args.open,
            token=args.token,
            no_token=args.no_token,
            edit_artifacts=args.edit_artifacts,
            read_only_reports=args.read_only_reports,
            max_image_mb=args.max_image_mb,
            max_text_mb=args.max_text_mb,
            max_audio_mb=args.max_audio_mb,
        )
    elif args.cmd == "demo":
        from .demo import generate, is_demo, live

        where = Path(args.dir).resolve()

        if is_demo(where):  # written before: open it rather than add 31 more runs
            print(f"Opening the demo in {where} (delete the folder for a fresh one)")
        else:
            print(f"Writing demo runs to {where}")
            t0 = time.perf_counter()
            generate(args.dir)
            print(f"Done in {time.perf_counter() - t0:.1f}s.")

        if args.up:
            stop = threading.Event()
            threading.Thread(target=live, args=(args.dir, stop), daemon=True).start()

            try:
                up(
                    args.dir,
                    port=args.port,
                    open_browser=args.open,
                    edit_artifacts=args.edit_artifacts,
                )
            finally:
                stop.set()
        else:
            print(f"View it with: {NAME} up {args.dir}")
    elif args.cmd == "compact":
        _need_viewer()
        from . import _fs
        from .catalog import effective_status, find_runs
        from .compact import compact_run
        from .reader import RunReader

        done = 0

        for _, path in find_runs(Path(args.dir)):
            meta = _fs.read_json(path / "run.json", {})

            if effective_status(meta) == "running" and not args.force:
                continue

            if RunReader(path).parquet is not None:
                continue

            compact_run(path)
            done += 1
            print(f"compacted {path}")

        print(f"{done} run(s) compacted")
    elif args.cmd == "ls":
        from . import _fs
        from .catalog import effective_status, find_runs, make_record
        from .jobs import read_meta
        from .query import parse

        root = Path(args.dir or _default_dir())
        records = []

        for project, path in find_runs(root):
            meta = read_meta(path) or {}
            ann = _fs.read_json(path / "annotations.json", {}) or {}
            records.append(make_record(path.name, project, path.name, meta, ann))

        for r in parse(args.query).apply(records):
            print(f"{r['status']:<9} {r['project']:<20} {r['id']}")
    elif args.cmd == "import-tensorboard":
        _import_tensorboard(args.logdir, args.project, args.dir, args.tags)
    elif args.cmd == "version":
        from . import __version__

        print(f"{NAME} {__version__}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
