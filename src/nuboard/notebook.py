"""Jupyter support: rich display of runs and projects, and the viewer in a cell.

`Run`, `RunHandle` and `Project` show an HTML summary when they are the last
expression of a cell. `nb.show()` starts the viewer in the background and
shows it in the cell. Nothing here imports IPython: notebooks call
`_repr_html_` on their own.
"""

from __future__ import annotations

import asyncio
import html
import os
import socket
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from ._meta import NAME

if TYPE_CHECKING:
    from .analysis import Project, RunHandle
    from .run import Run

# Notebook front ends that may show the viewer in a frame: Jupyter, JupyterLab and
# VS Code on this computer (the viewer itself only listens on loopback)
FRAME_ANCESTORS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "https://localhost:*",
    "https://127.0.0.1:*",
    "vscode-webview:",
)

_MAX_ROWS = 12  # config keys and scalars shown in a run's summary
_MAX_RUNS = 20  # runs listed in a project's summary
_STYLE = (
    "font:13px/1.45 system-ui,sans-serif;max-width:56em;"
    "border:1px solid rgba(127,127,127,.35);border-radius:8px;padding:10px 14px"
)
_TABLE = "border-collapse:collapse;margin:4px 0 2px;font-variant-numeric:tabular-nums"
_CELL = "text-align:left;padding:1px 14px 1px 0;border:0;vertical-align:top"
_MUTED = "opacity:.65"


# -- formatting ---------------------------------------------------------------
def _value(v: Any) -> str:
    """Format one config or scalar value, short."""

    if isinstance(v, bool) or v is None:
        text = str(v)
    elif isinstance(v, float):
        text = f"{v:.6g}"
    else:
        text = str(v)

    return html.escape(text) if len(text) <= 60 else html.escape(text[:57]) + "&hellip;"


def _flatten(d: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts with dotted keys."""
    out: dict[str, Any] = {}

    for k, v in d.items():
        if isinstance(v, Mapping) and v:
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v

    return out


def _rows(pairs: list[tuple[str, str]], total: int, noun: str) -> str:
    """A two-column table, with a note when rows were left out."""
    body = "".join(
        f'<tr><td style="{_CELL};{_MUTED}">{html.escape(k)}</td><td style="{_CELL}">{v}</td></tr>'
        for k, v in pairs
    )
    more = (
        f'<div style="{_MUTED}">and {total - len(pairs)} more {noun}</div>'
        if total > len(pairs)
        else ""
    )
    return f'<table style="{_TABLE}">{body}</table>{more}'


def _section(title: str, content: str) -> str:
    """A small heading and its content."""
    return f'<div style="margin-top:8px"><b>{html.escape(title)}</b>{content}</div>'


def run_html(
    *,
    run_id: str,
    name: str | None,
    project: str,
    status: str,
    path: Path | str,
    config: Mapping[str, Any],
    summary: Mapping[str, Mapping[str, Any]],
) -> str:
    """The HTML summary of one run: name, status, folder, config and last values."""
    title = html.escape(name or run_id)
    head = (
        f"<div><b>{title}</b> <span style='{_MUTED}'>{html.escape(run_id)} &middot; "
        f"{html.escape(project)} &middot; {html.escape(status)}</span></div>"
        f"<div style='{_MUTED};font-size:12px'>{html.escape(str(path))}</div>"
    )
    parts = [head]
    flat = _flatten(config)

    if flat:
        pairs = [(k, _value(v)) for k, v in list(flat.items())[:_MAX_ROWS]]
        parts.append(_section("Config", _rows(pairs, len(flat), "keys")))

    if summary:
        pairs = []

        for key, s in list(sorted(summary.items()))[:_MAX_ROWS]:
            last = _value(s.get("last"))
            step = s.get("step")
            low, high = s.get("min"), s.get("max")
            extra = f" at step {step}" if step is not None else ""

            if low is not None and high is not None and low != high:
                extra += f" &middot; min {_value(low)} &middot; max {_value(high)}"

            pairs.append((key, f"{last}<span style='{_MUTED}'>{extra}</span>"))

        parts.append(_section("Scalars", _rows(pairs, len(summary), "scalars")))

    return f'<div style="{_STYLE}">{"".join(parts)}</div>'


def live_run_html(run: Run) -> str:
    """The summary of a run being written in this process."""

    if not run.id:
        return f"<div style='{_STYLE}'>A {NAME} run that this rank does not write.</div>"

    status = "finished" if run.finished else "running"
    return run_html(
        run_id=run.id,
        name=run._meta.get("name"),
        project=run.project,
        status=status,
        path=run.path,
        config=run.config,
        summary=run.summary or run._meta.get("summary") or {},
    )


def handle_html(h: RunHandle) -> str:
    """The summary of a run read from disk."""
    r = h.record
    return run_html(
        run_id=h.id,
        name=r.get("name"),
        project=r.get("project") or "",
        status=r.get("status") or "",
        path=h.path,
        config=h.config or {},
        summary=h.summary or {},
    )


def project_html(p: Project) -> str:
    """The summary of a project: its folder, run count and newest runs."""
    runs = sorted(p.runs(), key=lambda h: h.record.get("started") or 0, reverse=True)
    head = (
        f"<div><b>{html.escape(p.root.name)}</b> <span style='{_MUTED}'>"
        f"{len(runs)} run{'s' if len(runs) != 1 else ''}</span></div>"
        f"<div style='{_MUTED};font-size:12px'>{html.escape(str(p.root))}</div>"
    )

    if not runs:
        return f'<div style="{_STYLE}">{head}</div>'

    th = f"{_CELL};{_MUTED};font-weight:normal"
    rows = "".join(
        f"<tr><td style='{_CELL}'>{html.escape(h.name or h.id)}</td>"
        f"<td style='{_CELL};{_MUTED}'>{html.escape(h.id)}</td>"
        f"<td style='{_CELL}'>{html.escape(h.record.get('status') or '')}</td>"
        f"<td style='{_CELL};{_MUTED}'>{_started(h.record.get('started'))}</td></tr>"
        for h in runs[:_MAX_RUNS]
    )
    table = (
        f"<table style='{_TABLE}'><tr><th style='{th}'>Name</th><th style='{th}'>Id</th>"
        f"<th style='{th}'>Status</th><th style='{th}'>Started</th></tr>{rows}</table>"
    )
    more = (
        f"<div style='{_MUTED}'>and {len(runs) - _MAX_RUNS} older runs</div>"
        if len(runs) > _MAX_RUNS
        else ""
    )
    return f'<div style="{_STYLE}">{head}{table}{more}</div>'


def _started(t: Any) -> str:
    """A start time as local date and time, or empty."""

    if not isinstance(t, (int, float)):
        return ""

    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


# -- the viewer in a cell -----------------------------------------------------
class Viewer:
    """A viewer started by `show`, displayed as a frame in a notebook cell.

    Attributes:
        url: The address of the page shown, which also opens in a browser tab.
        root: The folder the viewer serves.
    """

    def __init__(self, server: _Server, url: str, height: int) -> None:
        self._server = server
        self.url = url
        self.root = server.root
        self.height = height

    def _repr_html_(self) -> str:
        """The frame, and a link to open the page in a tab."""
        url = html.escape(self.url, quote=True)
        return (
            f'<div style="font:12px system-ui,sans-serif;{_MUTED};margin-bottom:4px">'
            f"{NAME} viewer of {html.escape(str(self.root))} &middot; "
            f'<a href="{url}" target="_blank" rel="noopener">open in a new tab</a></div>'
            f'<iframe src="{url}" title="{NAME} viewer" width="100%" height="{self.height}" '
            'style="border:1px solid rgba(127,127,127,.35);border-radius:6px" '
            'allow="fullscreen; clipboard-write"></iframe>'
        )

    def __repr__(self) -> str:
        """The address, for consoles that do not show HTML."""
        return f"<{NAME} viewer of {self.root} at {self.url}>"

    def stop(self) -> None:
        """Stop the viewer serving this folder (other cells showing it stop working)."""
        self._server.stop()


class _Server:
    """A viewer running on a background thread, on a free loopback port."""

    def __init__(self, root: Path, frame_ancestors: Sequence[str]) -> None:
        import uvicorn

        from .server import create_app

        self.root = root
        self.ancestors = tuple(frame_ancestors)
        app = create_app(
            root,
            allowed_hosts=["127.0.0.1", "localhost"],
            local_only=True,
            frame_ancestors=frame_ancestors,
        )
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1)
        self._uvicorn = uvicorn.Server(config)
        app.state.stopping = lambda: self._uvicorn.should_exit
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._uvicorn.serve(sockets=[self._sock])),
            name=f"{NAME}-viewer",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + 15

        while not self._uvicorn.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"the {NAME} viewer did not start")

            time.sleep(0.02)

    @property
    def alive(self) -> bool:
        """True while the server thread runs."""
        return self._thread.is_alive() and not self._uvicorn.should_exit

    def stop(self) -> None:
        """Ask the server to stop, and wait a little for it."""
        self._uvicorn.should_exit = True
        self._thread.join(timeout=5)
        _servers.pop(self.root, None)


_servers: dict[Path, _Server] = {}
_lock = threading.Lock()


def _target(target: Any, dir: str | os.PathLike[str] | None) -> tuple[Path, dict[str, str]]:
    """The folder to serve for `target` and the page's parameters."""
    from .analysis import Project, RunHandle
    from .run import Run, data_root, project_dir

    if target is None:
        return data_root(dir), {}

    if isinstance(target, Run):
        if not target.id:
            raise ValueError("this rank does not write the run; show it from rank 0")

        return target.project_dir, {"sel": target.path.name}

    if isinstance(target, RunHandle):
        return target.path.parent.parent, {"sel": target.path.name}

    if isinstance(target, Project):
        return target.root, {}

    candidate = Path(target)

    if dir is None and candidate.is_dir():
        return candidate, {}

    return project_dir(target, dir), {}


def show(
    target: Any = None,
    *,
    page: str | None = None,
    dir: str | os.PathLike[str] | None = None,
    height: int = 720,
    frame_ancestors: Sequence[str] = (),
) -> Viewer:
    """Show the viewer in a notebook cell.

    Starts the viewer on a free port of this computer, on a background thread,
    the first time a folder is shown, and reuses it after. Live runs update as
    they log. The viewer listens on loopback only, so the notebook's browser
    must run on the same computer (or reach it through a port forward, such as
    VS Code's or `ssh -L`).

    Args:
        target: What to show: a `Run` or `RunHandle` (its chart), a `Project`,
            a project name or a folder. Defaults to every project in `dir`.
        page: The viewer page to open: `"runs"`, `"charts"`, `"media"`,
            `"timeline"`, `"sweeps"` and so on. Defaults to `"charts"` for a run
            and `"runs"` otherwise.
        dir: Root folder of the projects (default `$NUBOARD_DIR` or `./experiments`).
        height: Height of the frame, in pixels.
        frame_ancestors: More origins allowed to frame the viewer, for a
            notebook front end not on `localhost`, such as
            `"https://notebooks.example.com"`.

    Returns:
        A `Viewer`, shown as the frame when it is the cell's last expression.
        `Viewer.url` opens the same page in a browser tab.

    Raises:
        FileNotFoundError: If the folder to show does not exist.
        ValueError: If `target` is a run this rank does not write.
    """
    root, params = _target(target, dir)
    root = root.expanduser().resolve()

    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")

    ancestors = (*FRAME_ANCESTORS, *frame_ancestors)

    with _lock:
        server = _servers.get(root)

        if server is not None and server.ancestors != ancestors:
            server.stop()  # restarted on the same folder with other allowed origins
            server = None

        if server is not None and not server.alive:
            server = None

        if server is None:
            server = _servers[root] = _Server(root, ancestors)

    page = page or ("charts" if "sel" in params else "runs")
    query = urlencode(params, quote_via=quote, safe=",")
    url = f"http://127.0.0.1:{server.port}/#/{page}{'?' + query if query else ''}"
    return Viewer(server, url, height)
