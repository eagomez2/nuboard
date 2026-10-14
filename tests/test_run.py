"""The Python API: init, log, finish, resume, fork, ranks and crash safety."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import time
import warnings

import pytest

import nuboard as nm
from nuboard.catalog import effective_status
from nuboard.reader import RunReader


def test_init_creates_self_contained_folder(tmp_path):
    with nm.init("proj", name="base line:1", config={"lr": 1e-3, "opt": {"b": [0.9, 0.95]}}) as run:
        run.log({"loss": 1.0, "nested": {"acc": 0.5}}, step=0)
    assert run.path.parent.parent == tmp_path / "exp" / "proj"
    assert re.fullmatch(r"\d{8}-\d{4}_base-line-1_[a-z2-9]{6}", run.id)
    assert ":" not in run.id
    meta = json.loads((run.path / "run.json").read_text("utf-8"))
    assert meta["format_version"] == nm.FORMAT_VERSION
    assert meta["status"] == "finished"
    assert meta["config"]["opt"]["b"] == [0.9, 0.95]
    assert meta["summary"]["nested/acc"]["last"] == 0.5
    assert {"config.json", "requirements.txt", "command.txt"} <= set(os.listdir(run.path / "files"))
    for f in run.path.rglob("*"):  # nothing points outside the folder
        if f.is_file() and f.suffix in (".json", ".txt"):
            assert str(tmp_path / "exp" / "other") not in f.read_text("utf-8", errors="ignore")


def test_log_values_and_steps(tmp_path):
    run = nm.init("p", capture_env=False)
    run.log({"a": 1})  # step 0
    run.log({"a": 2})  # step 1
    run.log({"a": 3}, step=10)
    run.log({"a": 4})  # step 11
    import numpy as np

    run.log({"np": np.float32(1.5), "flag": True, "nan": float("nan")}, step=12)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run.log({"bad": "text"}, step=13)
        run.flush()
    assert any("cannot convert" in str(w.message) for w in caught)
    run.finish()
    r = RunReader(run.path)
    steps, _, values = r.scalars("a")
    assert list(steps) == [0, 1, 10, 11]
    assert list(values) == [1, 2, 3, 4]
    assert r.scalars("np")[2][0] == 1.5
    summary = json.loads((run.path / "run.json").read_text())["summary"]
    assert summary["nan"]["last"] == "nan" and summary["nan"]["nonfinite"] == 1
    assert "bad" not in summary


def test_log_is_fast():
    run = nm.init("p", capture_env=False, compact=False)
    data = {f"metric_{i}": float(i) for i in range(50)}
    n = 5000
    t0 = time.perf_counter()
    for step in range(n):
        run.log(data, step=step)
    per_call = (time.perf_counter() - t0) / n
    run.finish()
    assert per_call < 50e-6, f"log() took {per_call * 1e6:.1f} µs"


def test_exception_marks_run_crashed():
    with pytest.raises(RuntimeError):
        with nm.init("p", capture_env=False) as run:
            run.log({"x": 1}, step=0)
            raise RuntimeError("boom")
    meta = json.loads((run.path / "run.json").read_text())
    assert meta["status"] == "crashed"
    assert "boom" in meta["exit"]["error"]


def test_process_killed_without_finish_keeps_flushed_data(tmp_path):
    script = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(os.path.join(os.path.dirname(nm.__file__), ".."))!r})
        import nuboard as nm
        run = nm.init("p", dir={str(tmp_path / "crash")!r}, capture_env=False, flush_interval=0.05)
        for i in range(1000):
            run.log({{"loss": 1.0 / (i + 1)}}, step=i)
        run.flush()
        print(run.path, flush=True)
        os._exit(1)  # no finish(), no atexit: like SIGKILL or a node failure
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    path = out.stdout.strip().splitlines()[-1]
    reader = RunReader(path)
    steps, _, _ = reader.scalars("loss")
    assert len(steps) == 1000
    meta = json.loads(open(os.path.join(path, "run.json")).read())
    assert meta["status"] == "running"
    meta["heartbeat"] -= 3600
    assert effective_status(meta) == "lost"


def test_resume_new_session_later_wins():
    run = nm.init("p", name="r", capture_env=False)
    for s in range(10):
        run.log({"loss": 10.0 - s}, step=s)
    run.finish()
    with pytest.raises(FileExistsError):
        nm.init("p", run_id=run.id, capture_env=False)
    again = nm.init("p", run_id=run.id, resume="must", capture_env=False)
    assert again.session == 1
    for s in range(5, 8):  # restarted from a checkpoint at step 5
        again.log({"loss": 100.0 + s}, step=s)
    again.finish()
    steps, _, values = RunReader(run.path).scalars("loss")
    assert list(steps) == [0, 1, 2, 3, 4, 5, 6, 7]
    assert list(values[5:]) == [105.0, 106.0, 107.0]
    meta = json.loads((run.path / "run.json").read_text())
    assert len(meta["sessions"]) == 2
    with pytest.raises(FileNotFoundError):
        nm.init("p", run_id="nope", resume="must", capture_env=False)
    created = nm.init("p", run_id="20250101-0000_fresh_abcdef", resume="auto", capture_env=False)
    created.finish()
    assert created.path.name == "20250101-0000_fresh_abcdef"


def test_fork_copies_history_up_to_step():
    parent = nm.init("p", capture_env=False)
    for s in range(10):
        parent.log({"loss": float(s)}, step=s)
    parent.finish()
    child = nm.init("p", fork_from=(parent.id, 4), capture_env=False)
    child.log({"loss": 40.0}, step=5)
    child.finish()
    steps, _, values = RunReader(child.path).scalars("loss")
    assert list(steps) == [0, 1, 2, 3, 4, 5]
    assert values[-1] == 40.0
    meta = json.loads((child.path / "run.json").read_text())
    assert meta["fork"] == {"run_id": parent.id, "step": 4}


def test_nonzero_rank_logs_only_with_all_ranks(monkeypatch, tmp_path):
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("TORCHELASTIC_RUN_ID", "job-42")
    monkeypatch.setenv("RANK", "0")
    r0 = nm.init("dist", name="ddp", capture_env=False)
    monkeypatch.setenv("RANK", "1")
    r1 = nm.init("dist", name="ddp", capture_env=False)
    assert r0.path == r1.path
    r0.log({"loss": 1.0}, step=0)
    r1.log({"loss": 2.0}, step=0)  # ignored: rank 1, not all_ranks
    r1.log({"grad_norm": 3.0}, step=0, all_ranks=True)
    r1.finish()
    r0.finish()
    files = sorted(os.listdir(r0.path))
    assert "events.r0.s0.log" in files and "events.r1.s0.log" in files
    reader = RunReader(r0.path)
    assert reader.metric_names(rank=1) == ["grad_norm"]
    assert reader.ranks() == [0, 1]


def test_nonzero_rank_without_shared_id_is_a_quiet_no_op(monkeypatch):
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("RANK", "1")
    with pytest.warns(RuntimeWarning, match="will not log"):
        run = nm.init("dist2", capture_env=False)
    run.log({"x": 1.0}, step=0, all_ranks=True)
    run.finish()
    assert not (run.project_dir / "runs").exists()


def test_rank_detection_fallbacks(monkeypatch):
    from nuboard._env import detect_dist

    monkeypatch.setenv("SLURM_PROCID", "3")
    monkeypatch.setenv("SLURM_NTASKS", "8")
    monkeypatch.setenv("SLURM_JOB_ID", "1234")
    d = detect_dist()
    assert (d.rank, d.world_size, d.shared_id) == (3, 8, "1234")
    monkeypatch.setenv("RANK", "5")
    assert detect_dist().rank == 5


def test_text_and_media(tmp_path):
    import numpy as np

    run = nm.init("p", capture_env=False)
    run.log_text("gen", "once upon a time", step=1)
    run.log_image("img", np.zeros((4, 5, 3), dtype=np.uint8), step=2, caption="black")
    run.log_html("page", "<b>hi</b>", step=3)
    run.finish()
    r = RunReader(run.path)
    assert r.texts()[0].text == "once upon a time"
    media = r.media()
    assert [m.key for m in media] == ["img", "page"]
    png = r.read_media(media[0])
    import io

    from PIL import Image

    assert Image.open(io.BytesIO(png)).size == (5, 4)
    assert r.read_media(media[1]) == b"<b>hi</b>"


def test_matplotlib_figure():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    run = nm.init("p", capture_env=False)
    run.log_figure("fig", fig, step=0)
    run.finish()
    r = RunReader(run.path)
    assert r.media()[0].meta["mime"] == "image/svg+xml"
    assert b"<svg" in r.read_media(r.media()[0])


def test_artifacts():
    src_dir = os.path.join(os.environ["NUBOARD_DIR"], "..", "data")
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, "a.txt"), "w") as f:
        f.write("hello")
    run = nm.init("p", capture_env=False)
    a1 = run.log_artifact("ds", src_dir, type="dataset", metadata={"rows": 1})
    a2 = run.log_artifact("ds", src_dir, type="dataset")
    assert (a1.version, a2.version) == (1, 2)
    assert a1.manifest["files"][0]["sha256"].startswith("2cf24dba")
    used = run.use_artifact("ds:v1")
    latest = run.use_artifact("ds")
    run.finish()
    assert used.version == 1 and latest.version == 2
    assert (used.files / "a.txt").read_text() == "hello"
    meta = json.loads((run.path / "run.json").read_text())
    assert meta["inputs"] == [{"artifact": "ds", "version": 1}, {"artifact": "ds", "version": 2}]
    assert len(meta["outputs"]) == 2
