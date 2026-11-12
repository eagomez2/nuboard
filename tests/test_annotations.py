from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard._annotations import AnnotationsError, update_annotations
from nuboard.server import create_app


@pytest.fixture
def served(tmp_path):
    with nb.init("proj", capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        yield c, key, run.path / "annotations.json"


def test_simultaneous_saves_of_one_run_all_survive(served):
    c, key, path = served

    def save(name):
        r = c.post("/api/runs/annotate", json={"keys": [key], "patch": {"fields": {name: "x"}}})
        assert r.status_code == 200

    for trial in range(50):
        names = [f"p{trial}_{i}" for i in range(4)]

        with ThreadPoolExecutor(4) as ex:
            list(ex.map(save, names))

        fields = json.loads(path.read_text("utf-8"))["fields"]
        assert all(n in fields for n in names), trial

    # audio notes go through the same lock and keep the properties
    note = {"item": "a@0", "notes": [{"start": 0, "end": 1, "text": "click"}]}
    assert c.put(f"/api/runs/{key}/audio-notes", json=note).status_code == 200
    ann = json.loads(path.read_text("utf-8"))
    assert ann["audio_notes"]["a@0"][0]["text"] == "click" and len(ann["fields"]) == 200


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", b"\xff\xfe{}"])
def test_a_broken_file_is_refused_and_left_untouched(served, content):
    c, key, path = served

    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, "utf-8")

    before = path.read_bytes()
    r = c.post("/api/runs/annotate", json={"keys": [key], "patch": {"starred": True}})
    assert r.status_code == 409 and "nothing in it is lost" in r.text
    note = {"item": "a@0", "notes": [{"start": 0, "end": 1, "text": "click"}]}
    assert c.put(f"/api/runs/{key}/audio-notes", json=note).status_code == 409
    assert path.read_bytes() == before
    assert c.get("/api/runs").status_code == 200  # reads stay tolerant


def test_an_empty_or_missing_file_is_a_fresh_start(tmp_path):
    update_annotations(tmp_path, lambda a: a.update(starred=True))
    assert json.loads((tmp_path / "annotations.json").read_text("utf-8")) == {"starred": True}
    (tmp_path / "annotations.json").write_text("", "utf-8")
    update_annotations(tmp_path, lambda a: a.update(reviewed=True))
    assert json.loads((tmp_path / "annotations.json").read_text("utf-8")) == {"reviewed": True}


def test_a_change_by_another_process_is_kept(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps({"tags": ["a"]}), "utf-8")
    calls = 0

    def change(ann):
        nonlocal calls
        calls += 1

        if calls == 1:  # another process rewrites the file between our read and write
            path.write_text(json.dumps({"tags": ["a"], "notes": "from elsewhere"}), "utf-8")
            st = os.stat(path)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

        ann["starred"] = True

    assert update_annotations(tmp_path, change) == {
        "tags": ["a"],
        "notes": "from elsewhere",
        "starred": True,
    }
    assert calls == 2
    assert json.loads(path.read_text("utf-8"))["notes"] == "from elsewhere"


def test_a_file_that_keeps_changing_is_refused(tmp_path):
    path = tmp_path / "annotations.json"
    n = iter(range(1000))

    def change(ann):
        path.write_text(json.dumps({"n": next(n)}), "utf-8")
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000 * (1 + next(n))))

    with pytest.raises(AnnotationsError, match="kept changing"):
        update_annotations(tmp_path, change)


def test_a_locked_file_is_a_clear_error(tmp_path, monkeypatch):
    from nuboard import _fs

    def locked(path, obj):
        raise PermissionError("in use")

    monkeypatch.setattr(_fs, "atomic_write_json", locked)

    with pytest.raises(AnnotationsError, match="locked by another program"):
        update_annotations(tmp_path, lambda a: a.update(starred=True))

    monkeypatch.undo()  # the lock was released after the error, so this does not hang
    update_annotations(tmp_path, lambda a: a.update(starred=True))


def test_set_field_from_python_is_safe_too(tmp_path):
    with nb.init("proj", capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

    r = nb.load("proj").run(run.id)
    r.set_field("verdict", "keep")
    path = run.path / "annotations.json"
    assert json.loads(path.read_text("utf-8"))["fields"] == {"verdict": "keep"}
    path.write_text("{oops", "utf-8")

    with pytest.raises(AnnotationsError):
        r.set_field("verdict", "drop")

    assert path.read_text("utf-8") == "{oops"
    assert r.audio_notes == {}


def test_a_stale_edit_is_refused_with_the_current_values(served):
    c, key, path = served
    post = lambda patch, expect=None: c.post(  # noqa: E731
        "/api/runs/annotate",
        json={"keys": [key], "patch": patch, **({"expect": expect} if expect else {})},
    )
    assert post({"notes": "first"}).status_code == 200
    # someone else saves new notes after this editor opened with "first"
    assert post({"notes": "theirs"}, {key: {"notes": "first"}}).status_code == 200
    r = post({"notes": "mine"}, {key: {"notes": "first"}})
    assert r.status_code == 409
    assert r.json()["conflicts"] == {key: {"notes": "theirs"}} and r.json()["updated"] == []
    assert json.loads(path.read_text("utf-8"))["notes"] == "theirs"
    # keeping mine on purpose: expect what is there now
    assert post({"notes": "mine"}, {key: {"notes": "theirs"}}).status_code == 200
    # without expect, a save behaves as before
    assert post({"notes": "plain"}).status_code == 200

    # properties: only the expected ones are compared, and empty values are alike
    assert post({"fields": {"score": 7}}, {key: {"fields": {"score": None}}}).status_code == 200
    r = post({"fields": {"verdict": "keep"}}, {key: {"fields": {"verdict": ""}}})
    assert r.status_code == 200
    r = post({"fields": {"score": 8}}, {key: {"fields": {"score": 6}}})
    assert r.status_code == 409 and r.json()["conflicts"][key] == {"fields": {"score": 7}}
    assert post({"fields": {"score": 8}}, {key: {"fields": {"score": 7.0}}}).status_code == 200
    assert post({"fields": {"ok": True}}, {key: {"fields": {"ok": None}}}).status_code == 200
    assert post({"fields": {"ok": False}}, {key: {"fields": {"ok": 1}}}).status_code == 409


def test_a_stale_edit_of_several_runs_saves_the_others(tmp_path):
    for i in range(3):
        with nb.init("proj", run_name=f"r{i}", capture_env=False, notes="logged") as run:
            run.add_scalar({"loss": 1.0}, step=0)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        keys = sorted(r["key"] for r in c.get("/api/runs").json()["runs"])
        c.post("/api/runs/annotate", json={"keys": keys[:1], "patch": {"fields": {"s": 1}}})
        expect = {k: {"fields": {"s": None}} for k in keys}
        body = {"keys": keys, "patch": {"fields": {"s": 2}}, "expect": expect}
        r = c.post("/api/runs/annotate", json=body)
        assert r.status_code == 409
        assert sorted(r.json()["updated"]) == keys[1:]
        assert r.json()["conflicts"] == {keys[0]: {"fields": {"s": 1}}}
        # notes logged with init count as the starting text until edited
        ok = {"keys": keys[:1], "patch": {"notes": "x"}, "expect": {keys[0]: {"notes": "logged"}}}
        assert c.post("/api/runs/annotate", json=ok).status_code == 200
