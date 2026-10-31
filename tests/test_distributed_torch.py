"""Real multi-process runs with torch.distributed (gloo, CPU); skipped without torch."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("torch.distributed")

SCRIPT = textwrap.dedent(
    """
    import os, sys
    import torch
    import torch.distributed as dist
    import nuboard as nb

    dist.init_process_group("gloo")
    rank = dist.get_rank()
    pattern = sys.argv[1]
    run = None

    if pattern == "every" or rank == 0:
        run = nb.init("p", dir=sys.argv[2], capture_env=False, system_metrics=False,
                      capture_console=False)

    for step in range(3):
        t = torch.ones(1)
        dist.all_reduce(t)  # a training step: every rank must take part
        if run is not None:
            run.add_scalar({"loss": float(t)}, step=step)

    if run is not None:
        run.finish()
        print("ID", rank, run.id)

    dist.barrier()
    dist.destroy_process_group()
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch(tmp_path: Path, pattern: str, extra: dict[str, str]) -> list[str]:
    script = tmp_path / "train.py"
    script.write_text(SCRIPT)
    port = str(_free_port())
    procs = []

    for rank in range(2):
        env = {
            **os.environ,
            "MASTER_ADDR": "127.0.0.1",
            "MASTER_PORT": port,
            "WORLD_SIZE": "2",
            "RANK": str(rank),
            "LOCAL_RANK": str(rank),
            **extra,
        }

        for name in ("SLURM_JOB_ID", "TORCHELASTIC_RUN_ID"):
            if name not in extra:
                env.pop(name, None)

        procs.append(
            subprocess.Popen(
                [sys.executable, str(script), pattern, str(tmp_path / "data")],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

    out = []

    try:
        for p in procs:
            stdout, stderr = p.communicate(timeout=60)  # the old broadcast hung here
            assert p.returncode == 0, stderr
            out += [line for line in stdout.splitlines() if line.startswith("ID")]
    finally:
        for p in procs:
            p.kill()

    return out


def test_init_on_rank_0_only_does_not_hang(tmp_path):
    ids = _launch(tmp_path, "rank0", {})
    assert len(ids) == 1
    runs = list((tmp_path / "data" / "p" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "events.r0.s0.log").exists()


def test_init_on_every_rank_without_shared_id(tmp_path):
    ids = _launch(tmp_path, "every", {})
    assert {i.split()[1] for i in ids} == {"0", "1"}
    assert len(list((tmp_path / "data" / "p" / "runs").iterdir())) == 1


def test_init_on_every_rank_with_shared_id_shares_the_folder(tmp_path):
    ids = _launch(tmp_path, "every", {"TORCHELASTIC_RUN_ID": "job-42"})
    assert len({i.split()[2] for i in ids}) == 1  # both ranks report the same run id
    assert len(list((tmp_path / "data" / "p" / "runs").iterdir())) == 1
