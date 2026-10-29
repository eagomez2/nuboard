from __future__ import annotations

import json

import pyarrow as pa
import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard.server import create_app


@pytest.fixture
def client(tmp_path):
    (tmp_path / "config.yaml").write_text("lr: 0.001\n", "utf-8")

    for lr in (1e-3, 1e-4):
        for seed in (1, 2):
            with nb.init(
                "sweep",
                run_name=f"lr{lr}-s{seed}",
                config={"lr": lr, "seed": seed},
                tags=["sweep"],
                capture_env=False,
            ) as run:
                for s in range(500):
                    run.add_scalar({"loss": 1 / (s + 1) + lr * seed}, step=s)

                run.add_text("note", "hi", step=1)
                run.add_file(tmp_path / "config.yaml")
                print(f"seed {seed}: " + "x" * 3_000_000)  # captured into files/output.log

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


def test_tags_edited_in_the_viewer_replace_the_logged_ones(client):
    keys = [r["key"] for r in client.get("/api/runs").json()["runs"]]
    assert client.get(f"/api/runs/{keys[0]}").json()["run"]["tags"] == ["sweep"]
    client.post("/api/runs/annotate", json={"keys": keys[:1], "patch": {"tags": ["best", "keep"]}})
    assert client.get(f"/api/runs/{keys[0]}").json()["run"]["tags"] == ["best", "keep"]
    assert client.get(f"/api/runs/{keys[1]}").json()["run"]["tags"] == ["sweep"]
    client.post("/api/runs/annotate", json={"keys": keys[:1], "patch": {"tags": []}})
    assert client.get(f"/api/runs/{keys[0]}").json()["run"]["tags"] == []


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
    assert "lr: 0.001" in client.get(f"/api/runs/{key}/files/config.yaml").text
    assert "format_version" not in client.get(f"/api/runs/{key}/files/%2E%2E/run.json").text
    head = client.get(f"/api/runs/{key}/files/output.log").text
    tail = client.get(f"/api/runs/{key}/files/output.log", params={"tail": 1}).text
    assert head.startswith("[nuboard: session 0") and len(head) == 2_000_000
    assert not tail.startswith("[nuboard") and tail.endswith("xxx\n")
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
    assert "lr-bands.json" in client.get("/api/info").json()["projects"][0]["views"]
    assert client.delete("/api/views/sweep/lr-bands.json").json() == {"deleted": "lr-bands.json"}
    assert client.get("/api/views/sweep/lr-bands.json").status_code == 404
    assert client.delete("/api/views/sweep/lr-bands.json").status_code == 404
    assert client.get("/api/info").json()["projects"][0]["views"] == []
    assert client.delete("/api/views/sweep/%2E%2E%2Fruns").status_code == 404  # stays in views/


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


def test_field_values_follow_definitions(client):
    keys = [r["key"] for r in client.get("/api/runs").json()["runs"]]
    project = client.get(f"/api/runs/{keys[0]}").json()["run"]["project"]
    defs = [{"name": "verdict", "type": "choice", "options": ["keep", "drop"]}]
    client.post("/api/fields", json={"project": project, "fields": defs})
    bad = {"keys": keys[:1], "patch": {"fields": {"verdict": "maybe"}}}
    res = client.post("/api/runs/annotate", json=bad)
    assert res.status_code == 400 and "keep, drop" in res.text
    good = {"keys": keys[:1], "patch": {"fields": {"verdict": "drop"}}}
    assert client.post("/api/runs/annotate", json=good).json()["updated"] == keys[:1]


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
    with nb.init("sweep", run_name="bad", capture_env=False) as run:
        for s in range(400):
            run.add_scalar({"loss": float("nan") if s >= 300 else 1.0}, step=s)

        src = tmp_path / "w.bin"
        src.write_bytes(b"x")
        run.add_artifact("weights", src)

    with nb.init("sweep", run_name="user", capture_env=False) as run:
        run.use_artifact("weights:latest")
        run.add_scalar({"loss": 1.0}, step=0)

    runs = {r["name"]: r for r in client.get("/api/runs").json()["runs"]}
    bad = runs["bad"]
    assert [a["kind"] for a in bad["alerts"]] == ["nonfinite"]
    assert bad["alerts"][0]["step"] == 300
    got = client.get("/api/alerts", params={"runs": bad["key"]}).json()["alerts"]
    assert got[bad["key"]][0]["metric"] == "loss"
    assert client.get("/api/runs", params={"q": "alerts > 0"}).json()["runs"][0]["name"] == "bad"
    art = client.get("/api/artifacts").json()["artifacts"]
    assert art[0]["producers"] == [bad["key"]] and art[0]["consumers"] == [runs["user"]["key"]]


def test_artifacts_of_a_project_without_runs(client, tmp_path):
    (tmp_path / "data.txt").write_text("x")
    nb.add_artifact("datasets", "corpus", tmp_path / "data.txt", reference=True)

    with nb.init("llm", run_name="train", capture_env=False) as run:
        run.use_artifact("datasets/corpus")
        run.add_scalar({"loss": 1.0}, step=0)

    with nb.init("vision", run_name="other", capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

    client.get("/api/runs")  # the catalog picks up the new runs
    art = client.get("/api/artifacts").json()["artifacts"]
    assert [(a["project"], a["name"]) for a in art] == [("datasets", "corpus")]
    assert art[0]["producers"] == [] and len(art[0]["consumers"]) == 1
    assert art[0]["manifest"]["reference"].endswith("data.txt")
    # a project's list also has the artifacts its runs used from other projects
    assert len(client.get("/api/artifacts?project=llm").json()["artifacts"]) == 1
    assert client.get("/api/artifacts?project=vision").json()["artifacts"] == []


def test_artifact_files_come_a_page_at_a_time(client, tmp_path):
    folder = tmp_path / "shards"
    folder.mkdir()

    for i in range(25):
        (folder / f"part-{i:03d}.bin").write_bytes(b"x" * i)

    nb.add_artifact("datasets", "shards", folder, reference=True)
    (art,) = client.get("/api/artifacts").json()["artifacts"]
    # the list has no file list, only what sums it up
    assert "files" not in art["manifest"]
    assert (art["file_count"], art["size"]) == (25, sum(range(25)))
    q = {"project": "datasets", "name": "shards", "version": 1, "limit": 10}
    page = client.get("/api/artifacts/files", params={**q, "offset": 20}).json()
    assert [f["path"] for f in page["files"]] == [f"part-{i:03d}.bin" for i in range(20, 25)]
    assert (page["total"], page["matched"]) == (25, 25)
    found = client.get("/api/artifacts/files", params={**q, "find": "PART-01"}).json()
    assert found["matched"] == 10 and len(found["files"]) == 10
    missing = client.get("/api/artifacts/files", params={**q, "version": 2})
    assert missing.status_code == 404
    bad = client.get("/api/artifacts/files", params={**q, "name": "../x"})
    assert bad.status_code == 400


def test_x_axis_by_another_metric(client):
    with nb.init("sweep", run_name="tok", capture_env=False) as run:
        for s in range(0, 2000, 2):
            run.add_scalar({"loss": 1 / (s + 1), "tokens": s * 512.0}, step=s)

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


def test_audio_supports_byte_ranges(tmp_path):
    import numpy as np

    run = nb.init("audio", capture_env=False)
    run.add_audio("clip", np.zeros(4000), step=0, sample_rate=8000)
    run.add_image("img", np.zeros((40, 40), "uint8"), step=0)
    run.finish()
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        items = c.get(f"/api/runs/{key}/media").json()["items"]
        audio = next(i for i in items if i["key"] == "clip")
        assert audio["duration"] == 0.5 and audio["kind"] == "audio"
        url = f"/api/runs/{key}/media/{audio['index']}"
        full = c.get(url, headers={"Accept-Encoding": "gzip"})
        assert full.headers["accept-ranges"] == "bytes"
        assert full.headers["content-encoding"] != "gzip"
        assert full.headers["content-type"] == "audio/wav"
        assert len(full.content) == 44 + 8000  # header + 4000 16-bit samples
        part = c.get(url, headers={"Range": "bytes=0-11"})
        assert part.status_code == 206
        assert part.content == full.content[:12]
        assert part.headers["content-range"] == f"bytes 0-11/{len(full.content)}"
        tail = c.get(url, headers={"Range": "bytes=-4"})
        assert tail.content == full.content[-4:]
        assert c.get(url, headers={"Range": "bytes=99999-"}).status_code == 416


def test_audio_notes_are_kept_per_item(tmp_path):
    import numpy as np

    run = nb.init("audio", capture_env=False)
    run.add_audio("clip", np.zeros(4000), step=3, sample_rate=8000)
    run.finish()
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        record = c.get("/api/runs").json()["runs"][0]
        key = record["key"]
        url = f"/api/runs/{key}/audio-notes"
        note = {"id": "a", "start": 0.1, "end": 0.25, "text": " click "}
        r = c.put(url, json={"item": "clip@3", "notes": [note]})
        assert r.json()["notes"] == [{"id": "a", "start": 0.1, "end": 0.25, "text": "click"}]
        items = c.get(f"/api/runs/{key}/media").json()["items"]
        assert items[0]["notes"][0]["text"] == "click"
        params = {"project": "audio", "ref": f"{record['id']}/clip@3"}
        assert c.get("/api/media/ref", params=params).json()["item"]["notes"][0]["id"] == "a"
        backwards = {**note, "start": 0.3}
        assert c.put(url, json={"item": "clip@3", "notes": [backwards]}).status_code == 400
        assert c.put(url, json={"item": "clip", "notes": []}).status_code == 400
        assert c.put(url, json={"item": "clip@3", "notes": []}).json()["notes"] == []
        assert "notes" not in c.get(f"/api/runs/{key}/media").json()["items"][0]
        assert "audio_notes" not in json.loads((run.path / "annotations.json").read_text())


def test_best_steps_and_media_refs(client):
    runs = client.get("/api/runs").json()["runs"]
    keys = [r["key"] for r in runs]
    best = client.get("/api/best", params={"runs": ",".join(keys), "metric": "loss"}).json()
    assert all(b["step"] == 499 for b in best["best"].values()) and len(best["best"]) == 4
    top = client.get("/api/best", params={"runs": keys[0], "metric": "loss", "mode": "max"}).json()
    assert top["best"][keys[0]]["step"] == 0
    run_id = runs[0]["id"]
    ref = client.get("/api/media/ref", params={"project": "sweep", "ref": f"{run_id}/note@1"})
    assert ref.json()["item"]["text"] == "hi" and ref.json()["run"] == keys[0]
    missing = {"project": "sweep", "ref": f"{run_id}/note@7"}
    assert client.get("/api/media/ref", params=missing).status_code == 404
    bad = {"project": "sweep", "ref": "nope"}
    assert client.get("/api/media/ref", params=bad).status_code == 400


def test_reports_round_trip(client):
    run_id = client.get("/api/runs").json()["runs"][0]["id"]
    line = f"![the note](media:{run_id}/note@1)"

    for _ in range(2):  # the first append creates the report, the second adds to it
        r = client.post("/api/reports", json={"project": "sweep", "name": "Notes", "append": line})
        assert r.json()["saved"] == "Notes"

    text = client.get("/api/reports/sweep/Notes").json()["text"]
    assert text.startswith("# Notes\n") and text.count(line) == 2
    assert client.get("/api/reports", params={"project": "sweep"}).json()["reports"][0][
        "title"
    ] == ("Notes")
    export = client.get("/api/reports/sweep/Notes/export")
    assert export.headers["content-type"] == "application/zip"
    import io
    import zipfile

    md = zipfile.ZipFile(io.BytesIO(export.content)).read("Notes.md").decode()
    assert "```text\nhi\n```" in md
    moved = client.post(
        "/api/reports", json={"project": "sweep", "name": "Notes", "rename": "final"}
    ).json()
    assert moved["saved"] == "final"
    assert client.get("/api/reports/sweep/Notes").status_code == 404
    client.post("/api/reports", json={"project": "sweep", "name": "final", "delete": True})
    assert client.get("/api/reports").json()["reports"] == []
    unknown = client.post("/api/reports", json={"project": "zzz", "name": "a", "text": ""})
    assert unknown.status_code == 400


def test_property_definitions_and_tag_values(client):
    defs = [{"name": "topics", "type": "tags", "options": ["a"]}, {"name": "n", "type": "number"}]
    assert client.post("/api/fields", json={"project": "sweep", "fields": defs}).json()["fields"]
    assert client.get("/api/fields", params={"project": "sweep"}).json()["fields"][0] == defs[0]
    bad = client.post(
        "/api/fields", json={"project": "sweep", "fields": [{"name": "x", "type": "?"}]}
    )
    assert bad.status_code == 400
    key = client.get("/api/runs").json()["runs"][0]["key"]
    patch = {"fields": {"topics": ["a", "b"], "n": 3}}
    res = client.post("/api/runs/annotate", json={"keys": [key], "patch": patch})
    assert res.status_code == 400  # "b" is not an option of topics
    defs[0]["options"] = ["a", "b"]
    client.post("/api/fields", json={"project": "sweep", "fields": defs})
    client.post("/api/runs/annotate", json={"keys": [key], "patch": patch})
    assert client.get(f"/api/runs/{key}").json()["run"]["fields"] == {"topics": ["a", "b"], "n": 3}
    client.post("/api/runs/annotate", json={"keys": [key], "patch": {"fields": {"topics": []}}})
    assert client.get(f"/api/runs/{key}").json()["run"]["fields"] == {"n": 3}


def test_runs_with_the_same_name_get_distinct_series(tmp_path):
    for _ in range(2):
        with nb.init("dup", run_name="same", dir=tmp_path / "exp", capture_env=False) as run:
            run.add_scalar({"loss": 1.0}, step=0)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        keys = [r["key"] for r in c.get("/api/runs").json()["runs"]]
        res = c.get("/api/scalars", params={"runs": ",".join(keys), "metric": "loss"})
        series = json.loads(pa.ipc.open_stream(res.content).read_all().schema.metadata[b"series"])
        labels = [s["label"] for s in series]
        assert len(set(labels)) == 2 and all(lb.startswith("same (") for lb in labels)


def test_chart_snapshots_are_served_and_exported(client):
    import base64
    import io
    import zipfile

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    body = {"project": "sweep", "report": "Charts", "png": "data:image/png;base64,"}
    path = client.post(
        "/api/reports/snapshot", json={**body, "png": body["png"] + base64.b64encode(png).decode()}
    ).json()["path"]
    assert path.startswith("files/Charts-") and path.endswith(".png")
    assert client.get(f"/api/reports/sweep/{path}").content == png
    bad = client.post("/api/reports/snapshot", json={**body, "png": "aGVsbG8="})
    assert bad.status_code == 400
    line = f'![loss]({path} "chart:metric=loss&runs=a")'
    client.post("/api/reports", json={"project": "sweep", "name": "Charts", "append": line})
    zf = zipfile.ZipFile(io.BytesIO(client.get("/api/reports/sweep/Charts/export").content))
    assert f"![loss]({path})" in zf.read("Charts.md").decode()
    assert zf.read(path) == png
    assert client.get("/api/reports/sweep/files/..%2Fruns").status_code == 404


def test_timeline_snapshots_are_plain_svg(client):
    import base64

    def post(svg):
        data = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        body = {"project": "sweep", "report": "Plots", "png": data}
        return client.post("/api/reports/snapshot", json=body)

    svg = '<svg xmlns="http://www.w3.org/2000/svg"><g><title>run a</title><rect/></g></svg>'
    path = post(svg).json()["path"]
    assert path.endswith(".svg")
    res = client.get(f"/api/reports/sweep/{path}")
    assert res.text == svg and "default-src 'none'" in res.headers["content-security-policy"]

    for bad in (
        "<svg><script>alert(1)</script></svg>",
        '<svg><rect onload="alert(1)"/></svg>',
        '<svg><a href="javascript:alert(1)"/></svg>',
        "<svg><foreignObject><p>x</p></foreignObject></svg>",
        "<html><svg/></html>",
    ):
        assert post(bad).status_code == 400, bad


def test_live_stream_ends_when_the_server_stops(tmp_path):
    # An open tab must not keep Ctrl+C from stopping `nuboard up`
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")
    calls = iter([False, True])
    app.state.stopping = lambda: next(calls, True)

    with TestClient(app) as c:
        body = c.get("/api/stream").text

    assert body.startswith("retry: 3000\nevent: hello\n")


def test_run_folder_files_are_listed_previewed_and_downloaded(tmp_path):
    import struct

    run = nb.init("ckpts", capture_env=False)
    run.add_scalar("loss", 1.0, step=0)
    run.finish()
    folder = run.path
    (folder / "checkpoints").mkdir()
    header = json.dumps({"w": {"dtype": "F32", "shape": [2, 3], "data_offsets": [0, 24]}}).encode()
    (folder / "checkpoints" / "ema.safetensors").write_bytes(
        struct.pack("<Q", len(header)) + header + b"\0" * 24
    )
    (folder / "checkpoints" / "broken.pth").write_bytes(b"\x80\x02garbage")
    (folder / "notes.html").write_text("<script>alert(1)</script>")
    (tmp_path / "secret.txt").write_text("outside")
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        tree = c.get(f"/api/runs/{key}/tree").json()
        files = {f["path"]: f for f in tree["files"]}
        assert files["checkpoints/ema.safetensors"]["kind"] == "tensors"
        assert files["run.json"]["internal"]
        assert tree["count"] == len(files)

        info = c.get(f"/api/runs/{key}/inspect/checkpoints/ema.safetensors").json()
        assert info["entries"][0]["shape"] == [2, 3] and info["error"] is None
        broken = c.get(f"/api/runs/{key}/inspect/checkpoints/broken.pth")
        assert broken.status_code == 200 and broken.json()["error"]

        assert c.get(f"/api/runs/{key}/text/notes.html").text.startswith("<script>")
        raw = c.get(f"/api/runs/{key}/raw/notes.html")
        # never served as a page of the viewer's origin
        assert raw.headers["content-type"] == "application/octet-stream"
        assert raw.headers["content-disposition"].startswith("attachment")
        assert raw.headers["content-security-policy"] == "sandbox"

        for bad in ("../../../secret.txt", "..%2F..%2F..%2Fsecret.txt", "%2E%2E/%2E%2E/x"):
            for kind in ("raw", "text", "inspect"):
                assert "outside" not in c.get(f"/api/runs/{key}/{kind}/{bad}").text

        assert c.get(f"/api/runs/{key}/raw/..%2F..%2F..%2Fsecret.txt").status_code == 404
        assert c.get(f"/api/runs/{key}/text/nope.txt").status_code == 404


def test_pins_are_shared_in_the_project_folder(tmp_path):
    run = nb.init("pinned", capture_env=False)
    run.finish()
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")
    pin = lambda **body: c.post("/api/pins", json={"project": "pinned", **body})  # noqa: E731

    with TestClient(app) as c:
        assert c.get("/api/pins", params={"project": "pinned"}).json() == {"pins": []}
        assert pin(add="files/config.yaml").json()["pins"] == ["files/config.yaml"]
        assert pin(add="/checkpoints/*/best_*.pth").json()["pins"][1] == "checkpoints/*/best_*.pth"
        assert pin(add="files/config.yaml").json()["pins"] == [
            "files/config.yaml",
            "checkpoints/*/best_*.pth",
        ]
        assert pin(remove="files/config.yaml").json()["pins"] == ["checkpoints/*/best_*.pth"]

        for bad in ("../secret", "a/../../b", "", "/"):
            assert pin(add=bad).status_code == 400

        assert pin(add="x").json()["pins"] == ["checkpoints/*/best_*.pth", "x"]
        assert c.post("/api/pins", json={"project": "nope", "add": "x"}).status_code == 400

    saved = json.loads((tmp_path / "exp" / "pinned" / "pins.json").read_text())
    assert saved == {"pins": ["checkpoints/*/best_*.pth", "x"]}


@pytest.mark.parametrize("compact", [False, True])
def test_scalar_bands_are_drawn_per_run_and_hidden_as_metrics(tmp_path, compact):
    with nb.init("bands", run_name="b", capture_env=False, compact=compact) as run:
        for s in range(5000):
            run.add_scalar("loss", 1.0, step=s, low=0.5, high=2.0)
            run.add_scalar("acc", 0.9, step=s)

    with nb.init("bands", run_name="plain", capture_env=False, compact=compact) as run:
        for s in range(5000):
            run.add_scalar("loss", 1.5, step=s)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        runs = c.get("/api/runs").json()["runs"]
        keys = ",".join(r["key"] for r in runs)
        assert set(next(r for r in runs if r["name"] == "b")["summary"]) == {"loss", "acc"}
        metrics = c.get("/api/metrics", params={"runs": keys}).json()["metrics"]
        assert [m["name"] for m in metrics] == ["acc", "loss"]

        res = c.get("/api/scalars", params={"runs": keys, "metric": "loss", "points": 200})
        table = pa.ipc.open_stream(res.content).read_all()
        series = json.loads(table.schema.metadata[b"series"])
        assert {s["label"]: s["band"] for s in series} == {"b": True, "plain": False}
        banded = series.index(next(s for s in series if s["band"]))
        rows = [r for r in table.to_pylist() if r["series"] == banded]
        assert rows and all(r["lo"] == 0.5 and r["hi"] == 2.0 and r["y"] == 1.0 for r in rows)

        zoomed = c.get(
            "/api/scalars",
            params={"runs": keys, "metric": "loss", "x": "metric:acc", "xmin": 0, "xmax": 1},
        )
        meta = json.loads(pa.ipc.open_stream(zoomed.content).read_all().schema.metadata[b"series"])
        assert [s["band"] for s in meta] == [True]  # only the banded run logged acc

        grouped = c.get("/api/scalars", params={"runs": keys, "metric": "loss", "group": "project"})
        meta = json.loads(pa.ipc.open_stream(grouped.content).read_all().schema.metadata[b"series"])
        assert "band" not in meta[0] and meta[0]["n"] == 2  # groups keep the spread across runs


def test_scalar_baselines_reach_the_chart_and_groups_average_them(tmp_path):
    for name, base in (("a", 2.0), ("b", 2.0), ("c", 3.0), ("d", None)):
        with nb.init("base", run_name=name, config={"m": name in "ab"}, capture_env=False) as run:
            if base is not None:
                run.add_scalar_baseline("val/pesq", base, low=base - 0.1, high=base + 0.1)

            for s in range(10):
                run.add_scalar("val/pesq", 2.5, step=s)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        runs = c.get("/api/runs").json()["runs"]
        assert {r["name"]: r["baselines"] for r in runs} == {
            "a": ["val/pesq"],
            "b": ["val/pesq"],
            "c": ["val/pesq"],
            "d": [],
        }
        keys = ",".join(r["key"] for r in runs)
        res = c.get("/api/scalars", params={"runs": keys, "metric": "val/pesq"})
        series = json.loads(pa.ipc.open_stream(res.content).read_all().schema.metadata[b"series"])
        by_label = {s["label"]: s["baseline"] for s in series}
        assert by_label["a"] == {"value": 2.0, "low": 1.9, "high": 2.1}
        assert by_label["c"]["value"] == 3.0 and by_label["d"] is None

        grouped = c.get(
            "/api/scalars", params={"runs": keys, "metric": "val/pesq", "group": "config.m"}
        )
        meta = json.loads(pa.ipc.open_stream(grouped.content).read_all().schema.metadata[b"series"])
        by_group = {s["label"]: s["baseline"]["value"] for s in meta}
        assert by_group == {"False": 3.0, "True": 2.0}  # d has no baseline and is left out


def test_token_guards_everything_but_assets(tmp_path):
    with nb.init("p", capture_env=False) as run:
        run.add_scalar("loss", 1.0, step=0)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache", token="s3cret")

    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/api/info").status_code == 401
        page = c.get("/", headers={"accept": "text/html"})
        assert page.status_code == 401 and 'name="token"' in page.text
        assert c.get("/?token=wrong", headers={"accept": "text/html"}).status_code == 401
        res = c.get("/charts?token=s3cret&x=1")
        assert res.status_code == 303 and res.headers["location"] == "/charts?x=1"
        assert "HttpOnly" in res.headers["set-cookie"] and "s3cret" not in res.headers["set-cookie"]
        assert c.get("/api/info").status_code == 200  # the cookie signs the client in

    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/api/info", headers={"authorization": "token s3cret"}).status_code == 200
        res = c.post("/login", data={"token": "s3cret", "next": "//evil.example"})
        assert res.status_code == 303 and res.headers["location"] == "/"
        assert c.get("/api/info").status_code == 200


def test_writes_from_another_site_are_refused(client):
    body = {"project": "sweep", "add": "x.txt"}
    other = client.post("/api/pins", json=body, headers={"origin": "https://evil.example"})
    assert other.status_code == 403
    same = client.post("/api/pins", json=body, headers={"origin": "http://testserver"})
    assert same.status_code == 200


def test_artifacts_are_added_unlinked_and_restored_only_when_allowed(tmp_path):
    data = tmp_path / "exp" / "data" / "corpus"
    data.mkdir(parents=True)
    (data / "a.txt").write_text("hello", "utf-8")
    nb.add_artifact("datasets", "corpus", data, reference=True)
    locked = create_app(tmp_path / "exp", cache_dir=tmp_path / "c1")

    with TestClient(locked) as c:
        assert c.get("/api/info").json()["edit_artifacts"] is False
        res = c.post("/api/artifacts/add", json={"project": "datasets", "name": "x", "path": "."})
        assert res.status_code == 403

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "c2", edit_artifacts=True)

    with TestClient(app) as c:
        check = c.post("/api/artifacts/check", json={"path": "data/corpus"}).json()
        assert check["exists"] and check["kind"] == "folder" and check["files"] == 1
        assert check["resolved"] == str(data.resolve())
        assert (
            "is not set"
            in c.post("/api/artifacts/check", json={"path": "$NOPE_X/a"}).json()["error"]
        )
        new = c.post(
            "/api/artifacts/add",
            json={
                "project": "datasets",
                "name": "corpus",
                "path": "data/corpus",
                "type": "dataset",
                "metadata": {"rows": 1},
            },
        ).json()
        assert new == {"project": "datasets", "name": "corpus", "version": 2}
        art = nb.get_artifact("datasets/corpus:v2")
        assert art.reference == data.resolve() and art.manifest["metadata"] == {"rows": 1}

        res = c.post(
            "/api/artifacts/unlink", json={"project": "datasets", "name": "corpus", "version": 2}
        )
        assert res.json() == {"unlinked": [2]}
        listed = {
            (a["version"], a["unlinked"]) for a in c.get("/api/artifacts").json()["artifacts"]
        }
        assert listed == {(1, False), (2, True)}
        assert (data / "a.txt").exists()  # referenced data is never touched

        # numbers stay taken while unlinked
        again = c.post(
            "/api/artifacts/add", json={"project": "datasets", "name": "corpus", "path": str(data)}
        ).json()
        assert again["version"] == 3

        c.post("/api/artifacts/unlink", json={"project": "datasets", "name": "corpus"})
        assert all(a["unlinked"] for a in c.get("/api/artifacts").json()["artifacts"])
        res = c.post(
            "/api/artifacts/unlink",
            json={"project": "datasets", "name": "corpus", "version": 2, "restore": True},
        )
        assert res.json() == {"restored": [2]}
        assert nb.get_artifact("datasets/corpus").version == 2


def test_storage_is_measured_only_on_request_and_pauses(tmp_path, monkeypatch):
    from nuboard.server import storage

    for i in range(3):
        with nb.init("p", run_name=f"r{i}", capture_env=False, system_metrics=False) as run:
            run.add_scalar({"loss": 1.0}, step=0)
            (run.path / "files").mkdir(exist_ok=True)
            (run.path / "files" / "big.bin").write_bytes(b"x" * (10_000 * (i + 1)))

    data = tmp_path / "elsewhere"
    data.mkdir()
    (data / "huge.bin").write_bytes(b"x" * 50_000)
    nb.add_artifact("p", "corpus", data, reference=True)
    nb.add_artifact("p", "model", data / "huge.bin")
    (tmp_path / "exp" / "p" / "reports").mkdir()
    (tmp_path / "exp" / "p" / "reports" / "r.md").write_text("x" * 700, "utf-8")
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        assert c.get("/api/storage").json() == {"state": "idle", "progress": {}, "result": None}
        assert c.post("/api/storage", json={"action": "nope"}).status_code == 400
        monkeypatch.setattr(storage, "PAUSE_AFTER_S", 0.0)  # pause after the first item
        c.post("/api/storage", json={"action": "start"})
        st = _wait(c, lambda s: s["state"] == "paused")
        assert st["progress"]["done"] == 1 and st["progress"]["total"] == 5
        monkeypatch.setattr(storage, "PAUSE_AFTER_S", 1000.0)
        c.post("/api/storage", json={"action": "resume"})
        res = _wait(c, lambda s: s["state"] == "idle")["result"]

    assert res["partial"] is False
    (proj,) = res["projects"]
    assert proj["run_count"] == 3 and proj["other_bytes"] == 700
    assert [r["files"] for r in proj["runs"]] == [30_000, 20_000, 10_000]
    assert all(r["scalars"] > 0 for r in proj["runs"])
    arts = {a["name"]: a for a in res["artifacts"]}
    assert arts["corpus"]["reference"] and arts["corpus"]["referenced"] == 50_000
    assert arts["corpus"]["bytes"] < 5_000  # only its manifest is stored here
    assert arts["model"]["bytes"] > 50_000 and not arts["model"]["reference"]
    assert proj["artifacts_bytes"] == arts["corpus"]["bytes"] + arts["model"]["bytes"]

    again = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")  # kept across restarts

    with TestClient(again) as c:
        st = c.get("/api/storage").json()
        assert st["state"] == "idle" and st["result"]["measured_at"] == res["measured_at"]
        monkeypatch.setattr(storage, "PAUSE_AFTER_S", 0.0)
        c.post("/api/storage", json={"action": "start"})
        _wait(c, lambda s: s["state"] == "paused")
        c.post("/api/storage", json={"action": "stop"})
        assert _wait(c, lambda s: s["state"] == "idle")["result"]["partial"] is True


def _wait(c, ok, timeout=10.0):
    import time

    end = time.time() + timeout

    while time.time() < end:
        st = c.get("/api/storage").json()

        if ok(st):
            return st

        time.sleep(0.02)

    raise AssertionError(f"timed out: {st}")
