"""The `Run` object returned by `init`."""

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
from .artifacts import Artifact, add_artifact, resolve_artifact

_LOG_RE = re.compile(r"^events\.r(\d+)\.s(\d+)\.log$")
_active: list[Run] = []
_hook_installed = False


def project_dir(project: str | os.PathLike[str] | None, dir: str | os.PathLike[str] | None) -> Path:
    """Return where a project's folder lives.

    The folder is `<dir or $NUBOARD_DIR or ./experiments>/<project>`.

    Args:
        project: Project name. Path separators (`/` or a backslash) nest it in
            sub-folders and each part is sanitized. Defaults to `"default"`.
        dir: Root folder for projects.

    Returns:
        The project's folder (it may not exist yet).
    """
    root = Path(dir or os.environ.get(f"{ENV_PREFIX}_DIR") or DEFAULT_ROOT)
    parts = [
        _fs.sanitize(p, "default") for p in re.split(r"[\\/]+", str(project or "default")) if p
    ]
    return root.joinpath(*parts) if parts else root / "default"


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Convert a mapping, dataclass, OmegaConf config or namespace to a plain dict.

    Raises:
        TypeError: If `config` is none of the supported kinds.
    """

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
    """Derive a 6-character run id suffix from an id shared by every rank."""
    digest = hashlib.sha1(shared_id.encode("utf-8")).digest()
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(alphabet[b % len(alphabet)] for b in digest[:6])


def _install_excepthook() -> None:
    """Install, once, a `sys.excepthook` that marks active runs crashed or killed."""
    global _hook_installed

    if _hook_installed:
        return

    _hook_installed = True
    previous = sys.excepthook

    def hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        """Finish every active run with the traceback, then call the previous hook."""
        text = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
        status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"

        for run in list(_active):
            run.finish(status=status, exit_code=1, error=text)

        previous(exc_type, exc, tb)

    sys.excepthook = hook


class Run:
    """One training run, stored as one self-contained folder.

    Create it with `NAME.init`. `log` and the `add_*` media methods are safe to call
    from the training loop: they only append to an in-memory queue that a
    background thread writes out.

    On a non-zero rank that cannot find rank 0's run (no initialized
    `torch.distributed`, `TORCHELASTIC_RUN_ID` or `SLURM_JOB_ID`), a
    `RuntimeWarning` is issued and every call on the run does nothing.

    Args:
        project: Project name. Path separators (`/` or a backslash) nest projects in
            sub-folders; each part is sanitized. Defaults to `"default"`.
        name: Human-readable run name, also used in the generated run id. Defaults
            to `"run"`.
        config: Hyperparameters: a mapping, a dataclass instance, an OmegaConf
            config, an object with `to_dict()` or a namespace such as
            `argparse.Namespace`. Saved in `run.json` and `files/config.json`. When
            resuming with no config, the stored one is kept.
        dir: Root folder for projects. Defaults to `$NUBOARD_DIR` or `./experiments`.
        tags: Tags shown and searchable in the viewer.
        notes: Free-form notes.
        group: Group name, for runs that belong together (e.g. a sweep).
        run_id: Run id, which is also the run's folder name. Defaults to a new
            `<YYYYmmdd-HHMM>_<name>_<suffix>` id. Every rank of a distributed job
            derives the same id.
        resume: What to do when `run_id` already exists: None raises, `"must"`
            continues it and also requires it to exist, `"auto"` continues it if it
            exists and creates it otherwise. Each continuation starts a new session.
        fork_from: `(parent_run_id, step)`. Copies the parent's rank 0 scalars up
            to and including `step` into the new run, which then continues from
            `step + 1`.
        all_ranks: Log scalars from every rank, not only rank 0.
        capture_env: Record the git commit and diff, installed packages, GPUs,
            host and command line.
        compact: On `finish`, compact a single-process run's logs into Parquet
            (only when PyArrow and NumPy are installed).
        flush_interval: Seconds between writes by the background thread.
        heartbeat_interval: Seconds between heartbeat updates of `run.json`, which
            the viewer uses to spot dead runs.
        _started: Start timestamp override, for tests.

    Attributes:
        id: The run id (the run folder's name).
        path: The run's folder, `<project_dir>/runs/<id>`.
        project: The project's name (last part of its folder).
        project_dir: The project's folder.
        config: The run's config as a plain dict.
        dist: Rank and world size of this process.
        all_ranks: Whether scalars are logged from every rank.
        session: Index of this session; it grows each time the run is resumed.
        started: Start time of this session, as a Unix timestamp.

    Raises:
        FileExistsError: If `run_id` exists and `resume` is None, or if a run folder
            differing only by case exists.
        FileNotFoundError: If `resume="must"` and `run_id` does not exist, or if the
            `fork_from` parent does not exist.
        TimeoutError: If a non-zero rank waits 120 s without rank 0 creating the
            run folder.
        TypeError: If `config` is of an unsupported type.
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
        """Create a run id that every rank agrees on, or None if this rank cannot."""
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
        """Wait, on a non-zero rank, for rank 0 to create the run folder.

        Rank 0 may have started in a different minute, so a folder with the same
        name and suffix but another timestamp is accepted too.

        Raises:
            TimeoutError: If no folder appears within `timeout` seconds.
        """
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
        """Return the next free session index for this rank's event logs."""
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
        """Create or update `run.json` and write the files captured at start."""
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
        """Copy a parent run's rank 0 scalars up to `step` into this run.

        When sessions overlap, a later session wins from its first step on.

        Raises:
            FileNotFoundError: If the parent run does not exist.
        """
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
        """Write `run.json` with the current summary (rank 0 only)."""

        if not self.dist.is_main:
            return

        with self._meta_lock:
            if self._writer is not None:
                self._meta["summary"] = self._writer.summary()

            _fs.atomic_write_json(self.path / "run.json", self._meta)

    def _on_heartbeat(self) -> None:
        """Update the heartbeat time in `run.json`; called by the writer thread."""

        with self._meta_lock:
            self._meta["heartbeat"] = time.time()
            self._save_meta()

    def _ensure_writer(self) -> Writer | None:
        """Start the background writer on first use; None once the run is finished."""

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
        """Log a dict of scalars.

        Non-blocking: values are converted off-thread. On ranks other than 0 the
        call is a no-op unless `all_ranks=True` (here or in `init`).

        Args:
            data: Metric names mapped to scalar values (numbers, NumPy or tensor
                scalars). Nested dicts are flattened with `/`.
            step: Training step. Defaults to one more than the previous call.
            time: Unix timestamp of the values. Defaults to now.
            all_ranks: Overrides the run's `all_ranks` setting for this call.

        Example:
            >>> for step in range(100):
            ...     run.log({"train": {"loss": 0.5, "acc": 0.9}}, step=step)
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

    def add_text(
        self, key: str, text: str, step: int | None = None, *, all_ranks: bool = False
    ) -> None:
        """Log a string, such as generated samples or notes.

        On ranks other than 0 the call is a no-op unless `all_ranks=True`.

        Args:
            key: Name the text is logged under.
            text: The text; other values are converted with `str`.
            step: Training step. Defaults to the step of the latest `log` call.
            all_ranks: Log from every rank, not only rank 0.
        """

        if not self.dist.is_main and not all_ranks:
            return

        writer = self._ensure_writer()

        if writer is not None:
            writer.put_text(key, self._step(step), _now(), str(text))

    def add_image(
        self,
        key: str,
        image: Any,
        step: int | None = None,
        *,
        caption: str | None = None,
    ) -> None:
        """Log an image.

        Tensors are detached and moved to the CPU, and arrays are copied, so the
        caller may reuse its buffer right away; encoding happens on the background
        thread. Only rank 0 logs media.

        Args:
            key: Name the image is logged under.
            image: PNG/JPEG bytes, a file path, a PIL image, or an HxW, HxWxC or
                CxHxW array or tensor (uint8, or float in [0, 1]).
            step: Training step. Defaults to the step of the latest `log` call.
            caption: Optional caption shown in the viewer.

        Example:
            >>> import numpy as np
            >>> run.add_image("samples", np.zeros((64, 64, 3), dtype=np.uint8), step=10)
        """
        from ._media import image_bytes

        if hasattr(image, "detach"):
            image = image.detach().cpu()

        if hasattr(image, "copy") and not isinstance(image, (bytes, str)):
            image = image.copy()  # the caller may mutate its buffer after we return

        self._put_media(
            key, step, lambda: image_bytes(image), {"kind": "image", "caption": caption}
        )

    def add_audio(
        self,
        key: str,
        audio: Any,
        step: int | None = None,
        *,
        sample_rate: int | None = None,
        caption: str | None = None,
    ) -> None:
        """Log audio.

        Arrays are stored as 16-bit WAV; files and bytes are stored as they are.
        Tensors are detached and moved to the CPU, and arrays are copied, so the
        caller may reuse its buffer right away. Only rank 0 logs media.

        Args:
            key: Name the audio is logged under.
            audio: A file path (wav, flac, mp3, ogg, opus, m4a), encoded bytes, or a
                `(samples,)` or `(channels, samples)` array or tensor.
            step: Training step. Defaults to the step of the latest `log` call.
            sample_rate: Sample rate in Hz; required for arrays.
            caption: Optional caption shown in the viewer.
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

    def add_figure(self, key: str, figure: Any, step: int | None = None) -> None:
        """Log a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure.

        The figure is serialized immediately, since figures are mutable. Plotly,
        Vega-Lite and Bokeh figures stay interactive in the viewer; matplotlib
        figures are stored as SVG. Only rank 0 logs media.

        Args:
            key: Name the figure is logged under.
            figure: The figure, or a Plotly or Vega-Lite spec as a dict.
            step: Training step. Defaults to the step of the latest `log` call.

        Raises:
            TypeError: If the figure type is not supported.
        """
        from ._media import figure_bytes

        data, mime = figure_bytes(figure)  # serialize now: figures are mutable
        self._put_media(key, step, lambda: (data, mime), {"kind": "figure"})

    def add_html(self, key: str, html: str, step: int | None = None) -> None:
        """Log an HTML document; the viewer renders it in a sandboxed iframe.

        Only rank 0 logs media.

        Args:
            key: Name the document is logged under.
            html: The HTML source.
            step: Training step. Defaults to the step of the latest `log` call.
        """
        data = html.encode("utf-8")
        self._put_media(key, step, lambda: (data, "text/html"), {"kind": "html"})

    def _put_media(self, key: str, step: int | None, producer: Any, meta: dict[str, Any]) -> None:
        """Queue a media item; `producer` returns its encoded bytes on the writer thread."""

        if not self.dist.is_main:
            return

        writer = self._ensure_writer()

        if writer is not None:
            writer.put_media(key, self._step(step), _now(), producer, meta)

    def _step(self, step: int | None) -> int:
        """Return `step`, or the step of the latest `log` call when it is None."""
        return self._last_step if step is None else step

    # -- artifacts ----------------------------------------------------------------
    def add_artifact(
        self,
        name: str,
        path: str | os.PathLike[str],
        *,
        type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Copy a file or folder into `artifacts/<name>/v<N>/` with a manifest.

        The new version is recorded as an output of this run.

        Args:
            name: Artifact name; it is sanitized to be safe as a folder name.
            path: File or folder to copy.
            type: Optional free-form type, such as `"model"` or `"dataset"`.
            metadata: Optional extra data stored in the manifest.

        Returns:
            The new artifact version.

        Raises:
            FileNotFoundError: If `path` does not exist.
        """
        art = add_artifact(
            self.project_dir, name, path, type=type, metadata=metadata, run_id=self.id
        )

        with self._meta_lock:
            self._meta.setdefault("outputs", []).append(
                {"artifact": art.name, "version": art.version}
            )
            self._save_meta()

        return art

    def use_artifact(self, ref: str) -> Artifact:
        """Resolve an artifact reference and record it as an input of this run.

        Args:
            ref: `"name"` or `"name:latest"` for the newest version, or
                `"name:v2"` for a specific one.

        Returns:
            The resolved artifact version.

        Raises:
            FileNotFoundError: If the artifact or version does not exist.
        """
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
        """Per-metric summary: `last`, `step`, `min`, `max`, `count`, `nonfinite`.

        Empty until something has been logged.
        """
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
        """Flush, close the log and mark the run finished. Safe to call twice.

        Called automatically at interpreter exit and by the context manager. Rank 0
        records the status, exit code and end time in `run.json`. A single-process
        run created with `compact=True` is then compacted into Parquet when PyArrow
        and NumPy are installed; if compaction fails, a warning is issued and the
        logs are left intact.

        Args:
            status: Final status, such as `"finished"`, `"crashed"` or `"killed"`.
            exit_code: Process exit code to record.
            error: Error text (e.g. a traceback) to record.
            _ended: End timestamp override, for tests.
        """

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
        """Finish the run when the interpreter exits."""
        self.finish()

    def __enter__(self) -> Run:
        """Return the run itself."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        """Finish the run, as crashed (or killed on Ctrl-C) if an exception escaped."""

        if exc_type is None:
            self.finish()
        else:
            text = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
            status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"
            self.finish(status=status, exit_code=1, error=text)

    def __repr__(self) -> str:
        """Return a short description with the run id and folder."""
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
    """Start (or resume) a run in `<dir>/<project>/runs/<run_id>/`.

    Records config, git commit and diff, installed packages, GPUs, command line and
    rank. Use as a context manager, or call `Run.finish` (also done at exit).

    Args:
        project: Project name. Path separators (`/` or a backslash) nest projects in
            sub-folders; each part is sanitized. Defaults to `"default"`.
        name: Human-readable run name, also used in the generated run id. Defaults
            to `"run"`.
        config: Hyperparameters: a mapping, a dataclass instance, an OmegaConf
            config, an object with `to_dict()` or a namespace such as
            `argparse.Namespace`. Saved in `run.json` and `files/config.json`. When
            resuming with no config, the stored one is kept.
        dir: Root folder for projects. Defaults to `$NUBOARD_DIR` or `./experiments`.
        tags: Tags shown and searchable in the viewer.
        notes: Free-form notes.
        group: Group name, for runs that belong together (e.g. a sweep).
        run_id: Run id, which is also the run's folder name. Defaults to a new
            `<YYYYmmdd-HHMM>_<name>_<suffix>` id. Every rank of a distributed job
            derives the same id.
        resume: What to do when `run_id` already exists: None raises, `"must"`
            continues it and also requires it to exist, `"auto"` continues it if it
            exists and creates it otherwise. Each continuation starts a new session.
        fork_from: `(parent_run_id, step)`. Copies the parent's rank 0 scalars up
            to and including `step` into the new run, which then continues from
            `step + 1`.
        all_ranks: Log scalars from every rank, not only rank 0.
        capture_env: Record the git commit and diff, installed packages, GPUs,
            host and command line.
        compact: On `finish`, compact a single-process run's logs into Parquet
            (only when PyArrow and NumPy are installed).
        flush_interval: Seconds between writes by the background thread.
        heartbeat_interval: Seconds between heartbeat updates of `run.json`, which
            the viewer uses to spot dead runs.
        _started: Start timestamp override, for tests.

    Returns:
        The new run.

    Raises:
        FileExistsError: If `run_id` exists and `resume` is None, or if a run folder
            differing only by case exists.
        FileNotFoundError: If `resume="must"` and `run_id` does not exist, or if the
            `fork_from` parent does not exist.
        TimeoutError: If a non-zero rank waits 120 s without rank 0 creating the
            run folder.
        TypeError: If `config` is of an unsupported type.

    Example:
        >>> import nuboard as nb
        >>> with nb.init("my-project", name="baseline", config={"lr": 1e-3}) as run:
        ...     run.log({"loss": 0.5}, step=0)
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
