"""A run resumed while the viewer is open: fresh data, stable media, later session wins."""

from __future__ import annotations

import numpy as np
from starlette.testclient import TestClient

import nuboard as nb
from nuboard.reader import RunReader
from nuboard.server import create_app

QUIET = {"capture_env": False, "system_metrics": False, "capture_console": False}


def _first_session():
    run = nb.init("res", **QUIET)

    for i in range(10):
        run.add_scalar("loss", float(i), step=i)
        run.add_text("note", f"s0 step{i}", step=i)
        run.add_image("img", np.full((4, 4), i, "uint8"), step=i)

    run.finish()
    return run


def _resume(run_id: str) -> None:
    run = nb.init("res", run_id=run_id, resume="must", **QUIET)

    for i in range(5, 20):
        run.add_scalar("loss", float(i), step=i)
        run.add_text("note", f"s1 step{i}", step=i)
        run.add_image("img", np.full((4, 4), 100 + i, "uint8"), step=i)

    run.finish()


def test_cached_reader_sees_a_resumed_compacted_run():
    run = _first_session()
    reader = RunReader(run.path)
    assert reader.parquet is not None and len(reader.scalars("loss")[0]) == 10

    resumed = nb.init("res", run_id=run.id, resume="must", **QUIET)
    resumed.add_scalar("loss", 10.0, step=10)
    resumed.flush()
    reader.refresh()
    assert reader.parquet is None  # the logs grew: Parquet no longer covers them
    assert len(reader.scalars("loss")[0]) == 11

    resumed.finish()  # compacted again
    reader.refresh()
    assert reader.parquet is not None and len(reader.scalars("loss")[0]) == 11


def test_viewer_media_ids_stay_put_and_later_session_wins(tmp_path):
    run = _first_session()
    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        before = c.get(f"/api/runs/{key}/media").json()["items"]
        img6 = next(i for i in before if i["key"] == "img" and i["step"] == 6)
        old6 = c.get(f"/api/runs/{key}/media/{img6['index']}").content

        _resume(run.id)
        scalars = c.get("/api/scalars", params={"runs": key, "metric": "loss"})
        assert scalars.status_code == 200

        after = c.get(f"/api/runs/{key}/media").json()["items"]
        imgs = [i for i in after if i["key"] == "img"]
        texts = [i for i in after if i["key"] == "note"]
        assert [i["step"] for i in imgs] == list(range(20))  # no duplicates of steps 5-9
        assert [t["text"] for t in texts[4:6]] == ["s0 step4", "s1 step5"]

        # the old URL still names the old item, so a cached copy is never wrong
        assert c.get(f"/api/runs/{key}/media/{img6['index']}").content == old6
        new6 = next(i for i in imgs if i["step"] == 6)
        assert new6["index"] != img6["index"]
        assert c.get(f"/api/runs/{key}/media/{new6['index']}").content != old6

        detail = c.get(f"/api/runs/{key}").json()
        assert detail["media"]["img"]["count"] == 20
        assert c.get(f"/api/runs/{key}/media", params={"rank": "x"}).status_code == 400

    # the Python reader still lists every logged item
    assert len(RunReader(run.path).media("img")) == 25
