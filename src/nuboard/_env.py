"""Capture of the environment a run was started in, and rank detection."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


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


# git never asks for a password, never takes the index lock (so a `git` command the user
# runs at the same time is not refused), and speaks plain English
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}


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
            env={**os.environ, **_GIT_ENV} if cmd[:1] == ["git"] else None,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def safe_url(url: str) -> str:
    """Return `url` without anything that could be a credential.

    The user and password (`https://user:TOKEN@host/...`), query and fragment of
    a URL with a scheme are removed. An scp-like remote (`git@host:org/repo`)
    names a user, never a password, and is kept.
    """
    url = url.strip()

    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        return url

    try:
        parts = urlsplit(url)
    except ValueError:
        return ""

    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _cwd() -> str | None:
    """The working directory, or None when it no longer exists."""

    try:
        return os.getcwd()
    except OSError:
        return None


def _script_dir() -> str | None:
    """The folder of the script that started this process, or None (notebooks, `-c`, REPL)."""
    main = sys.modules.get("__main__")
    candidates = [getattr(main, "__file__", None), sys.argv[0] if sys.argv else None]

    for path in candidates:
        if not path or not isinstance(path, str):
            continue

        try:
            file = Path(path).resolve()
        except (OSError, RuntimeError, ValueError):
            continue

        if file.is_file():
            return str(file.parent)

    return None


def _repo_root(directory: str | None) -> str | None:
    """The top folder of the git working tree `directory` is in, or None."""

    if not directory or not os.path.isdir(directory):
        return None

    root = _run(["git", "rev-parse", "--show-toplevel"], directory)
    return root.strip() or None if root else None


def _code_repo(code_dir: str | os.PathLike[str] | None) -> tuple[str | None, str | None]:
    """Find the repository of the training code: `code_dir`, the script's folder, then the cwd.

    Returns:
        `(root, source)`: the repository's top folder and which place it was
        found from (`"code_dir"`, `"script"` or `"cwd"`), or `(None, None)`.
    """
    import warnings

    places = [
        ("code_dir", os.fspath(code_dir) if code_dir is not None else None),
        ("script", _script_dir()),
        ("cwd", _cwd()),
    ]
    found = [(source, _repo_root(d)) for source, d in places if d]

    if code_dir is not None and not found[0][1]:
        warnings.warn(
            f"code_dir={os.fspath(code_dir)!r} is not inside a git repository; "
            "looking for one from the script's folder and the working directory instead",
            stacklevel=4,
        )

    roots = [(source, root) for source, root in found if root]

    if not roots:
        return None, None

    source, root = roots[0]
    cwd_root = dict(roots).get("cwd")

    if source == "script" and cwd_root and cwd_root != root:
        warnings.warn(
            f"recording git info of the script's repository {root}, not of the working "
            f"directory's {cwd_root}; pass code_dir= to choose",
            stacklevel=4,
        )

    return root, source


def git_info(
    cwd: str | None = None, code_dir: str | os.PathLike[str] | None = None
) -> tuple[dict[str, object] | None, str | None]:
    """Describe the git checkout of the code the run was started from.

    Every git command is optional: one that fails, is refused (an unsafe
    repository owner, say) or times out leaves its field None, and this never
    raises.

    Args:
        cwd: Directory to inspect, as is. When None, the repository is looked
            for from `code_dir`, then the running script's folder, then the
            working directory (see `git.source` in the format reference).
        code_dir: Folder of the training code, when the script is not (a
            notebook, `python -m` of an installed package, a CLI entry point).

    Returns:
        A pair `(info, diff)`. `info` holds `commit` (None in a repository with
        no commits yet), `branch` (None when detached), `remote` (without any
        credential), `root`, `dirty`, `pushed`, `untracked` and `source`;
        `diff` is the `git diff HEAD` text (the staged changes before the first
        commit; empty when clean). Both are None outside a repository or when
        `git` is not installed.
    """

    try:
        if shutil.which("git") is None:
            return None, None

        if cwd is not None:
            root, source = _repo_root(cwd), "cwd"
        else:
            root, source = _code_repo(code_dir)

        if root is None:
            return None, None

        return _describe(root, source)
    except Exception:  # never let tracking break training
        return None, None


def _describe(root: str, source: str | None) -> tuple[dict[str, object], str]:
    """`git_info` for the working tree at `root`."""
    commit = (_run(["git", "rev-parse", "--verify", "-q", "HEAD"], root) or "").strip() or None
    branch = (_run(["git", "symbolic-ref", "-q", "--short", "HEAD"], root) or "").strip() or None
    remote = (_run(["git", "config", "--get", "remote.origin.url"], root) or "").strip()

    # before the first commit there is no HEAD to compare with: the staged files are the change
    diff_cmd = ["git", "diff", "HEAD"] if commit else ["git", "diff", "--cached"]
    diff = _run([*diff_cmd, "--no-ext-diff", "--no-color"], root, timeout=10.0)

    untracked_out = _run(["git", "ls-files", "--others", "--exclude-standard", "-z"], root, 10.0)
    untracked = None if untracked_out is None else len([f for f in untracked_out.split("\0") if f])

    pushed: bool | None = None

    if commit:
        remotes = _run(["git", "for-each-ref", "--count=1", "refs/remotes"], root)
        containing = _run(["git", "branch", "-r", "--contains", commit], root)

        if remotes and containing is not None:
            pushed = bool(containing.strip())

    info: dict[str, object] = {
        "commit": commit,
        "branch": branch,
        "remote": safe_url(remote) or None,
        "root": root,
        "dirty": None if diff is None else bool(diff.strip()),
        "pushed": pushed,
        "untracked": untracked,
        "source": source,
    }
    return info, diff or ""


def _requirement(dist: metadata.Distribution, name: str, version: str) -> str:
    """One `pip freeze` line, keeping a VCS install's commit (PEP 610), never a local path."""

    try:
        direct = json.loads(dist.read_text("direct_url.json") or "null")
    except (OSError, ValueError):
        direct = None

    if not isinstance(direct, dict):
        return f"{name}=={version}"

    url = str(direct.get("url") or "")
    vcs = direct.get("vcs_info")

    if isinstance(vcs, dict) and url and not url.startswith("file:"):
        commit = vcs.get("commit_id") or vcs.get("requested_revision")
        kind = vcs.get("vcs") or "git"
        return f"{name} @ {kind}+{safe_url(url)}" + (f"@{commit}" if commit else "")

    if isinstance(direct.get("archive_info"), dict) and url and not url.startswith("file:"):
        return f"{name} @ {safe_url(url)}"

    return f"{name}=={version}  # editable/local install"


def pip_freeze() -> str:
    """List installed packages in `pip freeze` style, from distribution metadata.

    No subprocess is started. Each distribution appears once, as `name==version`,
    sorted case-insensitively. A package installed from a VCS URL is written as
    `name @ git+URL@commit` (URL without credentials); one installed from a
    local folder or in editable mode keeps `name==version`, marked with a
    comment, and its path is not recorded. Broken metadata is skipped.

    Returns:
        The list, one package per line, ending with a newline.
    """
    seen: dict[str, str] = {}

    try:
        dists = list(metadata.distributions())
    except Exception:
        dists = []

    for dist in dists:
        try:
            name = dist.metadata["Name"]
            version = dist.version
        except Exception:
            continue

        if name and version and name.lower() not in seen:
            seen[name.lower()] = _requirement(dist, name, version)

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
        "cwd": _cwd(),
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
