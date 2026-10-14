from __future__ import annotations

import json

import pyarrow as pa
import pytest
from starlette.testclient import TestClient

import nuboard as nm
from nuboard.server import create_app


@pytest.fixture
def client(tmp_path):
    for lr in (1e-3, 1e-4):
        for seed in (1, 2):
            with nm.init(
                "sweep",
                name=f"lr{lr}-s{seed}",
                config={"lr": lr, "seed": seed},
                tags=["sweep"],
                capture_env=False,
            ) as run:
                for s in range(500):
                    run.log({"loss": 1 / (s + 1) + lr * seed}, step=s)
                run.log_text("note", "hi", step=1)
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")
    with TestClient(app) as c:
        yield c


def test_runs_and_query(client):
    info = client.get("/api/info").json()
    assert info["projects"][0]["name"] == "sweep"
    res = client.get("/api/runs", params={"q": "where config.lr = 1e-3 group by config.lr"}).json()
    assert len(res["runs"]) == 2 and res["query"]["group_by"] == "config.lr"
    assert res["metrics"] == ["loss"]
    bad = client.get("/api/runs", params={"q": "where ("}).json()
    assert bad["error"] and len(bad["runs"]) == 4


def test_scalars_arrow_grouped(client):
    keys = [r["key"] for r in client.get("/api/runs").json()["runs"]]
    res = client.get(
        "/api/scalars",
        params={"runs": ",".join(keys), "metric": "loss", "group": "config.lr", "points": 100},
    )
    assert res.headers["content-type"] == "application/vnd.apache.arrow.stream"
    table = pa.ipc.open_stream(res.content).read_all()
    series = json.loads(table.schema.metadata[b"series"])
    assert [s["label"] for s in series] == ["1e-4", "1e-3"]
    assert all(s["n"] == 2 for s in series)
    assert set(table.column_names) == {"series", "x", "y", "lo", "hi"}
    zoomed = client.get(
        "/api/scalars", params={"runs": keys[0], "metric": "loss", "xmin": 100, "xmax": 200}
    )
    xs = pa.ipc.open_stream(zoomed.content).read_all().column("x").to_pylist()
    assert 99 <= xs[0] <= 100 and 200 <= xs[-1] <= 201


def test_annotations_and_files(client):
    key = client.get("/api/runs").json()["runs"][0]["key"]
    r = client.post(
        "/api/runs/annotate", json={"keys": [key], "patch": {"starred": True, "notes": "best"}}
    )
    assert r.json()["updated"] == [key]
    assert client.get(f"/api/runs/{key}").json()["run"]["notes"] == "best"
    assert (
        client.post(
            "/api/runs/annotate", content="x", headers={"content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert '"lr"' in client.get(f"/api/runs/{key}/files/config.json").text
    assert "format_version" not in client.get(f"/api/runs/{key}/files/%2E%2E/run.json").text
    import pathlib

    from nuboard.server.data import path_inside

    assert path_inside(pathlib.Path("/a/b"), "../c") is None
    media = client.get(f"/api/runs/{key}/media").json()["items"]
    assert media[0]["text"] == "hi"


def test_views_round_trip(client):
    r = client.post(
        "/api/views",
        json={
            "project": "sweep",
            "name": "lr bands",
            "state": {"page": "charts", "params": {"q": "group by lr"}},
        },
    )
    assert r.json()["saved"] == "lr-bands.json"
    view = client.get("/api/views/sweep/lr-bands.json").json()
    assert view == {"page": "charts", "params": {"q": "group by lr"}}
