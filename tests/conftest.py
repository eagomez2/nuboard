from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Keep runs and the catalog cache inside the test's temp folder."""
    monkeypatch.setenv("NUBOARD_DIR", str(tmp_path / "exp"))
    monkeypatch.setenv("NUBOARD_CACHE_DIR", str(tmp_path / "cache"))
    for var in (
        "RANK",
        "LOCAL_RANK",
        "WORLD_SIZE",
        "SLURM_PROCID",
        "SLURM_NTASKS",
        "OMPI_COMM_WORLD_RANK",
        "TORCHELASTIC_RUN_ID",
        "SLURM_JOB_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
