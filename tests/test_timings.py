"""The viewer's timer summaries (`nuboard.timings`) and the Timing tab's endpoints."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard._writer import Writer
from nuboard.reader import RunReader
from nuboard.server import create_app
from nuboard.timing import COUNT
from nuboard.timings import spans, summarize, timer_keys

T0 = 1_700_000_000.0


@pytest.fixture
def two_ranks(tmp_path):
    """A 100-second run of 10 steps on 2 ranks, with exact spans.

    Each step: `train` (6 s on rank 0, 6.4 s on rank 1) with `data` summed inside
    it, then `val` (2 s); rank 0 then runs `ckpt` (0.3 s, 1.3 s at step 7).
    """
    run = nb.init("t", capture_env=False, system_metrics=False, capture_console=False, _started=T0)
    other = Writer(run.path, 1, run.session)
    run._ensure_writer()
    assert run._writer is not None

    for step in range(10):
        t = T0 + step * 10
        ckpt = 1.3 if step == 7 else 0.3
        acc = {"timing/data": 1.0, "timing/data" + COUNT: 50}
        run._writer.put_own_scalars(step, t, {"timing/train": 6.0, **acc})
        run._writer.put_own_scalars(step, t + 6.5, {"timing/val": 2.0})
        run._writer.put_own_scalars(step, t + 8.6, {"timing/ckpt": ckpt})
        other.put_own_scalars(step, t, {"timing/train": 6.4, **acc})
        other.put_own_scalars(step, t + 6.5, {"timing/val": 2.0})

    other.close("finished")
    run.finish(_ended=T0 + 100)
    meta = json.loads((run.path / "run.json").read_text("utf-8"))
    return run, RunReader(run.path), meta


def test_timer_keys_skip_hidden_counts(two_ranks):
    _, reader, _ = two_ranks
    keys = timer_keys(reader, "timing")
    assert keys == ["timing/ckpt", "timing/data", "timing/train", "timing/val"]


def test_summary_of_one_rank(two_ranks):
    _, reader, meta = two_ranks
    s = summarize(reader, meta, rank=0)
    assert (s["ranks"], s["rank"], s["wall"], s["steps"]) == ([0, 1], 0, 100.0, 10)
    rows = {t["name"]: t for t in s["timers"]}
    # tree order: a child right after its parent
    assert [t["name"] for t in s["timers"]] == ["train", "data", "val", "ckpt"]
    assert rows["data"]["parent"] == "train" and rows["data"]["depth"] == 1
    assert rows["data"]["accumulated"] and rows["data"]["calls"] == 500
    assert rows["ckpt"]["parent"] is None  # after val, not inside it
    assert rows["train"]["total"] == pytest.approx(60) and rows["train"]["share"] == pytest.approx(
        0.6
    )
    assert rows["ckpt"]["mean"] == pytest.approx(0.4) and rows["ckpt"]["p95"] > 0.3
    # untimed: the wall time no top-level timer covered (100 - 60 - 20 - 4)
    assert s["untimed"]["total"] == pytest.approx(16, abs=1e-3)
    # rank 0 waits for the slower rank 1 at the end of each train span
    assert s["waiting"]["mean"] == pytest.approx(0.4, abs=1e-3)
    assert len(rows["train"]["series"]["x"]) == 10


def test_summary_of_all_ranks_has_bands_and_findings(two_ranks):
    _, reader, meta = two_ranks
    s = summarize(reader, meta, rank=None)
    train = next(t for t in s["timers"] if t["name"] == "train")
    assert train["series"]["lo"][0] == pytest.approx(6.0)
    assert train["series"]["hi"][0] == pytest.approx(6.4)
    kinds = {f["kind"]: f for f in s["findings"]}
    assert kinds["slow_rank"]["rank"] == 1
    assert kinds["spike"]["timer"] == "ckpt" and kinds["spike"]["step"] == 7


def test_spans_of_one_step(two_ranks):
    _, reader, meta = two_ranks
    out = spans(reader, meta, 7)
    assert (out["step"], out["prev"], out["next"]) == (7, 6, 8)
    lanes = {lane["rank"]: {sp["name"]: sp for sp in lane["spans"]} for lane in out["ranks"]}
    assert lanes[0]["ckpt"]["start"] == pytest.approx(8.6) and lanes[0]["ckpt"]["seconds"] == 1.3
    assert lanes[0]["data"]["accumulated"] and lanes[0]["data"]["count"] == 50
    assert "ckpt" not in lanes[1]
    assert spans(reader, meta, None)["step"] == 9  # the last step by default


def test_endpoints(two_ranks, tmp_path):
    del two_ranks  # the run it wrote is what the app reads
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        assert c.get(f"/api/runs/{key}").json()["timing"] is True
        one = c.get(f"/api/runs/{key}/timing").json()
        assert one["rank"] == 0 and len(one["timers"]) == 4
        assert c.get(f"/api/runs/{key}/timing", params={"rank": "all"}).json()["rank"] is None
        assert c.get(f"/api/runs/{key}/timing", params={"rank": "x"}).status_code == 400
        assert c.get(f"/api/runs/{key}/timing/spans", params={"step": 3}).json()["step"] == 3
        assert c.get(f"/api/runs/{key}/timing/spans", params={"step": "x"}).status_code == 400
        assert c.get("/api/runs/nope/timing").status_code == 404


def test_a_run_without_timers_has_no_timing_tab(tmp_path):
    with nb.init("t", capture_env=False, system_metrics=False, capture_console=False) as run:
        run.add_scalar("loss", 1.0, step=0)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        assert c.get(f"/api/runs/{key}").json()["timing"] is False


def test_a_renamed_prefix_is_read_from_run_json(tmp_path):
    with nb.init(
        "t", capture_env=False, system_metrics=False, capture_console=False, timing_prefix="perf"
    ) as run:
        with run.timer("epoch", step=0):
            pass

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        rec = c.get("/api/runs").json()["runs"][0]
        assert rec["prefixes"] == {"system": "system", "timing": "perf"}
        out = c.get(f"/api/runs/{rec['key']}/timing").json()
        assert out["prefix"] == "perf" and out["timers"][0]["key"] == "perf/epoch"
