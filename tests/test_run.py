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

import numpy as np
import pytest

import nuboard as nb
from nuboard._media import histogram_bytes, points_bytes, pr_curve_bytes
from nuboard.catalog import effective_status
from nuboard.jobs import read_meta
from nuboard.reader import RunReader


def test_init_creates_self_contained_folder(tmp_path):
    with nb.init("proj", name="base line:1", config={"lr": 1e-3, "opt": {"b": [0.9, 0.95]}}) as run:
        run.add_scalar({"loss": 1.0, "nested": {"acc": 0.5}}, step=0)

    assert run.path.parent.parent == tmp_path / "exp" / "proj"
    assert re.fullmatch(r"\d{8}-\d{4}_base-line-1_[a-z2-9]{6}", run.id)
    assert ":" not in run.id
    meta = json.loads((run.path / "run.json").read_text("utf-8"))
    assert meta["format_version"] == nb.FORMAT_VERSION
    assert meta["status"] == "finished"
    assert meta["config"]["opt"]["b"] == [0.9, 0.95]
    assert meta["summary"]["nested/acc"]["last"] == 0.5
    assert {"requirements.txt", "command.txt"} <= set(os.listdir(run.path / "files"))
    assert "config.json" not in os.listdir(run.path / "files")

    for f in run.path.rglob("*"):  # nothing points outside the folder
        if f.is_file() and f.suffix in (".json", ".txt"):
            assert str(tmp_path / "exp" / "other") not in f.read_text("utf-8", errors="ignore")


def test_add_file_copies_files_and_folders(tmp_path):
    (tmp_path / "config.yaml").write_text("lr: 0.001\n", "utf-8")
    hydra = tmp_path / ".hydra"
    (hydra / "sub").mkdir(parents=True)
    (hydra / "config.yaml").write_text("model: vit\n", "utf-8")
    (hydra / "sub" / "overrides.yaml").write_text("- lr=0.1\n", "utf-8")
    (hydra / "empty").mkdir()

    with nb.init("files", capture_env=False) as run:
        files = run.path / "files"
        assert run.add_file(tmp_path / "config.yaml") == files / "config.yaml"
        assert run.add_file(tmp_path / "config.yaml", "cfg/train.yaml") == files / "cfg/train.yaml"
        assert run.add_file(hydra, "hydra") == files / "hydra"
        assert run.add_file(hydra) == files / ".hydra"
        run.add_file(tmp_path / "config.yaml")  # overwrites in place

    assert (files / "config.yaml").read_text("utf-8") == "lr: 0.001\n"
    assert (files / "cfg" / "train.yaml").read_text("utf-8") == "lr: 0.001\n"
    assert (files / "hydra" / "config.yaml").read_text("utf-8") == "model: vit\n"
    assert (files / "hydra" / "sub" / "overrides.yaml").read_text("utf-8") == "- lr=0.1\n"
    assert (files / ".hydra" / "sub" / "overrides.yaml").exists()
    assert not [p for p in files.rglob("*.tmp")]


def test_add_file_rejects_unsafe_names(tmp_path):
    (tmp_path / "a.toml").write_text("x = 1\n", "utf-8")
    run = nb.init("files", capture_env=False)

    for bad in ("../x", "a/../../x", str(tmp_path / "abs.toml"), "/abs.toml", "C:\\x", "", "."):
        with pytest.raises(ValueError):
            run.add_file(tmp_path / "a.toml", bad)

    with pytest.raises(FileNotFoundError):
        run.add_file(tmp_path / "missing.yaml")

    run.finish()
    assert not (run.path.parent / "x").exists()


def test_log_values_and_steps(tmp_path):
    run = nb.init("p", capture_env=False)
    run.add_scalar({"a": 1})  # step 0
    run.add_scalar({"a": 2})  # step 1
    run.add_scalar({"a": 3}, step=10)
    run.add_scalar({"a": 4})  # step 11
    import numpy as np

    run.add_scalar({"np": np.float32(1.5), "flag": True, "nan": float("nan")}, step=12)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run.add_scalar({"bad": "text"}, step=13)
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
    run = nb.init("p", capture_env=False, compact=False)
    data = {f"metric_{i}": float(i) for i in range(50)}
    n = 5000
    t0 = time.perf_counter()

    for step in range(n):
        run.add_scalar(data, step=step)

    per_call = (time.perf_counter() - t0) / n
    run.finish()
    assert per_call < 50e-6, f"log() took {per_call * 1e6:.1f} µs"


def test_exception_marks_run_crashed():
    with pytest.raises(RuntimeError):
        with nb.init("p", capture_env=False) as run:
            run.add_scalar({"x": 1}, step=0)
            raise RuntimeError("boom")

    meta = json.loads((run.path / "run.json").read_text())
    assert meta["status"] == "crashed"
    assert "boom" in meta["exit"]["error"]


def test_process_killed_without_finish_keeps_flushed_data(tmp_path):
    script = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(os.path.join(os.path.dirname(nb.__file__), ".."))!r})
        import nuboard as nb
        run = nb.init("p", dir={str(tmp_path / "crash")!r}, capture_env=False, flush_interval=0.05)
        for i in range(1000):
            run.add_scalar({{"loss": 1.0 / (i + 1)}}, step=i)
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
    run = nb.init("p", name="r", capture_env=False)

    for s in range(10):
        run.add_scalar({"loss": 10.0 - s}, step=s)

    run.finish()

    with pytest.raises(FileExistsError):
        nb.init("p", run_id=run.id, capture_env=False)

    again = nb.init("p", run_id=run.id, resume="must", capture_env=False)
    assert again.session == 1

    for s in range(5, 8):  # restarted from a checkpoint at step 5
        again.add_scalar({"loss": 100.0 + s}, step=s)

    again.finish()
    steps, _, values = RunReader(run.path).scalars("loss")
    assert list(steps) == [0, 1, 2, 3, 4, 5, 6, 7]
    assert list(values[5:]) == [105.0, 106.0, 107.0]
    meta = json.loads((run.path / "run.json").read_text())
    assert len(meta["sessions"]) == 2

    with pytest.raises(FileNotFoundError):
        nb.init("p", run_id="nope", resume="must", capture_env=False)

    created = nb.init("p", run_id="20250101-0000_fresh_abcdef", resume="auto", capture_env=False)
    created.finish()
    assert created.path.name == "20250101-0000_fresh_abcdef"


def test_fork_copies_history_up_to_step():
    parent = nb.init("p", capture_env=False)

    for s in range(10):
        parent.add_scalar({"loss": float(s)}, step=s)

    parent.finish()
    child = nb.init("p", fork_from=(parent.id, 4), capture_env=False)
    child.add_scalar({"loss": 40.0}, step=5)
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
    r0 = nb.init("dist", name="ddp", capture_env=False)
    monkeypatch.setenv("RANK", "1")
    r1 = nb.init("dist", name="ddp", capture_env=False)
    assert r0.path == r1.path
    r0.add_scalar({"loss": 1.0}, step=0)
    r1.add_scalar({"loss": 2.0}, step=0)  # ignored: rank 1, not all_ranks
    r1.add_scalar({"grad_norm": 3.0}, step=0, all_ranks=True)
    (tmp_path / "config.yaml").write_text("lr: 0.001\n", "utf-8")
    assert r1.add_file(tmp_path / "config.yaml") is None  # only rank 0 copies
    assert not (r1.path / "files" / "config.yaml").exists()
    r1.finish()
    r0.finish()
    files = sorted(os.listdir(r0.path))
    assert "events.r0.s0.log" in files and "events.r1.s0.log" in files
    reader = RunReader(r0.path)
    assert reader.scalar_names(rank=1) == ["grad_norm"]
    assert reader.ranks() == [0, 1]


def test_nonzero_rank_without_shared_id_is_a_quiet_no_op(monkeypatch):
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("RANK", "1")

    with pytest.warns(RuntimeWarning, match="will not log"):
        run = nb.init("dist2", capture_env=False)

    run.add_scalar({"x": 1.0}, step=0, all_ranks=True)
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

    run = nb.init("p", capture_env=False)
    run.add_text("gen", "once upon a time", step=1)
    run.add_image("img", np.zeros((4, 5, 3), dtype=np.uint8), step=2, caption="black")
    run.add_html("page", "<b>hi</b>", step=3)
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


def test_point_clouds(tmp_path):
    import numpy as np

    run = nb.init("p", capture_env=False)
    xyz = np.arange(12, dtype="float64").reshape(4, 3)
    run.add_point_cloud("scan", xyz, step=1, colors=np.full((4, 3), 0.5), caption="toy")
    run.add_point_cloud("plain", [(0, 0, 0), (1, 2, 3)], step=1)
    run.add_point_cloud("named", xyz, step=1, axes=("x (m)", "y (m)", "z (m)"))
    run.add_point_cloud("shown", xyz, step=1, axes=True)

    with pytest.raises(ValueError, match="three names"):
        run.add_point_cloud("bad", xyz, axes=("x", "y"))

    with pytest.raises(ValueError, match="shape"):
        points_bytes(np.zeros((3, 2)))

    with pytest.raises(ValueError, match="rows"):
        points_bytes(xyz, colors=[(1, 2, 3)])

    run.finish()
    r = RunReader(run.path)
    scan, plain, named, shown = r.media()
    assert scan.meta["mime"] == "application/x-nuboard-points"
    assert scan.meta["points"] == 4 and scan.meta["colors"] and scan.meta["caption"] == "toy"
    data = r.read_media(scan)
    assert np.frombuffer(data[:48], "<f4").tolist() == list(range(12))
    assert data[48:] == bytes([128] * 12)
    assert np.frombuffer(r.read_media(plain), "<f4").tolist() == [0, 0, 0, 1, 2, 3]
    assert plain.meta["colors"] is False and "axes" not in plain.meta
    assert named.meta["axes"] == ["x (m)", "y (m)", "z (m)"]
    assert shown.meta["axes"] == ["x", "y", "z"]


def test_histograms():
    import numpy as np

    run = nb.init("h", capture_env=False)
    weights = np.array([[0.0, 1.0], [1.0, 3.0], [np.nan, 2.0]])
    run.add_histogram("w", weights, step=3, bins=3)
    weights[:] = 0  # the call copied its input
    run.add_histogram("plain", [1, 2, 2, 3, 10], step=3, bins=[0, 2, 4], weights=[1, 1, 1, 2, 5])

    with pytest.raises(ValueError, match="increasing"):
        histogram_bytes([1.0], bins=[1, 1])

    run.finish()
    r = RunReader(run.path)
    w, plain = r.media()
    assert w.meta["kind"] == "histogram" and w.meta["bins"] == 3 and w.meta["count"] == 5
    data = json.loads(r.read_media(w))
    assert data["edges"] == [0, 1, 2, 3] and data["counts"] == [1, 2, 2]
    assert data["nonfinite"] == 1 and data["min"] == 0 and data["max"] == 3
    assert data["mean"] == pytest.approx(1.4)
    assert data["std"] == pytest.approx(np.std([0, 1, 1, 3, 2]))

    # pure Python, with weights: 10 lies outside the edges
    data = json.loads(r.read_media(plain))
    assert data["counts"] == [1, 4] and data["outside"] == 5 and data["count"] == 10
    assert data["mean"] == pytest.approx((1 + 2 + 2 + 6 + 50) / 10)


def test_pr_curves():
    import numpy as np

    run = nb.init("p", capture_env=False)
    labels = np.array([1, 0, 1, 1, 0])
    scores = np.array([0.9, 0.8, 0.4, 0.1, 0.05])
    run.add_pr_curve("pr/cat", labels, scores, step=2, num_thresholds=5)
    labels[:] = 0  # the call copied its inputs

    with pytest.raises(ValueError, match="same"):
        pr_curve_bytes([1, 0], [0.5])

    run.finish()
    r = RunReader(run.path)
    (item,) = r.media()
    assert item.meta["kind"] == "pr" and item.meta["positives"] == 3
    data = json.loads(r.read_media(item))
    assert data["tp"] == [3, 2, 1, 1, 0] and data["fp"] == [2, 1, 1, 1, 0]
    assert data["fn"] == [0, 1, 2, 2, 3] and data["tn"] == [0, 1, 1, 1, 2]
    assert data["precision"][2] == 0.5 and data["recall"][1] == pytest.approx(2 / 3, abs=1e-6)
    assert data["precision"][-1] == 1.0  # nothing predicted positive


def test_tables_with_media_cells(tmp_path):
    import numpy as np

    run = nb.init("t", capture_env=False)
    wav = np.zeros(800)
    rows = [
        {"file": "a", "pesq": np.float32(2.5), "ok": True, "clip": nb.Audio(wav, sample_rate=8000)},
        {"file": "b", "pesq": float("nan"), "ok": False, "note": "loud"},
    ]
    run.add_table("eval/samples", rows, step=3)
    run.add_table("eval/samples", {"file": ["a", "b"], "pesq": [2.7, 1.9]}, step=4)

    with pytest.raises(ValueError, match="row_id"):
        run.add_table("eval/samples", rows, row_id="nope")

    run.finish()
    r = RunReader(run.path)
    cell, first, _ = r.media()
    assert cell.key == "eval/samples#0/clip" and cell.meta["kind"] == "cell"
    assert cell.meta["mime"] == "audio/wav" and cell.step == 3
    data = json.loads(r.read_media(first))
    types = {c["name"]: c["type"] for c in data["columns"]}
    assert types == {
        "file": "text",
        "pesq": "number",
        "ok": "bool",
        "clip": "audio",
        "note": "text",
    }
    assert data["id"] == "file" and first.meta["rows"] == 2
    assert data["rows"][1] == ["b", None, False, None, "loud"]
    assert data["rows"][0][3] == {"$cell": "eval/samples#0/clip"}
    handle = nb.load("t").runs()[0]
    assert handle.table("eval/samples") == [{"file": "a", "pesq": 2.7}, {"file": "b", "pesq": 1.9}]
    assert handle.table("eval/samples", step=3)[0]["pesq"] == pytest.approx(2.5)
    assert handle.table("nothing") == []


def test_matplotlib_figure():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    run = nb.init("p", capture_env=False)
    run.add_figure("fig", fig, step=0)
    run.finish()
    r = RunReader(run.path)
    assert r.media()[0].meta["mime"] == "image/svg+xml"
    assert b"<svg" in r.read_media(r.media()[0])


def test_audio_arrays_files_and_bytes(tmp_path):
    import io
    import wave

    import numpy as np

    t = np.arange(8000) / 16000
    mono = np.sin(2 * np.pi * 440 * t).astype("float32")
    stereo = np.stack([mono, -mono])  # (channels, samples)
    run = nb.init("p", capture_env=False)
    run.add_audio("mono", mono, step=0, sample_rate=16000, caption="a440")
    run.add_audio("stereo", stereo, step=0, sample_rate=16000)
    path = tmp_path / "clip.flac"
    path.write_bytes(b"fLaC" + b"\0" * 64)
    run.add_audio("file", path, step=1)
    run.finish()
    r = RunReader(run.path)
    m, st, f = r.media()
    assert m.meta == {
        "mime": "audio/wav",
        "kind": "audio",
        "caption": "a440",
        "sample_rate": 16000,
        "channels": 1,
        "duration": 0.5,
    }

    with wave.open(io.BytesIO(r.read_media(m))) as w:
        frames = np.frombuffer(w.readframes(8000), "<i2")
        assert (w.getsampwidth(), w.getnframes()) == (2, 8000)

    assert abs(frames.max() - 32767) <= 1
    assert st.meta["channels"] == 2 and st.meta["duration"] == 0.5
    assert f.meta["mime"] == "audio/flac" and r.read_media(f).startswith(b"fLaC")


def test_audio_needs_a_sample_rate_for_arrays():
    import numpy as np

    from nuboard._media import audio_bytes

    with pytest.raises(ValueError, match="sample_rate"):
        audio_bytes(np.zeros(10), None)

    with pytest.raises(ValueError, match="unrecognized"):
        audio_bytes(b"not audio", None)


def test_figure_spec_dicts():
    from nuboard._media import figure_bytes

    vega = {"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "mark": "bar"}
    plotly = {"data": [{"type": "bar", "y": [1, 2]}], "layout": {}}
    assert figure_bytes(vega)[1] == "application/vnd.vegalite+json"
    assert figure_bytes(plotly)[1] == "application/vnd.plotly.v1+json"

    with pytest.raises(TypeError):
        figure_bytes({"mark": "bar"})


def test_artifacts():
    src_dir = os.path.join(os.environ["NUBOARD_DIR"], "..", "data")
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "a.txt"), "w") as f:
        f.write("hello")

    run = nb.init("p", capture_env=False)
    a1 = run.add_artifact("ds", src_dir, type="dataset", metadata={"rows": 1})
    a2 = run.add_artifact("ds", src_dir, type="dataset")
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


def test_reference_artifacts_across_projects(tmp_path):
    data = tmp_path / "store" / "fineweb"
    data.mkdir(parents=True)
    (data / "a.txt").write_text("hello")
    shared = nb.add_artifact("datasets", "fineweb", data, type="dataset", reference=True)
    assert shared.manifest["producer_run"] is None
    assert shared.manifest["reference"] == str(data.resolve())
    assert "sha256" not in shared.manifest["files"][0]
    assert not (shared.path / "files").exists()  # nothing copied
    hashed = nb.add_artifact("datasets", "fineweb", data / "a.txt", reference=True, checksum=True)
    assert hashed.manifest["files"][0]["sha256"].startswith("2cf24dba")
    assert hashed.files == data.resolve()  # a file's folder, as for copies

    with nb.init("llm", capture_env=False) as run:
        used = run.use_artifact("datasets/fineweb:v1")
        run.add_artifact("registry/model", data / "a.txt", type="checkpoint")

    assert (used.files / "a.txt").read_text() == "hello"
    meta = json.loads((run.path / "run.json").read_text())
    entry = {"artifact": "fineweb", "version": 1, "project": "datasets"}
    assert meta["inputs"] == [{**entry, "project_path": "../datasets"}]
    assert meta["outputs"][0]["project"] == "registry"
    assert nb.get_artifact("registry/model").manifest["producer_run"] == run.id

    (data / "a.txt").write_text("changed!")

    with pytest.warns(UserWarning, match=r"fineweb:v1: changed: a\.txt"):
        nb.get_artifact("datasets/fineweb:v1")

    (data / "a.txt").unlink()
    assert nb.get_artifact("datasets/fineweb:v1").verify() == ["missing: a.txt"]


def test_reference_relative_to_each_machines_data_folder(tmp_path, monkeypatch):
    for machine in ("laptop", "cluster"):
        (tmp_path / machine / "fw").mkdir(parents=True)
        (tmp_path / machine / "fw" / "a.txt").write_text("hello")

    monkeypatch.setenv("NUBOARD_DATA_DIR", str(tmp_path / "laptop"))
    art = nb.add_artifact("datasets", "fw", tmp_path / "laptop" / "fw", reference=True)
    assert art.manifest["reference"] == "${NUBOARD_DATA_DIR}/fw"
    one = nb.add_artifact("datasets", "fw", tmp_path / "laptop" / "fw" / "a.txt", reference=True)
    assert one.manifest["reference"] == "${NUBOARD_DATA_DIR}/fw/a.txt"
    monkeypatch.setenv("NUBOARD_DATA_DIR", str(tmp_path / "cluster"))
    assert nb.get_artifact("datasets/fw:v2").files == tmp_path / "cluster" / "fw"
    assert nb.get_artifact("datasets/fw:v1").verify() == []  # another copy, other mtimes
    monkeypatch.setenv("HOME", str(tmp_path / "laptop"))
    monkeypatch.setenv("NUBOARD_DATA_DIR", "~")  # as a shell profile may leave it
    home = nb.add_artifact("datasets", "fw", "~/fw", reference=True)
    assert home.manifest["reference"] == "${NUBOARD_DATA_DIR}/fw"
    assert home.files == tmp_path / "laptop" / "fw"
    # any variable works when written in the path
    monkeypatch.setenv("DATA", str(tmp_path / "laptop"))
    own = nb.add_artifact("datasets", "fw", "${DATA}/fw", reference=True)
    assert own.manifest["reference"] == "${DATA}/fw"
    monkeypatch.delenv("DATA")

    with pytest.warns(UserWarning, match="DATA is not set"):
        nb.get_artifact("datasets/fw:v4")


def test_add_scalar_takes_one_value_or_several(tmp_path):
    run = nb.init("p", dir=tmp_path, capture_env=False)
    run.add_scalar("loss", 1.0, step=0)
    run.add_scalar({"loss": 0.5, "train": {"acc": 0.7}}, step=1)
    run.add_scalar({"loss": 0.25}, 2)  # a positional value is the step
    run.add_scalar("loss", 0.2)  # the next step
    run.add_scalar({"loss": 0.1})  # the same, under its old name

    with pytest.raises(TypeError, match="needs a value"):
        run.add_scalar("loss")

    assert not hasattr(run, "log")  # removed in 0.13; add_scalar is the one way

    run.finish()
    reader = RunReader(run.path)
    steps, _, values = reader.scalars("loss")
    assert steps.tolist() == [0, 1, 2, 3, 4]
    assert values.tolist() == [1.0, 0.5, 0.25, 0.2, 0.1]
    assert reader.scalar_names() == ["loss", "train/acc"]


def test_video_arrays_batches_and_files(tmp_path):
    import io

    import numpy as np
    from PIL import Image

    from nuboard._media import video_bytes, video_frames

    run = nb.init("p", capture_env=False)
    clip = np.zeros((6, 8, 10, 3), dtype=np.uint8)
    clip[:, :, :, 0] = np.arange(6)[:, None, None] * 40
    run.add_video("clip", clip, step=1, fps=12, caption="red ramp")
    run.add_video("batch", np.ones((3, 4, 3, 8, 10), dtype="float32"), step=1)  # N,T,C,H,W
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(16))
    run.add_video("file", mp4, step=1)

    with pytest.raises(ValueError, match="unrecognized video"):
        video_bytes(b"hello")

    run.finish()
    r = RunReader(run.path)
    clip_m, batch_m, file_m = r.media()
    assert clip_m.meta["mime"] == "image/apng" and clip_m.meta["kind"] == "video"
    assert clip_m.meta["frames"] == 6 and clip_m.meta["fps"] == 12
    assert clip_m.meta["caption"] == "red ramp"
    img = Image.open(io.BytesIO(r.read_media(clip_m)))
    assert img.n_frames == 6 and img.size == (10, 8)
    img.seek(5)
    assert img.convert("RGB").getpixel((0, 0)) == (200, 0, 0)
    assert (batch_m.meta["width"], batch_m.meta["height"]) == (20, 16)  # a 2x2 grid
    assert file_m.meta["mime"] == "video/mp4"
    assert video_frames(np.zeros((2, 3, 5, 6))).shape == (2, 5, 6, 3)  # T,C,H,W


def test_torch_tensors_are_copied_on_the_calling_thread():
    torch = pytest.importorskip("torch")
    import numpy as np

    run = nb.init("p", capture_env=False)
    img = torch.zeros(3, 4, 5)
    run.add_image("img", img, step=0)
    img.fill_(1.0)  # changing the buffer after the call must not change what was logged
    run.add_scalar("loss", torch.tensor(0.5), step=0)
    run.add_scalar({"lr": torch.tensor(1e-3, dtype=torch.bfloat16)}, step=0)
    run.add_histogram("w", torch.randn(100, dtype=torch.bfloat16), step=0)
    run.add_point_cloud("pc", torch.arange(12.0).reshape(4, 3), step=0)
    run.add_audio("a", torch.zeros(800), step=0, sample_rate=8000)
    run.add_video("v", torch.rand(2, 4, 3, 6, 6), step=0)  # N,T,C,H,W
    run.finish()

    import io

    from PIL import Image

    r = RunReader(run.path)
    assert r.scalars("loss")[2].tolist() == [0.5]
    assert abs(r.scalars("lr")[2][0] - 1e-3) < 1e-5
    by_key = {m.key: m for m in r.media()}
    assert set(by_key) == {"img", "w", "pc", "a", "v"}
    pixels = np.asarray(Image.open(io.BytesIO(r.read_media(by_key["img"]))))
    assert pixels.max() == 0
    assert np.frombuffer(r.read_media(by_key["pc"]), "<f4").tolist() == list(range(12))
    assert by_key["v"].meta["frames"] == 4


def test_add_scalar_band_needs_both_bounds_and_a_single_name():
    import numpy as np

    run = nb.init("p", capture_env=False)

    with pytest.raises(TypeError):
        run.add_scalar("loss", 1.0, low=0.5)

    with pytest.raises(TypeError):
        run.add_scalar({"loss": 1.0}, low=0.5, high=2.0)

    run.add_scalar("loss", 1.0, step=0, low=0.5, high=2.0)
    run.add_scalar("loss", 0.8, step=1)  # a point without a band
    run.finish()
    reader = RunReader(run.path)
    assert reader.scalar_names() == ["loss"]
    assert len(reader.scalar_names(bands=True)) == 3
    low, high = reader.bounds("loss")
    np.testing.assert_array_equal(low, [0.5, np.nan])
    np.testing.assert_array_equal(high, [2.0, np.nan])
    assert set(reader.meta()["summary"]) == {"loss"}


def test_add_scalar_baseline_is_saved_and_replaced():
    run = nb.init("p", capture_env=False)

    with pytest.raises(TypeError):
        run.add_scalar_baseline("val/pesq", 2.3, high=2.5)

    with pytest.raises(TypeError):
        run.add_scalar_baseline({"val/pesq": 2.3}, low=2.1, high=2.5)

    with pytest.raises(ValueError):
        run.add_scalar_baseline("val/pesq", float("nan"))

    run.add_scalar_baseline("val/pesq", 2.3, low=2.1, high=2.5)
    run.add_scalar_baseline({"val/stoi": 0.8, "val/pesq": 2.4})
    saved = json.loads((run.path / "run.json").read_text())["baselines"]
    assert saved == {"val/pesq": {"value": 2.4}, "val/stoi": {"value": 0.8}}
    run.finish()


def test_a_helper_job_logs_into_the_run_without_touching_its_state():
    train = nb.init("p", name="big", capture_env=False, system_metrics=False)
    train.add_scalar({"train/loss": 1.0}, step=0)
    train.flush()
    train._on_heartbeat()  # puts the summary in run.json

    with pytest.raises(FileNotFoundError, match="leave out job"):
        nb.init("p", run_id="20250101-0000_nope_abcdef", job="eval")

    ev = nb.init("p", run_id=train.id, job="eval", capture_env=False, system_metrics=False)
    assert ev.job == "eval" and ev.path == train.path

    with pytest.raises(RuntimeError, match="already running"):
        nb.init("p", run_id=train.id, job="eval", capture_env=False)

    with pytest.warns(UserWarning, match="train/loss is also logged by the main job"):
        ev.add_scalar({"train/loss": 5.0}, step=99)

    for epoch in range(3):
        train.add_scalar({"train/loss": 1.0 / (epoch + 1)}, step=epoch * 10)
        ev.add_scalar({"eval/score": float(epoch)}, step=epoch * 10)

    ev.add_image("eval/sample", np.zeros((4, 4, 3), np.uint8), step=0)
    ev.add_scalar_baseline("eval/score", 0.5)
    ev.finish()  # the main job still runs: its status is untouched
    main = json.loads((train.path / "run.json").read_text())
    assert main["status"] == "running" and "eval/score" not in main["summary"]
    assert "baselines" not in main
    job = json.loads((train.path / "jobs" / "eval.json").read_text())
    assert job["status"] == "finished" and "eval/score" in job["summary"]
    assert not (train.path / "data.parquet").exists()  # the main job compacts when it ends

    train.flush()
    train._on_heartbeat()
    meta = read_meta(train.path)
    assert meta is not None and meta["status"] == "running"
    assert [j["job"] for j in meta["jobs"]] == ["eval"]
    assert meta["summary"]["eval/score"]["last"] == 2.0
    assert meta["summary"]["train/loss"]["last"] == pytest.approx(1 / 3)  # the main job wins
    assert meta["baselines"]["eval/score"]["value"] == 0.5

    reader = RunReader(train.path)
    assert list(reader.scalars("eval/score")[0]) == [0, 10, 20]
    (img,) = reader.media("eval/sample")
    assert img.pack.endswith(f".s{ev.session}.pack")
    assert reader.read_media(img)[:4] == b"\x89PNG"

    again = nb.init("p", run_id=train.id, job="eval", capture_env=False, system_metrics=False)
    assert again.session > ev.session  # a restart continues the job
    again.finish()
    train.finish()
    assert len(json.loads((train.path / "jobs" / "eval.json").read_text())["sessions"]) == 2
    assert (train.path / "data.parquet").exists()  # the last job to end compacts
    after = RunReader(train.path)
    assert after.parquet is not None
    assert list(after.scalars("eval/score")[0]) == [0, 10, 20]
