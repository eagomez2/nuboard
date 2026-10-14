"""Command line: `NAME up`, `NAME demo`, `NAME compact`, `NAME ls`."""

from __future__ import annotations

import argparse
import os
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
) -> None:
    """Serve a folder of runs with the web viewer until interrupted.

    When `host` is a loopback address, the app only accepts loopback `Host`
    headers. If `port` is taken, the next free port (up to 19 above it) is used.

    Args:
        directory: Folder holding the runs to view; `~` is expanded.
        host: Interface to listen on.
        port: Preferred port.
        open_browser: Open a browser tab on the viewer URL after about a second.
        before_start: Currently unused.

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
    app = create_app(
        root, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "::1"] if loopback else None
    )
    port = _free_port(host, port)
    url = f"http://{'localhost' if loopback else host}:{port}/"
    runs = len(app.state.store.catalog.runs())
    print(f"{NAME} serving {root.resolve()} ({runs} runs) at {url}  (Ctrl+C to stop)")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main(argv: list[str] | None = None) -> None:
    """Run the command line interface.

    Subcommands: `up` (start the viewer), `demo` (write a demo workspace and
    optionally serve it with a live run), `compact` (write `data.parquet` for
    finished runs), `ls` (list runs, optionally filtered by a query) and
    `version`.

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

    p = sub.add_parser(
        "demo", help="write a demo workspace (and optionally start the viewer with a live run)"
    )
    p.add_argument("dir", nargs="?", default="demo-runs")
    p.add_argument("--up", action="store_true", help="start the viewer and keep a live run logging")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--open", action="store_true")

    p = sub.add_parser("compact", help="write data.parquet for finished runs")
    p.add_argument("dir")
    p.add_argument("--force", action="store_true", help="also compact runs that look still running")

    p = sub.add_parser("ls", help="list runs, optionally filtered by a query")
    p.add_argument("dir", nargs="?", default=None)
    p.add_argument("-q", "--query", default="")

    sub.add_parser("version", help="print the version")

    args = parser.parse_args(argv)

    if args.cmd == "up":
        up(args.dir or _default_dir(), args.host, args.port, args.open)
    elif args.cmd == "demo":
        from .demo import generate, live

        print(f"Writing demo runs to {Path(args.dir).resolve()}")
        t0 = time.perf_counter()
        generate(args.dir)
        print(f"Done in {time.perf_counter() - t0:.1f}s.")

        if args.up:
            stop = threading.Event()
            threading.Thread(target=live, args=(args.dir, stop), daemon=True).start()

            try:
                up(args.dir, port=args.port, open_browser=args.open)
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
        from .query import parse

        root = Path(args.dir or _default_dir())
        records = []

        for project, path in find_runs(root):
            meta = _fs.read_json(path / "run.json", {})
            ann = _fs.read_json(path / "annotations.json", {}) or {}
            records.append(make_record(path.name, project, path.name, meta, ann))

        for r in parse(args.query).apply(records):
            print(f"{r['status']:<9} {r['project']:<20} {r['id']}")
    elif args.cmd == "version":
        from . import __version__

        print(f"{NAME} {__version__}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
