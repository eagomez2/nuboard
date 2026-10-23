"""The `Run` object returned by `init`."""

from __future__ import annotations

import atexit
import dataclasses
import datetime as _dt
import glob
import hashlib
import math
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from . import _env, _fs
from . import _format as fmt
from ._console import ConsoleLog
from ._meta import DEFAULT_ROOT, ENV_PREFIX, FORMAT_VERSION, NAME
from ._system import SystemMonitor, parse_groups
from ._writer import Writer, _flatten, _to_float
from .artifacts import Artifact, resolve_artifact, split_ref
from .artifacts import add_artifact as _add_artifact
from .catalog import effective_status
from .figures import WaveformFigure
from .jobs import MAIN, job_path, read_jobs

_LOG_RE = re.compile(r"^events\.r(\d+)\.s(\d+)\.log$")
_active: list[Run] = []
_hook_installed = False


def data_root(dir: str | os.PathLike[str] | None) -> Path:
    """Return the root folder of the projects: `dir`, `$NUBOARD_DIR` or `./experiments`."""
    return Path(dir or os.environ.get(f"{ENV_PREFIX}_DIR") or DEFAULT_ROOT)


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
    root = data_root(dir)
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


def _relative_name(name: str) -> PurePosixPath:
    """Return `name` as a safe relative path inside a run's `files/` folder.

    Args:
        name: Relative name; `/` or a backslash separates subfolders.

    Returns:
        The name as a relative path without `.` parts.

    Raises:
        ValueError: If `name` is empty, absolute or contains `..`.
    """
    normalized = name.replace("\\", "/")
    rel = PurePosixPath(normalized)

    if rel.is_absolute() or PureWindowsPath(name).anchor:
        raise ValueError(f"file name must be relative: {name!r}")

    if ".." in rel.parts:
        raise ValueError(f"file name must not contain '..': {name!r}")

    if not rel.parts:
        raise ValueError(f"file name must not be empty: {name!r}")

    return rel


def _copy_atomic(src: Path, dest: Path) -> None:
    """Copy `src` to `dest` via a temporary file next to `dest` and `os.replace`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{_fs.random_suffix(4)}.tmp")

    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _suffix_from(shared_id: str) -> str:
    """Derive a 6-character run id suffix from an id shared by every rank."""
    digest = hashlib.sha1(shared_id.encode("utf-8")).digest()
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(alphabet[b % len(alphabet)] for b in digest[:6])


def _warn_if_changed(art: Artifact) -> None:
    """Warn when an artifact version's files are missing or changed since it was made."""
    problems = art.verify()

    if problems:
        more = f"; and {len(problems) - 5} more" if len(problems) > 5 else ""
        shown = "; ".join(problems[:5]) + more
        warnings.warn(f"artifact {art.ref}: {shown}", stacklevel=3)


def _install_excepthook() -> None:
    """Install, once, a `sys.excepthook` that marks active runs crashed or killed."""
    global _hook_installed

    if _hook_installed:
        return

    _hook_installed = True
    previous = sys.excepthook

    def hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        """Finish every active run with the traceback, then call the previous hook."""
        full = "".join(traceback.format_exception(exc_type, exc, tb))
        text = full[-4000:]
        status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"

        for run in list(_active):
            if run._console is not None:  # the previous hook prints it after the log is closed
                run._console.write(full)

            run.finish(status=status, exit_code=1, error=text)

        previous(exc_type, exc, tb)

    sys.excepthook = hook


def _records(rows: Any) -> list[dict[Any, Any]]:
    """Return a table's rows as dicts, from dicts, a dict of columns or a DataFrame."""

    if hasattr(rows, "to_dict") and hasattr(rows, "columns"):  # pandas DataFrame
        return rows.to_dict(orient="records")

    if isinstance(rows, dict):  # columns
        names = list(rows)
        return [
            dict(zip(names, values, strict=True)) for values in zip(*rows.values(), strict=True)
        ]

    return [dict(r) for r in rows]


def _copied(data: Any) -> Any:
    """Return media data the caller may reuse right away.

    Tensors become NumPy arrays of their own (detached, moved to the CPU, and
    upcast to float32 when NumPy has no matching type, as for bfloat16), so a
    later in-place change to the tensor does not reach the logged item. Arrays
    are copied; anything else is returned as it is.
    """

    if hasattr(data, "detach") and hasattr(data, "numpy"):  # torch tensor
        t = data.detach().cpu()

        if str(t.dtype) == "torch.bfloat16":
            t = t.float()

        return t.numpy().copy()

    if hasattr(data, "copy") and not isinstance(data, (bytes, str)):
        data = data.copy()

    return data


class Run:
    """One training run, stored as one self-contained folder.

    Create it with `NAME.init`. `add_scalar` and the other `add_*` methods are safe to call
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
            `argparse.Namespace`. Saved in `run.json`. When resuming with no config,
            the stored one is kept. To keep a config file as it is (YAML, TOML,
            Hydra's `.hydra/` folder, ...), attach it with `Run.add_file`.
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
        job: Join the existing run `run_id` as a helper job of this name, such as
            `"eval"` for a job that evaluates checkpoints while training goes on.
            It logs into the same run without touching its status, heartbeat or
            summary, which stay the main job's: its own state goes in
            `jobs/<job>.json`, its console in `files/output.<job>.log` and its
            system metrics under `system/<job>/`. None (or `"main"`) is the
            process that creates the run. Restarting a job continues it.
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
        system_metrics: Log CPU, memory and GPU use as `system/` scalars, from
            local rank 0 of each machine. True for all of them, False for none,
            or a list of groups out of `"cpu"`, `"memory"` and `"gpu"`.
        system_interval: Seconds between system samples.
        capture_console: Copy what the script prints to stdout and stderr into
            `files/output.log`, shown in the viewer's run details.
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
        job: Name of this helper job, or None for the main job.
        started: Start time of this session, as a Unix timestamp.

    Raises:
        FileExistsError: If `run_id` exists and `resume` is None, or if a run folder
            differing only by case exists.
        FileNotFoundError: If `resume="must"` and `run_id` does not exist, if the
            `fork_from` parent does not exist, or if `job` is given and run `run_id`
            does not exist.
        RuntimeError: If `job` is already running on this run in another process.
        TimeoutError: If a non-zero rank waits 120 s without rank 0 creating the
            run folder.
        TypeError: If `config` is of an unsupported type.
        ValueError: If `system_metrics` names an unknown group, or if `job` is given
            with `fork_from`.
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
        job: str | None = None,
        fork_from: tuple[str, int] | None = None,
        all_ranks: bool = False,
        capture_env: bool = True,
        compact: bool = True,
        flush_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
        system_metrics: bool | str | Sequence[str] = True,
        system_interval: float = 30.0,
        capture_console: bool = True,
        _started: float | None = None,
    ) -> None:
        self.project_dir = project_dir(project, dir)
        self.project = self.project_dir.name
        self._root = data_root(dir)
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
        self._system: SystemMonitor | None = None
        self._console: ConsoleLog | None = None
        groups = parse_groups(system_metrics)
        self.started = _started if _started is not None else time.time()
        runs_dir = self.project_dir / "runs"
        name = _fs.sanitize(name or "run")
        self.job = None if job in (None, MAIN) else _fs.sanitize(str(job))
        self._main_names: set[str] = set()
        self._main_names_read = 0.0
        self._names_seen: set[str] = set()

        if self.job is not None:
            if fork_from is not None:
                raise ValueError("a helper job joins a run and cannot fork_from another")

            if run_id is None or not (runs_dir / run_id / "run.json").exists():
                raise FileNotFoundError(
                    f"job={job!r} joins an existing run, but there is no run {run_id!r} in "
                    f"{runs_dir}; leave out job to start a new run"
                )

            resume = "must"

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
                self._finished = True  # every add_* call becomes a no-op
                return

            run_id = new_id
            self.path = runs_dir / run_id

        self.id = run_id
        self._meta_path = (
            self.path / "run.json" if self.job is None else job_path(self.path, self.job)
        )

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

        if self.dist.is_main and self.job is not None:
            self._write_job_meta(capture_env)
        elif self.dist.is_main:
            self._write_initial_meta(name, tags, notes, group, resumed, fork_from, capture_env)

        if fork_from is not None and self.dist.is_main:
            self._copy_fork(*fork_from)

        _active.append(self)
        atexit.register(self._atexit)
        _install_excepthook()

        if capture_console and (self.dist.is_main or all_ranks):
            base = "output" if self.job is None else f"output.{self.job}"
            log = f"{base}.log" if self.dist.is_main else f"{base}.r{self.dist.rank}.log"
            stamp = _dt.datetime.fromtimestamp(self.started).isoformat(" ", "seconds")
            job_note = f", job {self.job}" if self.job else ""
            self._console = ConsoleLog(
                self.path / "files" / log, f"[nuboard: session {self.session}{job_note}, {stamp}]"
            )

        if groups and self.dist.local_rank == 0:
            self._system = SystemMonitor(groups, system_interval, self._log_system)

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

    def _write_job_meta(self, capture_env: bool) -> None:
        """Create or update this helper job's `jobs/<job>.json`.

        Raises:
            RuntimeError: If the job is already running in another live process.
        """
        path = self._meta_path
        meta = _fs.read_json(path, None) or {}
        quiet = time.time() - (meta.get("heartbeat") or 0)
        patience = max(3 * float(meta.get("heartbeat_interval") or 10.0), 30.0)

        if meta.get("status") == "running" and quiet < patience:
            env = meta.get("env") or {}
            raise RuntimeError(
                f"job {self.job!r} is already running on run {self.id!r} "
                f"({env.get('host', '?')}, pid {env.get('pid', '?')}, last seen {quiet:.0f} s "
                f"ago). If that process was killed, start again in {patience - quiet:.0f} s."
            )

        if not meta:
            meta = {
                "format_version": FORMAT_VERSION,
                "job": self.job,
                "created": self.started,
                "sessions": [],
                "summary": {},
                "inputs": [],
                "outputs": [],
            }

        if self.config:
            meta["config"] = self.config
        else:
            self.config = (_fs.read_json(self.path / "run.json", {}) or {}).get("config") or {}

        meta.update(
            status="running",
            started=self.started,
            ended=None,
            heartbeat=time.time(),
            heartbeat_interval=self._heartbeat_interval,
            exit=None,
            env={"host": socket.gethostname(), "pid": os.getpid()},
        )
        meta["sessions"].append({"session": self.session, "started": self.started, "ended": None})

        if capture_env:
            meta["command"] = _env.command_line()

        path.parent.mkdir(exist_ok=True)
        self._meta = meta
        self._save_meta()

    def _warn_shared_names(self, data: Mapping[str, Any]) -> None:
        """Warn once per name when a helper job logs a scalar the main job also logs."""
        new = {k for k, _ in _flatten(data)} - self._names_seen

        if not new:
            return

        self._names_seen |= new

        if time.time() - self._main_names_read > 30:  # the main job may have logged more
            main = _fs.read_json(self.path / "run.json", {}) or {}
            self._main_names = set(main.get("summary") or {})
            self._main_names_read = time.time()

        for k in sorted(new & self._main_names):
            warnings.warn(
                f"{NAME}: {k} is also logged by the main job; this job's values replace "
                f"them from its first step. Log it under another name, such as "
                f"{self.job}/{k.split('/', 1)[-1]}.",
                stacklevel=3,
            )

    def _others_running(self) -> bool:
        """Return True if another job of this run (main or helper) is still running."""
        others = [j for j in read_jobs(self.path) if j["job"] != self.job]

        if self.job is not None:
            others.append(_fs.read_json(self.path / "run.json", {}) or {})

        return any(effective_status(j) == "running" for j in others)

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
        """Write `run.json`, or a helper job's file, with the current summary (rank 0 only)."""

        if not self.dist.is_main:
            return

        with self._meta_lock:
            if self._writer is not None:
                self._meta["summary"] = self._writer.summary()

            _fs.atomic_write_json(self._meta_path, self._meta)

    def _log_system(self, values: dict[str, float]) -> None:
        """Queue a system sample at the latest step; called by the system thread.

        It leaves the step counters alone, so `add_scalar` without a step is
        not affected, and logs from any rank, as only local rank 0 samples.
        """
        writer = self._writer or self._ensure_writer()

        if self.job is not None:
            prefix = f"system/{self.job}/"
            values = {prefix + k.removeprefix("system/"): v for k, v in values.items()}

        if writer is not None:
            writer.queue.append((0, self._last_step, _now(), values))

    def _on_heartbeat(self) -> None:
        """Update the heartbeat time in `run.json`; called by the writer thread."""

        if self._console is not None:
            self._console.flush()

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
                        own_pack=self.job is not None,
                    )

        return self._writer

    # -- logging ----------------------------------------------------------------
    def add_scalar(
        self,
        key: str | Mapping[str, Any],
        value: Any = None,
        step: int | None = None,
        *,
        low: Any = None,
        high: Any = None,
        time: float | None = None,
        all_ranks: bool | None = None,
    ) -> None:
        """Log one scalar, or several at the same step.

        Non-blocking: values are converted off-thread. On ranks other than 0 the
        call is a no-op unless `all_ranks=True` (here or in `init`).

        Args:
            key: The scalar's name, such as `"train/loss"`, or a dict of names
                and values to log several at once. Nested dicts are flattened
                with `/`.
            value: The value, for a single name: a number, bool, or NumPy or
                tensor scalar. With a dict, a value here is taken as `step`.
            step: Training step. Defaults to one more than the previous call.
            low: Optional lower bound, such as `mean - std`. Given together
                with `high`, the viewer shades the range around the line.
            high: Optional upper bound, such as `mean + std`.
            time: Unix timestamp of the values. Defaults to now.
            all_ranks: Overrides the run's `all_ranks` setting for this call.

        Raises:
            TypeError: If `key` is a name and `value` is missing, if only one of
                `low` and `high` is given, or if they are given with a dict.

        Example:
            >>> run.add_scalar("train/loss", 0.42, step=10)
            >>> run.add_scalar({"train": {"loss": 0.42, "acc": 0.9}}, step=10)
            >>> run.add_scalar("val/loss", mean, step=epoch, low=mean - std, high=mean + std)
        """

        if isinstance(key, Mapping):
            if low is not None or high is not None:
                raise TypeError("add_scalar takes low and high only with a single name")

            data = dict(key)

            if value is not None and step is None:
                step = int(value)
        elif value is None:
            raise TypeError(f"add_scalar({key!r}) needs a value")
        elif low is None and high is None:
            data = {key: value}
        elif low is None or high is None:
            raise TypeError(f"add_scalar({key!r}) needs both low and high, or neither")
        else:
            data = {key: value, key + fmt.BAND_LOW: low, key + fmt.BAND_HIGH: high}

        if step is None:
            step = self._next_step

        self._last_step = step

        if step >= self._next_step:
            self._next_step = step + 1

        if not self.dist.is_main and not (self.all_ranks if all_ranks is None else all_ranks):
            return

        if self.job is not None:
            self._warn_shared_names(data)

        writer = self._writer or self._ensure_writer()

        if writer is not None:
            writer.queue.append((0, step, _now() if time is None else time, data))

    def add_scalar_baseline(
        self,
        key: str | Mapping[str, Any],
        value: Any = None,
        *,
        low: Any = None,
        high: Any = None,
    ) -> None:
        """Set a reference value drawn on a scalar's chart, such as the unprocessed input's score.

        The baseline belongs to the scalar logged under the same name with
        `add_scalar`; logging it again replaces it. It is saved in `run.json`
        right away. On ranks other than 0 the call is a no-op.

        Args:
            key: The scalar's name, such as `"val/pesq"`, or a dict of names
                and values to set several at once.
            value: The reference value, for a single name.
            low: Optional lower bound of a range around the value, such as
                `mean - std`. Given together with `high`.
            high: Optional upper bound, such as `mean + std`.

        Raises:
            TypeError: If `key` is a name and `value` is missing, if only one of
                `low` and `high` is given, or if they are given with a dict.
            ValueError: If a value is not finite.

        Example:
            >>> run.add_scalar_baseline("val/pesq", 2.31)
            >>> run.add_scalar_baseline("val/stoi", 0.87, low=0.84, high=0.90)
            >>> run.add_scalar_baseline({"val/pesq": 2.31, "val/stoi": 0.87})
        """

        if isinstance(key, Mapping):
            if low is not None or high is not None:
                raise TypeError("add_scalar_baseline takes low and high only with a single name")

            items = {str(k): {"value": v} for k, v in key.items()}
        elif value is None:
            raise TypeError(f"add_scalar_baseline({key!r}) needs a value")
        elif (low is None) != (high is None):
            raise TypeError(f"add_scalar_baseline({key!r}) needs both low and high, or neither")
        else:
            items = {key: {"value": value, "low": low, "high": high}}

        baselines: dict[str, dict[str, float]] = {}

        for name, parts in items.items():
            entry = {k: _to_float(v) for k, v in parts.items() if v is not None}

            if not all(math.isfinite(v) for v in entry.values()):
                raise ValueError(f"the baseline of {name!r} must be finite: {entry}")

            baselines[name] = entry

        if not self.dist.is_main:
            return

        with self._meta_lock:
            self._meta.setdefault("baselines", {}).update(baselines)

        self._save_meta()

    def add_text(
        self,
        key: str,
        text: str,
        step: int | None = None,
        *,
        time: float | None = None,
        all_ranks: bool = False,
    ) -> None:
        """Log a string, such as generated samples or notes.

        On ranks other than 0 the call is a no-op unless `all_ranks=True`.

        Args:
            key: Name the text is logged under.
            text: The text; other values are converted with `str`.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            time: Unix timestamp of the item. Defaults to now.
            all_ranks: Log from every rank, not only rank 0.
        """

        if not self.dist.is_main and not all_ranks:
            return

        writer = self._ensure_writer()

        if writer is not None:
            writer.put_text(key, self._step(step), _now() if time is None else time, str(text))

    def add_image(
        self,
        key: str,
        image: Any,
        step: int | None = None,
        *,
        caption: str | None = None,
        time: float | None = None,
    ) -> None:
        """Log an image.

        Tensors are detached and moved to the CPU, and arrays are copied, so the
        caller may reuse its buffer right away; encoding happens on the background
        thread. Only rank 0 logs media.

        Args:
            key: Name the image is logged under.
            image: PNG/JPEG bytes, a file path, a PIL image, or an HxW, HxWxC or
                CxHxW array or tensor (uint8, or float in [0, 1]).
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            caption: Optional caption shown in the viewer.
            time: Unix timestamp of the item. Defaults to now.

        Example:
            >>> import numpy as np
            >>> run.add_image("samples", np.zeros((64, 64, 3), dtype=np.uint8), step=10)
        """
        from ._media import image_bytes

        image = _copied(image)  # the caller may change its tensor or array after we return

        self._put_media(
            key, step, lambda: image_bytes(image), {"kind": "image", "caption": caption}, time
        )

    def add_audio(
        self,
        key: str,
        audio: Any,
        step: int | None = None,
        *,
        sample_rate: int | None = None,
        caption: str | None = None,
        time: float | None = None,
    ) -> None:
        """Log audio.

        Arrays are stored as 16-bit WAV; files and bytes are stored as they are.
        Tensors are detached and moved to the CPU, and arrays are copied, so the
        caller may reuse its buffer right away. Only rank 0 logs media.

        Args:
            key: Name the audio is logged under.
            audio: A file path (wav, flac, mp3, ogg, opus, m4a), encoded bytes, or a
                `(samples,)` or `(channels, samples)` array or tensor.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            sample_rate: Sample rate in Hz; required for arrays.
            caption: Optional caption shown in the viewer.
            time: Unix timestamp of the item. Defaults to now.
        """
        from ._media import audio_bytes

        audio = _copied(audio)  # the caller may change its tensor or array after we return

        self._put_media(
            key,
            step,
            lambda: audio_bytes(audio, sample_rate),
            {"kind": "audio", "caption": caption},
            time,
        )

    def add_video(
        self,
        key: str,
        video: Any,
        step: int | None = None,
        *,
        fps: float = 4,
        caption: str | None = None,
        time: float | None = None,
    ) -> None:
        """Log a video, such as a rollout of an agent or a generated clip.

        Files and bytes (MP4, WebM, MOV, Ogg, GIF or animated PNG) are stored as
        they are. Arrays are encoded as an animated PNG, with the standard
        library, on the background thread; they are copied, so the caller may
        reuse its buffer right away. Only rank 0 logs media.

        Args:
            key: Name the video is logged under.
            video: A file path, encoded bytes, or a (T, H, W), (T, H, W, C) or
                (T, C, H, W) array or tensor (uint8, or float in [0, 1]); a
                (N, T, C, H, W) batch, as TensorBoard takes it, is tiled in a grid.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            fps: Frames per second of an array.
            caption: Optional caption shown in the viewer.
            time: Unix timestamp of the item. Defaults to now.

        Example:
            >>> frames = np.random.rand(16, 3, 64, 64)  # (T, C, H, W)
            >>> run.add_video("rollout", frames, step=10, fps=8)
        """
        from ._media import video_bytes

        if hasattr(video, "shape") and not isinstance(video, (bytes, str)):
            from ._media import video_frames

            video = video_frames(video)  # converted and copied now: uint8 frames

        rate = fps
        self._put_media(
            key,
            step,
            lambda: video_bytes(video, rate),
            {"kind": "video", "caption": caption},
            time,
        )

    def add_point_cloud(
        self,
        key: str,
        points: Any,
        step: int | None = None,
        *,
        colors: Any = None,
        axes: bool | Sequence[str] = False,
        caption: str | None = None,
        time: float | None = None,
    ) -> None:
        """Log a 3D point cloud, such as a lidar scan or points sampled from a mesh.

        The viewer draws it in a view you can rotate and zoom, colored by
        `colors` or else by height (z). Points are stored as float32; arrays are
        copied, so the caller may reuse its buffer right away. Only rank 0 logs
        media.

        The viewer can always show x, y and z axes with their values; `axes`
        shows them from the start and can name them.

        Args:
            key: Name the point cloud is logged under.
            points: An (N, 3) array, tensor or sequence of x, y, z positions.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            colors: Optional (N, 3) RGB colors, uint8 or floats in [0, 1].
            axes: True to show the axes, or their three names (such as
                `("x (m)", "y (m)", "z (m)")`) to show them with those labels.
            caption: Optional caption shown in the viewer.
            time: Unix timestamp of the item. Defaults to now.

        Raises:
            ValueError: If `axes` names are not three strings.

        Example:
            >>> import numpy as np
            >>> run.add_point_cloud("scan", np.random.rand(1000, 3), step=10, axes=True)
        """
        from ._media import points_bytes

        names: list[str] | None = None

        if axes is True:
            names = ["x", "y", "z"]
        elif axes:
            names = [str(a) for a in axes]

            if isinstance(axes, str) or len(names) != 3:
                raise ValueError("axes takes True or three names, such as ('x', 'y', 'z')")

        points = _copied(points)
        points = points if hasattr(points, "shape") else list(points)

        if colors is not None:
            colors = _copied(colors)
            colors = colors if hasattr(colors, "shape") else list(colors)

        self._put_media(
            key,
            step,
            lambda: points_bytes(points, colors),
            {"kind": "points", "caption": caption, **({"axes": names} if names else {})},
            time,
        )

    def add_pr_curve(
        self,
        key: str,
        labels: Any,
        predictions: Any,
        step: int | None = None,
        *,
        num_thresholds: int = 201,
        weights: Any = None,
        time: float | None = None,
    ) -> None:
        """Log a precision-recall curve, as TensorBoard's `add_pr_curve` does.

        True and false positives are counted at `num_thresholds` evenly spaced
        thresholds from 0 to 1, so only those counts are stored, not the
        predictions. For several classes, log one curve per class
        (`pr/cat`, `pr/dog`, ...). Only rank 0 logs media.

        Args:
            key: Name the curve is logged under.
            labels: Ground truth, as booleans or 0/1 values (array, tensor or
                sequence).
            predictions: Scores in [0, 1], one per label.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            num_thresholds: How many thresholds, from 0 to 1 inclusive.
            weights: Optional weight per example.
            time: Unix timestamp of the item. Defaults to now.

        Example:
            >>> run.add_pr_curve("pr/cat", labels == 3, probs[:, 3], step=epoch)
        """
        from ._media import _values, pr_curve_bytes

        # copied now: the caller may reuse its buffers after we return
        y, p = _values(labels), _values(predictions)
        w = _values(weights) if weights is not None else None
        self._put_media(
            key,
            step,
            lambda: pr_curve_bytes(y, p, num_thresholds, w),
            {"kind": "pr"},
            time,
        )

    def add_histogram(
        self,
        key: str,
        values: Any,
        step: int | None = None,
        *,
        bins: int | Sequence[float] = 50,
        range: tuple[float, float] | None = None,
        weights: Any = None,
        time: float | None = None,
    ) -> None:
        """Log the distribution of some values, such as a layer's weights or gradients.

        Only the bin counts and the values' min, max, mean and standard
        deviation are stored, so a million weights take a few hundred bytes.
        The viewer shows it with the figures: the histogram at the chosen step
        next to the previous one, how it moves over steps, and every run on one
        chart. Arrays and tensors are binned with NumPy on the writer thread;
        NaN and infinite values are counted but not binned. Only rank 0 logs
        media.

        Args:
            key: Name the distribution is logged under.
            values: An array, tensor or sequence of numbers, of any shape.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            bins: Number of equal-width bins, or their edges.
            range: The `(low, high)` the bins span; values outside are counted
                as `outside`. Defaults to the values' min and max.
            weights: Optional weight per value, of the same shape as `values`.
            time: Unix timestamp of the item. Defaults to now.

        Example:
            >>> for name, p in model.named_parameters():
            ...     run.add_histogram(f"weights/{name}", p, step=epoch)
        """
        from ._media import histogram_bytes

        def copy(x: Any) -> Any:
            if x is None:
                return None

            x = _copied(x)
            return x if hasattr(x, "__array__") else list(x)

        v, w = copy(values), copy(weights)
        edges = bins if isinstance(bins, int) else list(bins)
        self._put_media(
            key,
            step,
            lambda: histogram_bytes(v, edges, range, w),
            {"kind": "histogram"},
            time,
        )

    def add_table(
        self,
        key: str,
        rows: Any,
        step: int | None = None,
        *,
        row_id: str | None = None,
        time: float | None = None,
    ) -> None:
        """Log a table, such as per-example evaluation results.

        Cells hold numbers, booleans, strings or None, or media as
        `nuboard.Audio(...)` and `nuboard.Image(...)`; media cells are stored like
        `add_audio` and `add_image` items. Log the same table at several steps
        and the viewer colors each cell by how it changed, matching rows by
        `row_id`. Only rank 0 logs media.

        Args:
            key: Name the table is logged under.
            rows: A list of dicts (one per row), a dict of column lists, or a
                pandas DataFrame.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            row_id: The column that identifies a row across steps. Defaults to
                the first column.
            time: Unix timestamp of the item. Defaults to now.

        Raises:
            ValueError: If `row_id` is not one of the columns.

        Example:
            >>> clip = nb.Audio(wav, sample_rate=16000)
            >>> run.add_table("eval/samples", [
            ...     {"file": "p232_001", "pesq": 2.91, "enhanced": clip},
            ...     {"file": "p232_002", "pesq": 1.74},
            ... ], step=epoch)
        """
        from ._media import audio_bytes, cell_value, image_bytes, table_bytes
        from .cells import Audio, Image

        if not self.dist.is_main:
            return

        records = _records(rows)
        columns: list[str] = []

        for r in records:
            columns += [str(c) for c in r if str(c) not in columns]

        if not columns:
            return

        if row_id is not None and row_id not in columns:
            raise ValueError(f"row_id {row_id!r} is not a column of the table")

        kinds: dict[str, str] = {}
        out: list[list[Any]] = []
        at = self._step(step)

        for i, record in enumerate(records):
            values = {str(c): v for c, v in record.items()}
            row: list[Any] = []

            for c in columns:
                v = values.get(c)

                if isinstance(v, (Audio, Image)):
                    cell = f"{key}#{i}/{c}"
                    data = _copied(v.data)
                    meta = {"kind": "cell", "caption": v.caption}

                    if isinstance(v, Audio):
                        rate = v.sample_rate
                        producer = lambda d=data, r=rate: audio_bytes(d, r)  # noqa: E731
                    else:
                        producer = lambda d=data: image_bytes(d)  # noqa: E731

                    self._put_media(cell, at, producer, meta, time)
                    kinds[c] = "audio" if isinstance(v, Audio) else "image"
                    row.append({"$cell": cell})
                else:
                    row.append(cell_value(v))

            out.append(row)

        rid = row_id or columns[0]
        self._put_media(
            key, at, lambda: table_bytes(columns, kinds, out, rid), {"kind": "table"}, time
        )

    def add_figure(
        self, key: str, figure: Any, step: int | None = None, *, time: float | None = None
    ) -> None:
        """Log a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure, or a `WaveformFigure`.

        The figure is serialized immediately, since figures are mutable. Plotly,
        Vega-Lite and Bokeh figures stay interactive in the viewer; matplotlib
        figures are stored as SVG. A `nb.WaveformFigure` is plotted with its signals
        over the waveform; its arrays are copied and encoded on the background
        thread. Only rank 0 logs media.

        Args:
            key: Name the figure is logged under.
            figure: The figure, a Plotly or Vega-Lite spec as a dict, or a `nb.WaveformFigure`.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            time: Unix timestamp of the item. Defaults to now.

        Raises:
            TypeError: If the figure type is not supported.
            ValueError: If a waveform's signals do not hold one value per sample,
                its range is empty or reversed, or a region track is malformed.

        Example:
            >>> run.add_figure("eval/vad", nb.WaveformFigure(wav, 16000, {"vad": probs}))
        """
        from ._media import figure_bytes

        if isinstance(figure, WaveformFigure):
            from ._media import waveform_bytes, waveform_regions, waveform_signals

            audio, signals = waveform_signals(figure.audio, figure.signals)
            regions = waveform_regions(figure.regions) if figure.regions else None
            rate, bounds = figure.sample_rate, figure.range

            if not rate:
                raise ValueError("a waveform needs a sample_rate")

            if bounds is not None and not float(bounds[1]) > float(bounds[0]):
                raise ValueError(f"range must go from low to high, not {bounds}")

            self._put_media(
                key,
                step,
                lambda: waveform_bytes(audio, rate, signals, bounds),
                {"kind": "figure", "caption": figure.caption, "regions": regions},
                time,
            )
            return

        data, mime = figure_bytes(figure)  # serialize now: figures are mutable
        self._put_media(key, step, lambda: (data, mime), {"kind": "figure"}, time)

    def add_html(
        self, key: str, html: str, step: int | None = None, *, time: float | None = None
    ) -> None:
        """Log an HTML document; the viewer renders it in a sandboxed iframe.

        Only rank 0 logs media.

        Args:
            key: Name the document is logged under.
            html: The HTML source.
            step: Training step. Defaults to the step of the latest `add_scalar` call.
            time: Unix timestamp of the item. Defaults to now.
        """
        data = html.encode("utf-8")
        self._put_media(key, step, lambda: (data, "text/html"), {"kind": "html"}, time)

    def _put_media(
        self,
        key: str,
        step: int | None,
        producer: Any,
        meta: dict[str, Any],
        time: float | None = None,
    ) -> None:
        """Queue a media item; `producer` returns its encoded bytes on the writer thread."""

        if not self.dist.is_main:
            return

        writer = self._ensure_writer()

        if writer is not None:
            writer.put_media(
                key, self._step(step), _now() if time is None else time, producer, meta
            )

    def _step(self, step: int | None) -> int:
        """Return `step`, or the step of the latest `add_scalar` call when it is None."""
        return self._last_step if step is None else step

    # -- files --------------------------------------------------------------------
    def add_file(self, path: str | os.PathLike[str], name: str | None = None) -> Path | None:
        """Copy a file or folder into the run's `files/` folder.

        Use it to keep config files in whatever format they come in (YAML, TOML,
        Hydra's `.hydra/` folder, ...) or any other file next to the run. The viewer
        lists every file in `files/` and diffs them between runs. A folder is copied
        recursively. Each file is copied to a temporary name and moved into place
        with `os.replace`, so readers never see a half-written file; existing files
        with the same name are overwritten. Only rank 0 copies; the copy happens on
        the calling thread.

        Args:
            path: File or folder to copy.
            name: Destination inside `files/`, such as `"config.yaml"` or
                `"hydra/config.yaml"` (subfolders are created). Defaults to the base
                name of `path`.

        Returns:
            The destination path, or None on a non-zero rank.

        Raises:
            FileNotFoundError: If `path` does not exist (on rank 0).
            ValueError: If `name` is empty, absolute or contains `..`.
        """
        src = Path(path)
        rel = _relative_name(src.resolve().name if name is None else name)

        if not self.dist.is_main:
            return None

        if not src.exists():
            raise FileNotFoundError(f"cannot add file: {src} does not exist")

        files = self.path / "files"
        dest = files.joinpath(*rel.parts)

        if src.is_dir():
            for folder, _, names in os.walk(src):
                for fname in names:
                    file = Path(folder) / fname
                    _copy_atomic(file, dest / file.relative_to(src))

            dest.mkdir(parents=True, exist_ok=True)
        else:
            _copy_atomic(src, dest)

        return dest

    # -- artifacts ----------------------------------------------------------------
    def add_artifact(
        self,
        name: str,
        path: str | os.PathLike[str],
        *,
        type: str | None = None,
        metadata: dict[str, Any] | None = None,
        reference: bool = False,
        checksum: bool = False,
        description: str | None = None,
    ) -> Artifact:
        """Copy a file or folder into `artifacts/<name>/v<N>/` with a manifest.

        The new version is recorded as an output of this run.

        Args:
            name: Artifact name, sanitized to be safe as a folder name. A project
                before a `/`, as in `"datasets/fineweb-edu"`, adds the version to
                that project instead of this run's.
            path: File or folder to copy, or to reference.
            type: Optional free-form type, such as `"model"` or `"dataset"`.
            metadata: Optional extra data stored in the manifest.
            reference: Record where `path` is, with each file's size and
                modification time, instead of copying it.
            checksum: With `reference`, also hash every file (SHA-256).
            description: Optional free text saying what this version is.

        Returns:
            The new artifact version.

        Raises:
            FileNotFoundError: If `path` does not exist.
        """
        project, bare, _ = split_ref(name)
        home = self._artifact_project(project)
        art = _add_artifact(
            home,
            bare,
            path,
            type=type,
            metadata=metadata,
            run_id=self.id,
            reference=reference,
            checksum=checksum,
            description=description,
        )

        with self._meta_lock:
            self._meta.setdefault("outputs", []).append(self._artifact_record(art, project, home))
            self._save_meta()

        return art

    def use_artifact(self, ref: str) -> Artifact:
        """Resolve an artifact reference and record it as an input of this run.

        A version whose files are missing or changed since it was made (checked by
        size, without reading them) gives a warning.

        Args:
            ref: `"name"` or `"name:latest"` for the newest version, or
                `"name:v2"` for a specific one. A project before the name, as in
                `"datasets/fineweb-edu:v2"`, looks in that project.

        Returns:
            The resolved artifact version.

        Raises:
            FileNotFoundError: If the artifact or version does not exist.
        """
        project, _, _ = split_ref(ref)
        home = self._artifact_project(project)
        art = resolve_artifact(home, ref)
        _warn_if_changed(art)

        with self._meta_lock:
            self._meta.setdefault("inputs", []).append(self._artifact_record(art, project, home))
            self._save_meta()

        return art

    def _artifact_project(self, project: str | None) -> Path:
        """Return the folder of the project an artifact name points to; this run's by default."""
        return self.project_dir if project is None else project_dir(project, self._root)

    def _artifact_record(self, art: Artifact, project: str | None, home: Path) -> dict[str, Any]:
        """Return the `inputs`/`outputs` entry for `art`, with its project when it is another."""
        record: dict[str, Any] = {"artifact": art.name, "version": art.version}

        if home.resolve() != self.project_dir.resolve():
            record["project"] = "/".join(home.relative_to(self._root).parts)
            record["project_path"] = Path(os.path.relpath(home, self.project_dir)).as_posix()

        return record

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

        if self._system is not None:
            self._system.stop()

        if self._console is not None:
            self._console.close()

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

        if (
            self._compact
            and self.dist.world_size == 1
            and status != "running"
            and not self._others_running()  # the last job to end compacts
        ):
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
            full = "".join(traceback.format_exception(exc_type, exc, tb))
            status = "killed" if issubclass(exc_type, KeyboardInterrupt) else "crashed"

            if self._console is not None:  # Python prints it only after the log is closed
                self._console.write(full)

            self.finish(status=status, exit_code=1, error=full[-4000:])

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
    job: str | None = None,
    fork_from: tuple[str, int] | None = None,
    all_ranks: bool = False,
    capture_env: bool = True,
    compact: bool = True,
    flush_interval: float = 1.0,
    heartbeat_interval: float = 10.0,
    system_metrics: bool | str | Sequence[str] = True,
    system_interval: float = 30.0,
    capture_console: bool = True,
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
            `argparse.Namespace`. Saved in `run.json`. When resuming with no config,
            the stored one is kept. To keep a config file as it is (YAML, TOML,
            Hydra's `.hydra/` folder, ...), attach it with `Run.add_file`.
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
        job: Join the existing run `run_id` as a helper job of this name, such as
            `"eval"` for a job that evaluates checkpoints while training goes on.
            It logs into the same run without touching its status, heartbeat or
            summary, which stay the main job's: its own state goes in
            `jobs/<job>.json`, its console in `files/output.<job>.log` and its
            system metrics under `system/<job>/`. None (or `"main"`) is the
            process that creates the run. Restarting a job continues it.
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
        system_metrics: Log CPU, memory and GPU use as `system/` scalars, from
            local rank 0 of each machine. True for all of them, False for none,
            or a list of groups out of `"cpu"`, `"memory"` and `"gpu"`.
        system_interval: Seconds between system samples.
        capture_console: Copy what the script prints to stdout and stderr into
            `files/output.log`, shown in the viewer's run details.
        _started: Start timestamp override, for tests.

    Returns:
        The new run.

    Raises:
        FileExistsError: If `run_id` exists and `resume` is None, or if a run folder
            differing only by case exists.
        FileNotFoundError: If `resume="must"` and `run_id` does not exist, if the
            `fork_from` parent does not exist, or if `job` is given and run `run_id`
            does not exist.
        RuntimeError: If `job` is already running on this run in another process.
        TimeoutError: If a non-zero rank waits 120 s without rank 0 creating the
            run folder.
        TypeError: If `config` is of an unsupported type.
        ValueError: If `system_metrics` names an unknown group.

    Example:
        >>> import nuboard as nb
        >>> with nb.init("my-project", name="baseline", config={"lr": 1e-3}) as run:
        ...     run.add_scalar({"loss": 0.5}, step=0)
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
        job=job,
        fork_from=fork_from,
        all_ranks=all_ranks,
        capture_env=capture_env,
        compact=compact,
        flush_interval=flush_interval,
        heartbeat_interval=heartbeat_interval,
        system_metrics=system_metrics,
        system_interval=system_interval,
        capture_console=capture_console,
        _started=_started,
    )


def add_artifact(
    project: str,
    name: str,
    path: str | os.PathLike[str],
    *,
    type: str | None = None,
    metadata: dict[str, Any] | None = None,
    reference: bool = False,
    checksum: bool = False,
    description: str | None = None,
    dir: str | os.PathLike[str] | None = None,
) -> Artifact:
    """Add a new artifact version without a run, such as a dataset no script produced.

    The version has no producing run. Inside a training script, use
    `Run.add_artifact` so the version is linked to the run.

    Args:
        project: Project to add it to, as in `init`, such as `"datasets"`.
        name: Artifact name, sanitized to be safe as a folder name.
        path: File or folder to copy, or to reference.
        type: Optional free-form type, such as `"dataset"`.
        metadata: Optional extra data stored in the manifest.
        reference: Record where `path` is, with each file's size and modification
            time, instead of copying it.
        checksum: With `reference`, also hash every file (SHA-256).
        description: Optional free text saying what this version is.
        dir: Root folder holding the projects, as in `init`.

    Returns:
        The new artifact version.

    Raises:
        FileNotFoundError: If `path` does not exist.
    """
    return _add_artifact(
        project_dir(project, dir),
        name,
        path,
        type=type,
        metadata=metadata,
        reference=reference,
        checksum=checksum,
        description=description,
    )


def get_artifact(ref: str, *, dir: str | os.PathLike[str] | None = None) -> Artifact:
    """Find an artifact version without a run, such as in a notebook.

    Nothing is recorded; inside a run, use `Run.use_artifact` so the run lists
    the version as an input. Missing or changed files give a warning.

    Args:
        ref: `"project/name"`, `"project/name:latest"` or `"project/name:v2"`.
            Without a project, the `"default"` project is used, as in `init`.
        dir: Root folder holding the projects, as in `init`.

    Returns:
        The resolved artifact version.

    Raises:
        FileNotFoundError: If the artifact or version does not exist.
    """
    project, _, _ = split_ref(ref)
    art = resolve_artifact(project_dir(project, dir), ref)
    _warn_if_changed(art)
    return art
