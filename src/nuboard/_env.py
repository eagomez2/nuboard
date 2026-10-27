"""Capture of the environment a run was started in, and rank detection."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata


@dataclass(frozen=True)
class DistInfo:
    """Where this process sits in a distributed job.

    Attributes:
        rank: Global rank of this process; 0 for a single-process run.
        local_rank: Rank of this process on its own machine.
        world_size: Total number of processes in the job.
        shared_id: An id common to every rank of the job (`TORCHELASTIC_RUN_ID` or
            `SLURM_JOB_ID`), used to derive the same run id on every rank; None when
            neither is set.
    """

    rank: int = 0
    local_rank: int = 0
    world_size: int = 1
    shared_id: str | None = None

    @property
    def is_main(self) -> bool:
        """Whether this is rank 0, the process that owns the run's metadata."""
        return self.rank == 0


def _env_int(*names: str) -> int | None:
    """Return the integer value of the first of `names` that is set and parses, else None."""

    for name in names:
        value = os.environ.get(name)

        if value not in (None, ""):
            try:
                return int(value)
            except ValueError:
                continue

    return None


def detect_dist() -> DistInfo:
    """Read rank and world size from torchrun, SLURM or Open MPI variables.

    Variables are tried in the order torchrun, SLURM, Open MPI, PMI. A process with
    none of them set is treated as a single-process run.

    Returns:
        The detected `DistInfo`.
    """
    rank = _env_int("RANK", "SLURM_PROCID", "OMPI_COMM_WORLD_RANK", "PMI_RANK") or 0
    local = _env_int("LOCAL_RANK", "SLURM_LOCALID", "OMPI_COMM_WORLD_LOCAL_RANK") or 0
    world = _env_int("WORLD_SIZE", "SLURM_NTASKS", "OMPI_COMM_WORLD_SIZE", "PMI_SIZE") or 1
    shared = os.environ.get("TORCHELASTIC_RUN_ID") or os.environ.get("SLURM_JOB_ID")

    if shared == "none":  # torchrun's default when no rendezvous id is given
        shared = None

    return DistInfo(rank=rank, local_rank=local, world_size=world, shared_id=shared)


def broadcast_run_id(run_id: str | None) -> str | None:
    """Share rank 0's run id with every rank via `torch.distributed`, if it is up.

    Only takes effect when `torch` is already imported and its process group is
    initialized. Any error is swallowed so tracking never breaks training.

    Args:
        run_id: This rank's run id; only rank 0's value matters.

    Returns:
        Rank 0's run id, or `run_id` unchanged when it cannot be broadcast.
    """
    torch = sys.modules.get("torch")

    if torch is None:
        return run_id

    try:
        dist = torch.distributed

        if not (dist.is_available() and dist.is_initialized()):
            return run_id

        box = [run_id]
        dist.broadcast_object_list(box, src=0)
        return box[0]
    except Exception:  # never let tracking break training
        return run_id


def _run(cmd: list[str], cwd: str | None = None, timeout: float = 3.0) -> str | None:
    """Run `cmd` and return its stdout, or None if it fails, is missing or times out."""

    try:
        out = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None


def git_info(cwd: str | None = None) -> tuple[dict[str, object] | None, str | None]:
    """Describe the git checkout the run was started from.

    Args:
        cwd: Directory to inspect. Defaults to the current working directory.

    Returns:
        A pair `(info, diff)`. `info` holds `commit`, `branch`, `remote`, `root` and
        `dirty`; `diff` is the `git diff HEAD` text (empty when clean). Both are None
        outside a repository or when `git` is not installed.
    """

    if shutil.which("git") is None:
        return None, None

    commit = _run(["git", "rev-parse", "HEAD"], cwd)

    if not commit:
        return None, None

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    remote = _run(["git", "config", "--get", "remote.origin.url"], cwd)
    root = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    diff = _run(["git", "diff", "HEAD"], cwd, timeout=10.0) or ""
    info = {
        "commit": commit.strip(),
        "branch": (branch or "").strip() or None,
        "remote": (remote or "").strip() or None,
        "root": (root or "").strip() or None,
        "dirty": bool(diff.strip()),
    }
    return info, diff


def pip_freeze() -> str:
    """List installed packages in `pip freeze` style, from distribution metadata.

    No subprocess is started. Each distribution appears once, as `name==version`,
    sorted case-insensitively.

    Returns:
        The list, one package per line, ending with a newline.
    """
    seen: dict[str, str] = {}

    for dist in metadata.distributions():
        name = dist.metadata["Name"]

        if name and name.lower() not in seen:
            seen[name.lower()] = f"{name}=={dist.version}"

    return "\n".join(sorted(seen.values(), key=str.lower)) + "\n"


def cuda_order(gpus: list[tuple[int, str]], visible: str | None) -> list[tuple[int, str]]:
    """Return the GPUs CUDA shows this process, in `cuda:0`, `cuda:1`, ... order.

    Follows CUDA's reading of `CUDA_VISIBLE_DEVICES`: a comma-separated list of
    GPU indices or UUIDs (a unique prefix of a `GPU-...` UUID is enough), ended
    by the first entry that names no GPU or one already listed.

    Args:
        gpus: `(index, uuid)` of every GPU of the machine, as `nvidia-smi` lists them.
        visible: The value of `CUDA_VISIBLE_DEVICES`, or None when it is unset.

    Returns:
        The visible GPUs' `(index, uuid)`, the first one being `cuda:0`.
    """

    if visible is None:
        return list(gpus)

    order: list[tuple[int, str]] = []

    for token in visible.split(","):
        token = token.strip()

        if token.isdigit():
            found = [g for g in gpus if g[0] == int(token)]
        elif token.startswith("GPU-"):
            found = [g for g in gpus if g[1].startswith(token)]
        else:
            found = []

        if len(found) != 1 or found[0] in order:
            break

        order.append(found[0])

    return order


def gpus() -> list[dict[str, object]]:
    """List the NVIDIA GPUs this process can use, as reported by `nvidia-smi`.

    `CUDA_VISIBLE_DEVICES` is respected: only the GPUs it names are listed, in
    its order, so the first one is `cuda:0` in the script.

    Returns:
        One dict per GPU with `device` (such as `"cuda:0"`), `index` (the GPU's
        index on the machine), `uuid`, `name`, `memory` and `driver`; empty when
        `nvidia-smi` is not installed or fails.
    """

    if shutil.which("nvidia-smi") is None:
        return []

    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,driver_version",
            "--format=csv,noheader",
        ]
    )
    rows: dict[tuple[int, str], list[str]] = {}

    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]

        if len(parts) == 5 and parts[0].isdigit():
            rows[(int(parts[0]), parts[1])] = parts[2:]

    order = cuda_order(list(rows), os.environ.get("CUDA_VISIBLE_DEVICES"))
    return [
        {
            "device": f"cuda:{i}",
            "index": index,
            "uuid": uuid,
            "name": rows[(index, uuid)][0],
            "memory": rows[(index, uuid)][1],
            "driver": rows[(index, uuid)][2],
        }
        for i, (index, uuid) in enumerate(order)
    ]


def environment() -> dict[str, object]:
    """Describe the machine and process the run is started in.

    Returns:
        A dict with the host name, platform, Python version and executable, `argv`,
        working directory, process id, GPUs and `CUDA_VISIBLE_DEVICES`.
    """
    return {
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "gpus": gpus(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }


def command_line() -> str:
    """Return the shell-quoted command line that started this process.

    Returns:
        The Python executable followed by `sys.argv`, ending with a newline.
    """
    import shlex

    return " ".join(shlex.quote(a) for a in [sys.executable, *sys.argv]) + "\n"
