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
    rank: int = 0
    local_rank: int = 0
    world_size: int = 1
    shared_id: str | None = None

    @property
    def is_main(self) -> bool:
        return self.rank == 0


def _env_int(*names: str) -> int | None:
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            try:
                return int(value)
            except ValueError:
                continue
    return None


def detect_dist() -> DistInfo:
    """Read rank/world size from torchrun, SLURM or Open MPI variables."""
    rank = _env_int("RANK", "SLURM_PROCID", "OMPI_COMM_WORLD_RANK", "PMI_RANK") or 0
    local = _env_int("LOCAL_RANK", "SLURM_LOCALID", "OMPI_COMM_WORLD_LOCAL_RANK") or 0
    world = _env_int("WORLD_SIZE", "SLURM_NTASKS", "OMPI_COMM_WORLD_SIZE", "PMI_SIZE") or 1
    shared = os.environ.get("TORCHELASTIC_RUN_ID") or os.environ.get("SLURM_JOB_ID")
    if shared == "none":  # torchrun's default when no rendezvous id is given
        shared = None
    return DistInfo(rank=rank, local_rank=local, world_size=world, shared_id=shared)


def broadcast_run_id(run_id: str | None) -> str | None:
    """Share rank 0's run id with every rank via torch.distributed, if it is up."""
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
    """Return (git metadata, ``git diff HEAD`` text) or (None, None) outside a repo."""
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
    """``pip freeze``-style list from installed distribution metadata (no subprocess)."""
    seen: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name and name.lower() not in seen:
            seen[name.lower()] = f"{name}=={dist.version}"
    return "\n".join(sorted(seen.values(), key=str.lower)) + "\n"


def gpus() -> list[dict[str, str]]:
    if shutil.which("nvidia-smi") is None:
        return []
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]
    )
    result = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            result.append({"name": parts[0], "memory": parts[1], "driver": parts[2]})
    return result


def environment() -> dict[str, object]:
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
    import shlex

    return " ".join(shlex.quote(a) for a in [sys.executable, *sys.argv]) + "\n"
