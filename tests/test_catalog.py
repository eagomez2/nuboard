from __future__ import annotations

import json
import time

import nuboard as nb
from nuboard.artifacts import list_artifacts
from nuboard.catalog import SCHEMA_VERSION, Catalog, find_runs


def test_find_runs_any_folder_shape(tmp_path):
    root = tmp_path / "exp"

    for project in ("a", "team/b"):
        nb.init(project, capture_env=False).finish()

    nested = {p for p, _ in find_runs(root)}
    assert nested == {"a", "team/b"}
    assert [p for p, _ in find_runs(root / "a")] == ["a"]
    assert [p for p, _ in find_runs(root / "a" / "runs")] == ["a"]
    run_dir = next((root / "a" / "runs").iterdir())
    assert [r for _, r in find_runs(run_dir)] == [run_dir.resolve()]


def test_refresh_detects_changes_and_rebuilds_cache(tmp_path):
    run = nb.init("a", capture_env=False)
    run.add_scalar({"x": 1}, step=0)
    run.finish()
    cat = Catalog(tmp_path / "exp", cache=tmp_path / "cache")
    assert cat.refresh() == {run.id}
    assert cat.refresh() == set()
    (run.path / "annotations.json").write_text(json.dumps({"starred": True}))
    time.sleep(0.01)
    assert cat.refresh() == {run.id}
    assert cat.get(run.id)["starred"] is True
    # a fresh catalog reads from the cache, and a schema bump rebuilds it
    again = Catalog(tmp_path / "exp", cache=tmp_path / "cache")
    assert again.get(run.id)["summary"]["x"]["last"] == 1
    again._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    again._db.commit()
    rebuilt = Catalog(tmp_path / "exp", cache=tmp_path / "cache")
    assert rebuilt.runs() == []
    assert rebuilt.refresh() == {run.id}


def test_5000_runs_list_quickly(tmp_path):
    root = tmp_path / "many" / "proj" / "runs"
    base = json.dumps(
        {
            "format_version": 1,
            "status": "finished",
            "config": {"lr": 0.1, "seed": 1},
            "summary": {
                f"m{i}": {
                    "last": 1.0,
                    "min": 0.5,
                    "max": 2.0,
                    "count": 10,
                    "step": 9,
                    "nonfinite": 0,
                }
                for i in range(20)
            },
        }
    )

    for i in range(5000):
        d = root / f"20250101-0000_r{i}_aaaaaa"
        d.mkdir(parents=True)
        (d / "run.json").write_text(base)

    cat = Catalog(tmp_path / "many", cache=tmp_path / "cache")
    cat.refresh()
    t0 = time.perf_counter()
    warm = Catalog(tmp_path / "many", cache=tmp_path / "cache")
    warm.refresh()
    assert len(warm.runs()) == 5000
    assert time.perf_counter() - t0 < 2.0  # 200 ms target on a laptop SSD; CI is slower


def test_stray_files_such_as_ds_store_are_skipped(tmp_path):
    run = nb.init("a", capture_env=False)
    run.add_scalar({"x": 1}, step=0)
    src = tmp_path / "src"
    src.mkdir()
    (src / "w.bin").write_bytes(b"0")
    run.add_artifact("ds", src, type="dataset")
    run.finish()
    root = tmp_path / "exp"

    for d in [root, *(p for p in root.rglob("*") if p.is_dir())]:
        (d / ".DS_Store").write_bytes(b"\0Bud1")  # what macOS Finder leaves behind

    assert [r for _, r in find_runs(root)] == [run.path.resolve()]
    assert Catalog(root, cache=tmp_path / "cache").refresh() == {run.id}
    assert [r.id for r in nb.load(root / "a").runs()] == [run.id]
    assert [a.name for a in list_artifacts(root / "a")] == ["ds"]
    again = nb.init("a", capture_env=False)
    assert again.use_artifact("ds").version == 1
    again.finish()


def test_media_count_is_recorded_and_read_without_opening_packs(tmp_path):
    import numpy as np

    scalars = nb.init("a", run_name="scalars", capture_env=False, system_metrics=False)
    scalars.add_scalar({"x": 1}, step=0)
    scalars.finish()
    assert json.loads((scalars.path / "run.json").read_text())["media_count"] == 0

    media = nb.init("a", run_name="media", capture_env=False, system_metrics=False)
    media.add_text("notes", "hello", step=0)
    media.add_image("img", np.zeros((2, 2, 3), np.uint8), step=0)
    media.finish()
    assert json.loads((media.path / "run.json").read_text())["media_count"] == 2

    again = nb.init("a", run_id=media.id, resume="must", capture_env=False, system_metrics=False)
    again.add_text("notes", "more", step=1)
    again.finish()  # a resumed run adds to the count
    assert json.loads((media.path / "run.json").read_text())["media_count"] == 3

    ev = nb.init("a", run_id=scalars.id, job="eval", capture_env=False, system_metrics=False)
    ev.add_text("eval/sample", "x", step=0)
    ev.finish()

    cat = Catalog(tmp_path / "exp", cache=tmp_path / "cache")
    cat.refresh()
    assert cat.get(media.id)["media_count"] == 3
    assert cat.get(scalars.id)["media_count"] == 1  # the helper job's media count

    # a run.json written by an older version: any media pack counts as media
    for run in (scalars, media):
        meta = json.loads((run.path / "run.json").read_text())
        del meta["media_count"]
        (run.path / "run.json").write_text(json.dumps(meta))

    for job in (scalars.path / "jobs").glob("*.json"):
        meta = json.loads(job.read_text())
        del meta["media_count"]
        job.write_text(json.dumps(meta))

    time.sleep(0.01)
    old = Catalog(tmp_path / "exp", cache=tmp_path / "cache2")
    old.refresh()
    assert old.get(media.id)["media_count"] == 1
    packs = list(scalars.path.glob("media.r*.pack"))
    assert old.get(scalars.id)["media_count"] == int(bool(packs))
