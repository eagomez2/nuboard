"""The :class:`Run` object returned by :func:`init`."""

from __future__ import annotations

import atexit
import dataclasses
import datetime as _dt
import glob
import hashlib
import os
import re
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from . import _env, _fs
from . import _format as fmt
from ._meta import DEFAULT_ROOT, ENV_PREFIX, FORMAT_VERSION, NAME
from ._writer import Writer
from .artifacts import Artifact, log_artifact, resolve_artifact

_LOG_RE = re.compile(r"^events\.r(\d+)\.s(\d+)\.log$")
_active: list[Run] = []
_hook_installed = False


def project_dir(project: str | os.PathLike[str] | None, dir: str | os.PathLike[str] | None) -> Path:
    """Where a project's folder lives: ``<dir or $NUBOARD_DIR or ./experiments>/<project>``."""
    root = Path(dir or os.environ.get(f"{ENV_PREFIX}_DIR") or DEFAULT_ROOT)
    parts = [
        _fs.sanitize(p, "default") for p in re.split(r"[\\/]+", str(project or "default")) if p
    ]
    return root.joinpath(*parts) if parts else root / "default"


def _config_to_dict(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, Mapping):
        return {
            str(k): _config_to_dict(v) if isinstance(v, Mapping) else v for k, v in config.items()
        }
    if dataclasses.is_dataclass(config) and not isinstance(config, type):
        return dataclasses.asdict(config)
    if type(config).__module__.startswith("omegaconf"):
        from omegaconf import OmegaConf  # type: ignore[import-not-found]

        return OmegaConf.to_container(config, resolve=True)  # type: ignore[return-value]
    to_dict = getattr(config, "to_dict", None)
    if callable(to_dict):
        return {str(k): v for k, v in to_dict().items()}  # type: ignore[union-attr]
    if hasattr(config, "__dict__"):  # argparse.Namespace and simple objects
        return {k: v for k, v in vars(config).items() if not k.startswith("_")}
    raise TypeError(
        f"config must be a mapping, dataclass or namespace, not {type(config).__name__}"
    )


def _suffix_from(shared_id: str) -> str:
    digest = hashlib.sha1(shared_id.encode("utf-8")).digest()
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(alphabet[b % len(alphabet)] for b in digest[:6])


def _install_excepthook() -> None:
    global _hook_installed
    if _hook_installed:
        return
    _hook_installed = True
    previous = sys.excepthook

    def hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        text = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
        status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"
        for run in list(_active):
            run.finish(status=status, exit_code=1, error=text)
        previous(exc_type, exc, tb)

    sys.excepthook = hook


class Run:
    """One training run, stored as one self-contained folder.

    Create it with :func:`NAME.init`. All ``log*`` methods are safe to call from
    the training loop: they only append to an in-memory queue that a background
    thread writes out.
    """

    def __init__(
        self,
        project: str | os.PathLike[str] | None = None,
        *,
        name: str | None = None,
        config: Any = None,
        dir: str | os.PathLike[str] | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        group: str | None = None,
        run_id: str | None = None,
        resume: Literal["must", "auto"] | None = None,
        fork_from: tuple[str, int] | None = None,
        all_ranks: bool = False,
        capture_env: bool = True,
        compact: bool = True,
        flush_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
        _started: float | None = None,
    ) -> None:
        self.project_dir = project_dir(project, dir)
        self.project = self.project_dir.name
        self.dist = _env.detect_dist()
        self.all_ranks = all_ranks
        self._compact = compact
        self._flush_interval = flush_interval
        self._heartbeat_interval = heartbeat_interval
        self._writer: Writer | None = None
        self._writer_lock = threading.Lock()
        self._meta_lock = threading.RLock()
        self._next_step = 0
        self._last_step = 0
        self._finished = False
        self.started = _started if _started is not None else time.time()
        runs_dir = self.project_dir / "runs"
        name = _fs.sanitize(name or "run")

        resumed = False
        if run_id is not None:
            self.path = runs_dir / run_id
            if (self.path / "run.json").exists() or (self.dist.rank > 0 and self.path.exists()):
                if resume is None:
                    raise FileExistsError(
                        f"run {run_id!r} already exists; pass resume='must' or 'auto' to continue"
                    )
                resumed = True
            elif resume == "must":
                raise FileNotFoundError(f"cannot resume: no run {run_id!r} in {runs_dir}")
        else:
            new_id = self._new_run_id(runs_dir, name)
            if new_id is None:  # a non-zero rank with no way to find rank 0's folder
                warnings.warn(
                    f"{NAME}: rank {self.dist.rank} cannot find rank 0's run (no initialized "
                    "torch.distributed, TORCHELASTIC_RUN_ID or SLURM_JOB_ID); it will not log",
                    RuntimeWarning,
                    stacklevel=3,
                )
                self.id, self.path, self.session = "", runs_dir, 0
                self.config = _config_to_dict(config)
                self._meta = {}
                self._finished = True  # every log call becomes a no-op
                return
            run_id = new_id
            self.path = runs_dir / run_id
        self.id = run_id

        if self.dist.is_main:
            runs_dir.mkdir(parents=True, exist_ok=True)
            if not resumed:
                _fs.check_case_collision(runs_dir, run_id)
            self.path.mkdir(exist_ok=True)
        elif not self.path.exists():
            self._wait_for_folder()

        self.session = self._next_session()
        self.config = _config_to_dict(config)
        self._meta: dict[str, Any] = {}
        if self.dist.is_main:
            self._write_initial_meta(name, tags, notes, group, resumed, fork_from, capture_env)
        if fork_from is not None and self.dist.is_main:
            self._copy_fork(*fork_from)
        _active.append(self)
        atexit.register(self._atexit)
        _install_excepthook()

    # -- setup ----------------------------------------------------------------
    def _new_run_id(self, runs_dir: Path, name: str) -> str | None:
        stamp = _dt.datetime.fromtimestamp(self.started).strftime("%Y%m%d-%H%M")
        if self.dist.world_size > 1:
            if self.dist.shared_id:
                return f"{stamp}_{name}_{_suffix_from(self.dist.shared_id)}"
            mine = f"{stamp}_{name}_{_fs.random_suffix()}" if self.dist.is_main else None
            shared = _env.broadcast_run_id(mine)
            if shared:
                return shared
            if not self.dist.is_main:
                return None
        return f"{stamp}_{name}_{_fs.random_suffix()}"

    def _wait_for_folder(self, timeout: float = 120.0) -> None:
        """Non-zero ranks wait for rank 0 to create the run folder."""
        suffix = self.id.rsplit("_", 1)[-1]
        name = self.id.split("_", 1)[1].rsplit("_", 1)[0] if "_" in self.id else ""
        deadline = time.monotonic() + timeout
        pattern = str(self.path.parent / f"*_{glob.escape(name)}_{suffix}")
        while time.monotonic() < deadline:
            if self.path.exists():
                return
            matches = glob.glob(pattern)  # rank 0 may have started in a different minute
            if matches:
                self.path = Path(sorted(matches)[-1])
                self.id = self.path.name
                return
            time.sleep(0.5)
        raise TimeoutError(f"rank {self.dist.rank}: rank 0 never created {self.path}")

    def _next_session(self) -> int:
        sessions = [-1]
        if self.path.exists():
            for entry in os.listdir(self.path):
                m = _LOG_RE.match(entry)
                if m and int(m.group(1)) == self.dist.rank:
                    sessions.append(int(m.group(2)))
        return max(sessions) + 1

    def _write_initial_meta(
        self,
        name: str,
        tags: list[str] | None,
        notes: str | None,
        group: str | None,
        resumed: bool,
        fork_from: tuple[str, int] | None,
        capture_env: bool,
    ) -> None:
        files = self.path / "files"
        files.mkdir(exist_ok=True)
        meta = _fs.read_json(self.path / "run.json", {}) if resumed else {}
        if not meta:
            meta = {
                "format_version": FORMAT_VERSION,
                "run_id": self.id,
                "project": self.project,
                "name": name,
                "group": group,
                "tags": list(tags or []),
                "notes": notes or "",
                "created": self.started,
                "config": self.config,
                "sessions": [],
                "summary": {},
                "inputs": [],
                "outputs": [],
                "fork": {"run_id": fork_from[0], "step": int(fork_from[1])} if fork_from else None,
            }
        elif self.config:
            meta["config"] = self.config
        if not self.config:
            self.config = meta.get("config") or {}
        meta["status"] = "running"
        meta["started"] = self.started
        meta["ended"] = None
        meta["heartbeat"] = time.time()
        meta["exit"] = None
        meta["distributed"] = {
            "world_size": self.dist.world_size,
            "shared_id": self.dist.shared_id,
        }
        meta["sessions"].append({"session": self.session, "started": self.started, "ended": None})
        _fs.atomic_write_json(files / "config.json", self.config)
        if capture_env:
            git, diff = _env.git_info()
            meta["git"] = git
            meta["env"] = _env.environment()
            if diff:
                _fs.atomic_write_bytes(files / "git.patch", diff.encode("utf-8"))
            _fs.atomic_write_bytes(files / "requirements.txt", _env.pip_freeze().encode("utf-8"))
            _fs.atomic_write_bytes(files / "command.txt", _env.command_line().encode("utf-8"))
        self._meta = meta
        self._save_meta()

    def _copy_fork(self, parent_id: str, step: int) -> None:
        parent = self.project_dir / "runs" / parent_id
        if not (parent / "run.json").exists():
            raise FileNotFoundError(f"cannot fork: no run {parent_id!r} in {parent.parent}")
        merged: dict[str, list[tuple[int, float, float]]] = {}
        logs = sorted(
            (int(m.group(2)), p)
            for p in parent.iterdir()
            if (m := _LOG_RE.match(p.name)) and int(m.group(1)) == 0
        )
        for _, path in logs:
            per_metric: dict[str, list[tuple[int, float, float]]] = {}
            names: dict[int, str] = {}
            for kind, payload, _ in fmt.iter_frames(path.read_bytes(), len(fmt.MAGIC)):
                if kind == fmt.NAME:
                    mid, mname = fmt.decode_name(payload)
                    names[mid] = mname
                elif kind == fmt.SCALARS:
                    ids, steps, times, values = fmt.decode_scalars_py(payload)
                    for i, s, t, v in zip(ids, steps, times, values):
                        per_metric.setdefault(names[i], []).append((s, t, v))
            for mname, pts in per_metric.items():  # later session wins from its first step
                first = min(p[0] for p in pts)
                kept = [p for p in merged.get(mname, []) if p[0] < first]
                merged[mname] = kept + pts
        points = [
            (mname, s, t, v) for mname, pts in merged.items() for (s, t, v) in pts if s <= step
        ]
        points.sort(key=lambda p: (p[1], p[0]))
        writer = self._ensure_writer()
        if writer is not None:
            writer.write_points(points)
        self._next_step = self._last_step = step + 1 if points else 0

    def _save_meta(self) -> None:
        if not self.dist.is_main:
            return
        with self._meta_lock:
            if self._writer is not None:
                self._meta["summary"] = self._writer.summary()
            _fs.atomic_write_json(self.path / "run.json", self._meta)

    def _on_heartbeat(self) -> None:
        with self._meta_lock:
            self._meta["heartbeat"] = time.time()
            self._save_meta()

    def _ensure_writer(self) -> Writer | None:
        if self._writer is None:
            with self._writer_lock:
                if self._writer is None and not self._finished:
                    self._writer = Writer(
                        self.path,
                        self.dist.rank,
                        self.session,
                        flush_interval=self._flush_interval,
                        heartbeat_interval=self._heartbeat_interval,
                        on_heartbeat=self._on_heartbeat if self.dist.is_main else None,
                    )
        return self._writer

    # -- logging ----------------------------------------------------------------
    def log(
        self,
        data: Mapping[str, Any],
        step: int | None = None,
        *,
        time: float | None = None,
        all_ranks: bool | None = None,
    ) -> None:
        """Log a dict of scalars. Non-blocking: values are converted off-thread.

        ``step`` defaults to one more than the previous call. Nested dicts are
        flattened with ``/``. On ranks other than 0 the call is a no-op unless
        ``all_ranks=True`` (here or in :func:`init`).
        """
        if step is None:
            step = self._next_step
        self._last_step = step
        if step >= self._next_step:
            self._next_step = step + 1
        if not self.dist.is_main and not (self.all_ranks if all_ranks is None else all_ranks):
            return
        writer = self._writer or self._ensure_writer()
        if writer is not None:
            writer.queue.append((0, step, _now() if time is None else time, dict(data)))

    def log_text(
        self, key: str, text: str, step: int | None = None, *, all_ranks: bool = False
    ) -> None:
        """Log a string (generated samples, notes) at ``step``."""
        if not self.dist.is_main and not all_ranks:
            return
        writer = self._ensure_writer()
        if writer is not None:
            writer.put_text(key, self._step(step), _now(), str(text))

    def log_image(
        self,
        key: str,
        image: Any,
        step: int | None = None,
        *,
        caption: str | None = None,
    ) -> None:
        """Log an image: PNG/JPEG bytes, a path, a PIL image or an HxW[xC] array."""
        from ._media import image_bytes

        if hasattr(image, "detach"):
            image = image.detach().cpu()
        if hasattr(image, "copy") and not isinstance(image, (bytes, str)):
            image = image.copy()  # the caller may mutate its buffer after we return
        self._put_media(
            key, step, lambda: image_bytes(image), {"kind": "image", "caption": caption}
        )

    def log_audio(
        self,
        key: str,
        audio: Any,
        step: int | None = None,
        *,
        sample_rate: int | None = None,
        caption: str | None = None,
    ) -> None:
        """Log audio: a file path (wav, flac, mp3, ogg, opus, m4a), encoded bytes,
        or a (samples,) / (channels, samples) array with ``sample_rate``.

        Arrays are stored as 16-bit WAV; files and bytes are stored as they are.
        """
        from ._media import audio_bytes

        if hasattr(audio, "detach"):
            audio = audio.detach().cpu()
        if hasattr(audio, "copy") and not isinstance(audio, (bytes, str)):
            audio = audio.copy()  # the caller may mutate its buffer after we return
        self._put_media(
            key,
            step,
            lambda: audio_bytes(audio, sample_rate),
            {"kind": "audio", "caption": caption},
        )

    def log_figure(self, key: str, figure: Any, step: int | None = None) -> None:
        """Log a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure."""
        from ._media import figure_bytes

        data, mime = figure_bytes(figure)  # serialize now: figures are mutable
        self._put_media(key, step, lambda: (data, mime), {"kind": "figure"})

    def log_html(self, key: str, html: str, step: int | None = None) -> None:
        """Log an HTML document; the viewer renders it in a sandboxed iframe."""
        data = html.encode("utf-8")
        self._put_media(key, step, lambda: (data, "text/html"), {"kind": "html"})

    def _put_media(self, key: str, step: int | None, producer: Any, meta: dict[str, Any]) -> None:
        if not self.dist.is_main:
            return
        writer = self._ensure_writer()
        if writer is not None:
            writer.put_media(key, self._step(step), _now(), producer, meta)

    def _step(self, step: int | None) -> int:
        return self._last_step if step is None else step

    # -- artifacts ----------------------------------------------------------------
    def log_artifact(
        self,
        name: str,
        path: str | os.PathLike[str],
        *,
        type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Copy a file or folder into ``artifacts/<name>/v<N>/`` with a manifest."""
        art = log_artifact(
            self.project_dir, name, path, type=type, metadata=metadata, run_id=self.id
        )
        with self._meta_lock:
            self._meta.setdefault("outputs", []).append(
                {"artifact": art.name, "version": art.version}
            )
            self._save_meta()
        return art

    def use_artifact(self, ref: str) -> Artifact:
        """Resolve ``"name"``, ``"name:latest"`` or ``"name:v2"`` and record it as an input."""
        art = resolve_artifact(self.project_dir, ref)
        with self._meta_lock:
            self._meta.setdefault("inputs", []).append(
                {"artifact": art.name, "version": art.version}
            )
            self._save_meta()
        return art

    # -- lifecycle ----------------------------------------------------------------
    @property
    def summary(self) -> dict[str, dict[str, Any]]:
        return self._writer.summary() if self._writer else {}

    def flush(self) -> None:
        """Block until everything logged so far is written (rarely needed)."""
        if self._writer is not None:
            self._writer.flush()

    def finish(
        self,
        status: str = "finished",
        *,
        exit_code: int = 0,
        error: str | None = None,
        _ended: float | None = None,
    ) -> None:
        """Flush, close the log and mark the run finished. Safe to call twice."""
        if self._finished:
            return
        self._finished = True
        if self in _active:
            _active.remove(self)
        atexit.unregister(self._atexit)
        if self._writer is not None:
            self._writer.close(status)
        if not self.dist.is_main:
            return
        with self._meta_lock:
            now = time.time() if _ended is None else _ended
            self._meta["status"] = status
            self._meta["ended"] = now
            self._meta["heartbeat"] = now
            self._meta["exit"] = {"code": exit_code, "error": error}
            if self._meta.get("sessions"):
                self._meta["sessions"][-1]["ended"] = now
            self._save_meta()
        if self._compact and self.dist.world_size == 1 and status != "running":
            try:
                from .compact import compact_run
            except ImportError:
                return  # PyArrow/NumPy not installed: the viewer reads the log directly
            try:
                compact_run(self.path)
            except Exception as exc:  # pragma: no cover
                warnings.warn(f"{NAME}: compaction failed, logs are intact: {exc!r}", stacklevel=2)

    def _atexit(self) -> None:
        self.finish()

    def __enter__(self) -> Run:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if exc_type is None:
            self.finish()
        else:
            text = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
            status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"
            self.finish(status=status, exit_code=1, error=text)

    def __repr__(self) -> str:
        return f"<{NAME}.Run {self.id} at {self.path}>"


_now = time.time


def init(
    project: str | os.PathLike[str] | None = None,
    *,
    name: str | None = None,
    config: Any = None,
    dir: str | os.PathLike[str] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    group: str | None = None,
    run_id: str | None = None,
    resume: Literal["must", "auto"] | None = None,
    fork_from: tuple[str, int] | None = None,
    all_ranks: bool = False,
    capture_env: bool = True,
    compact: bool = True,
    flush_interval: float = 1.0,
    heartbeat_interval: float = 10.0,
    _started: float | None = None,
) -> Run:
    """Start (or resume) a run in ``<dir>/<project>/runs/<run_id>/``.

    ``dir`` defaults to ``$NUBOARD_DIR`` or ``./experiments``. Records config,
    git commit and diff, installed packages, GPUs, command line and rank.
    Use as a context manager, or call :meth:`Run.finish` (also done at exit).
    """
    return Run(
        project,
        name=name,
        config=config,
        dir=dir,
        tags=tags,
        notes=notes,
        group=group,
        run_id=run_id,
        resume=resume,
        fork_from=fork_from,
        all_ranks=all_ranks,
        capture_env=capture_env,
        compact=compact,
        flush_interval=flush_interval,
        heartbeat_interval=heartbeat_interval,
        _started=_started,
    )
