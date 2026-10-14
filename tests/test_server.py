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


def test_custom_fields_and_query(client):
    keys = [r["key"] for r in client.get("/api/runs").json()["runs"]]
    res = client.post(
        "/api/runs/annotate",
        json={"keys": keys[:2], "patch": {"fields": {"verdict": "keep", "score": 7}}},
    )
    assert res.json()["updated"] == keys[:2]
    found = client.get("/api/runs", params={"q": "verdict = keep"}).json()["runs"]
    assert {r["key"] for r in found} == set(keys[:2])
    assert found[0]["fields"] == {"verdict": "keep", "score": 7}
    client.post("/api/runs/annotate", json={"keys": keys[:1], "patch": {"fields": {"score": None}}})
    assert client.get(f"/api/runs/{keys[0]}").json()["run"]["fields"] == {"verdict": "keep"}
    assert (
        client.get("/api/runs", params={"q": "fields.score > 5"}).json()["runs"][0]["key"]
        == keys[1]
    )


def test_collections(client, tmp_path):
    runs = client.get("/api/runs").json()["runs"]
    keys = [r["key"] for r in runs]
    res = client.post("/api/collections", json={"name": "best", "add": keys[:3]}).json()
    assert len(res["collections"][0]["runs"]) == 3
    client.post("/api/collections", json={"name": "best", "remove": keys[:1]})
    listed = client.get("/api/collections").json()["collections"]
    assert listed[0]["name"] == "best" and len(listed[0]["runs"]) == 2
    assert (tmp_path / "exp" / "sweep" / "collections" / "best.json").exists()
    hits = client.get("/api/runs", params={"q": 'collections has "best"'}).json()["runs"]
    assert {r["key"] for r in hits} == set(keys[1:3])
    client.post("/api/collections", json={"name": "best", "project": "sweep", "delete": True})
    assert client.get("/api/collections").json()["collections"] == []
    assert client.get("/api/runs", params={"q": "collections has best"}).json()["runs"] == []


def test_alerts_endpoint_and_artifact_lineage(client, tmp_path):
    with nm.init("sweep", name="bad", capture_env=False) as run:
        for s in range(400):
            run.log({"loss": float("nan") if s >= 300 else 1.0}, step=s)
        src = tmp_path / "w.bin"
        src.write_bytes(b"x")
        run.log_artifact("weights", src)
    with nm.init("sweep", name="user", capture_env=False) as run:
        run.use_artifact("weights:latest")
        run.log({"loss": 1.0}, step=0)
    runs = {r["name"]: r for r in client.get("/api/runs").json()["runs"]}
    bad = runs["bad"]
    assert [a["kind"] for a in bad["alerts"]] == ["nonfinite"]
    assert bad["alerts"][0]["step"] == 300
    got = client.get("/api/alerts", params={"runs": bad["key"]}).json()["alerts"]
    assert got[bad["key"]][0]["metric"] == "loss"
    assert client.get("/api/runs", params={"q": "alerts > 0"}).json()["runs"][0]["name"] == "bad"
    art = client.get("/api/artifacts").json()["artifacts"]
    assert art[0]["producers"] == [bad["key"]] and art[0]["consumers"] == [runs["user"]["key"]]


def test_x_axis_by_another_metric(client):
    with nm.init("sweep", name="tok", capture_env=False) as run:
        for s in range(0, 2000, 2):
            run.log({"loss": 1 / (s + 1), "tokens": s * 512.0}, step=s)
    key = next(r["key"] for r in client.get("/api/runs").json()["runs"] if r["name"] == "tok")
    res = client.get("/api/scalars", params={"runs": key, "metric": "loss", "x": "metric:tokens"})
    table = pa.ipc.open_stream(res.content).read_all()
    assert table.schema.metadata[b"x"] == b"metric:tokens"
    xs = table.column("x").to_pylist()
    assert xs[0] == 0 and xs[-1] == 1998 * 512.0
    zoomed = client.get(
        "/api/scalars",
        params={"runs": key, "metric": "loss", "x": "metric:tokens", "xmin": 51200, "xmax": 102400},
    )
    zx = pa.ipc.open_stream(zoomed.content).read_all().column("x").to_pylist()
    assert zx[0] <= 51200 and 102400 <= zx[-1] <= 103424 and len(zx) > 50
    # a metric the run does not have gives no series instead of an error
    none = client.get("/api/scalars", params={"runs": key, "metric": "loss", "x": "metric:nope"})
    assert pa.ipc.open_stream(none.content).read_all().num_rows == 0


def test_assets_are_readable_from_the_figure_sandbox(client):
    from nuboard.server.app import STATIC

    assets = sorted((STATIC / "assets").glob("*.js")) if (STATIC / "assets").exists() else []
    if not assets:
        pytest.skip("frontend not built")
    r = client.get(f"/assets/{assets[0].name}")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
