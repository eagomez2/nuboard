from __future__ import annotations

import numpy as np
import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard.selection import (
    PickError,
    checkpoint_step,
    complete_steps,
    delete_pick,
    pareto_mask,
    read_picks,
    save_pick,
)
from nuboard.server import create_app


def _brute_front(values, directions):
    sign = np.array([1.0 if d == "min" else -1.0 for d in directions])
    x = values * sign
    return np.array(
        [
            not any((x[j] <= x[i]).all() and (x[j] < x[i]).any() for j in range(len(x)) if j != i)
            for i in range(len(x))
        ]
    )


def test_a_step_counts_only_when_every_metric_was_logged_there():
    series = {
        "loss": (np.arange(0, 300, 1), np.linspace(2, 1, 300)),  # every step
        "acc": (np.array([100, 200, 300]), np.array([0.5, 0.6, 0.7])),  # every 100
    }
    steps, values, incomplete = complete_steps(series, ["acc", "loss"])
    assert steps.tolist() == [100, 200]  # loss has no step 300
    assert values[:, 0].tolist() == [0.5, 0.6]
    assert values[1, 1] == pytest.approx(series["loss"][1][200])
    assert incomplete == 299  # every other step that has one of them

    # a metric the run never logged leaves nothing complete
    assert len(complete_steps(series, ["acc", "ece"])[0]) == 0


def test_a_step_logged_twice_keeps_its_last_value_and_non_finite_steps_are_left_out():
    series = {
        "a": (np.array([1, 2, 2, 3]), np.array([1.0, 2.0, 2.5, np.nan])),
        "b": (np.array([1, 2, 3]), np.array([0.1, 0.2, 0.3])),
    }
    steps, values, _ = complete_steps(series, ["a", "b"])
    assert steps.tolist() == [1, 2]
    assert values[:, 0].tolist() == [1.0, 2.5]


def test_the_shortlist_is_the_pareto_front():
    rng = np.random.default_rng(3)

    for n, dirs in ((1, ["max"]), (50, ["max", "min"]), (700, ["max", "min", "min"])):
        values = rng.normal(size=(n, len(dirs))).round(1)  # rounding makes ties
        assert pareto_mask(values, dirs).tolist() == _brute_front(values, dirs).tolist()

    # equal rows do not beat each other
    assert pareto_mask(np.array([[1.0, 1.0], [1.0, 1.0], [0.0, 2.0]]), ["max", "min"]).tolist() == [
        True,
        True,
        False,
    ]
    assert pareto_mask(np.empty((0, 2)), ["min", "min"]).tolist() == []


def test_a_checkpoint_says_its_step_or_it_is_guessed_from_when_it_was_made():
    steps = np.array([100, 200, 300])
    times = np.array([10.0, 20.0, 30.0])
    assert checkpoint_step({"step": 250}, steps, times) == (250, True)
    assert checkpoint_step({"metadata": {"step": 120}}, steps, times) == (120, True)
    assert checkpoint_step({"created": 21.0}, steps, times) == (200, False)
    assert checkpoint_step({"created": 5.0}, steps, times) == (None, False)
    assert checkpoint_step({"metadata": {"step": True}}, steps, times) == (None, False)


def test_picks_are_saved_replaced_and_deleted(tmp_path):
    first = save_pick(tmp_path, {"run": "r1", "step": 10, "note": " best ", "metrics": {"a": 1}})
    assert first["note"] == "best" and first["checkpoint"] is None
    second = save_pick(
        tmp_path,
        {"run": "r2", "step": 20, "checkpoint": {"artifact": "model", "version": 3}},
    )
    assert [p["run"] for p in read_picks(tmp_path)] == ["r1", "r2"]

    edited = save_pick(tmp_path, {"id": first["id"], "run": "r1", "step": 10, "note": "why"})
    assert edited["id"] == first["id"] and edited["note"] == "why" and "edited" in edited
    assert [p["note"] for p in read_picks(tmp_path)] == ["why", ""]

    assert delete_pick(tmp_path, second["id"]) is True
    assert delete_pick(tmp_path, second["id"]) is False
    assert [p["run"] for p in read_picks(tmp_path)] == ["r1"]

    with pytest.raises(PickError):
        save_pick(tmp_path, {"run": "r1", "step": 1.5})

    with pytest.raises(PickError):
        save_pick(tmp_path, {"run": "", "step": 1})


@pytest.fixture
def client(tmp_path):
    (tmp_path / "ckpt.bin").write_bytes(b"x")

    for name, peak, ece in (("long", 0.84, 0.02), ("short", 0.80, 0.01), ("worse", 0.70, 0.05)):
        with nb.init("vit", run_name=name, capture_env=False) as run:
            for s in range(0, 3001, 100):
                run.add_scalar("train/loss", 2 - s / 3000, step=s)

                if s and s % 1000 == 0:
                    run.add_scalar({"val/acc": peak * s / 3000, "val/ece": ece + s / 1e6}, step=s)

            run.add_artifact("model", tmp_path / "ckpt.bin", type="checkpoint", step=2000)

    with nb.init("vit", run_name="no-ece", capture_env=False) as run:
        run.add_scalar("val/acc", 0.9, step=1000)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        yield c


def test_steps_are_scored_and_runs_missing_a_metric_are_listed(client):
    runs = client.get("/api/runs").json()["runs"]
    keys = ",".join(r["key"] for r in runs)
    got = client.get(
        "/api/steps", params={"runs": keys, "m": ["val/acc", "val/ece"], "d": ["max", "min"]}
    ).json()

    assert got["complete"] == 9  # 3 runs × steps 1000, 2000, 3000
    assert got["coverage"] == {"val/acc": 4, "val/ece": 3}
    assert [(u["name"], u["missing"]) for u in got["unranked"]] == [("no-ece", ["val/ece"])]

    names = [r["name"] for r in got["runs"]]
    front = [(names[i], s) for i, s in zip(got["front"]["run"], got["front"]["step"])]
    # best accuracy first; "worse" never wins on anything; the lowest ECE is at short's 1000
    assert front[0] == ("long", 3000)
    assert ("short", 1000) in front and not any(n == "worse" for n, _ in front)
    assert got["front_count"] == len(front)
    assert got["front_count"] + got["others_count"] == 9
    assert len(got["front"]["values"]) == 2

    long = next(r for r in got["runs"] if r["name"] == "long")
    assert long["checkpoints"] == [
        {
            "artifact": "model",
            "version": 1,
            "project": "vit",
            "type": "checkpoint",
            "step": 2000,
            "exact": True,
            "row": 2000,
        }
    ]

    assert client.get("/api/steps", params={"runs": keys, "m": ["val/acc"]}).status_code == 400
    assert (
        client.get("/api/steps", params={"runs": keys, "m": ["a", "a"], "d": ["min", "min"]})
    ).status_code == 400


def test_picks_round_trip(client):
    run = client.get("/api/runs").json()["runs"][0]
    pick = {"run": run["id"], "step": 2000, "note": "good", "metrics": {"val/acc": 0.5}}
    saved = client.post("/api/picks", json={"project": "vit", "pick": pick}).json()["pick"]
    listed = client.get("/api/picks", params={"project": "vit"}).json()["picks"]
    assert [(p["id"], p["key"], p["project"]) for p in listed] == [(saved["id"], run["key"], "vit")]
    assert client.post("/api/picks", json={"project": "nope", "pick": pick}).status_code == 404
    assert client.post("/api/picks", json={"project": "vit", "pick": {}}).status_code == 400
    gone = client.post("/api/picks", json={"project": "vit", "delete": saved["id"]}).json()
    assert gone == {"deleted": saved["id"], "existed": True}
    assert client.get("/api/picks").json()["picks"] == []
