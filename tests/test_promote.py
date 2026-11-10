"""Artifact versions made from a run's files: copies, and references inside the project."""

from __future__ import annotations

import argparse
import os
import shutil

import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard import _artifact_cli, remove
from nuboard.artifacts import promote_run_path, unlink_artifact, versions_needing
from nuboard.server.app import create_app


def make_run(root=None, name="train", *, finish=True):
    """Log a run in project `proj` with a checkpoint folder in its `files/`."""
    run = nb.init("proj", dir=root, run_name=name, capture_env=False)
    run.add_scalar({"loss": 1.0}, step=0)
    ckpt = run.path / "files" / "ckpt"
    ckpt.mkdir(parents=True)
    (ckpt / "model.bin").write_bytes(b"\0" * 64)
    (ckpt / "state.json").write_text("{}", "utf-8")

    if finish:
        run.finish()

    return run


def test_a_reference_is_stored_relative_to_the_project_and_moves_with_it(tmp_path):
    run = make_run(tmp_path / "exp")
    art = promote_run_path(run.path, "files/ckpt", "best", copy=False, type="checkpoint")
    rel = f"runs/{run.path.name}/files/ckpt"

    assert art.manifest["reference"] == rel and art.manifest["root"] == rel
    assert art.manifest["reference_base"] == "project"
    assert art.manifest["producer_run"] == run.id
    assert art.manifest["source"] == {"run": run.id, "path": "files/ckpt"}
    assert not (art.path / "files").exists()  # nothing copied
    assert art.verify() == []

    shutil.move(tmp_path / "exp", tmp_path / "moved")  # as rsync or a zip would
    moved = nb.get_artifact("proj/best", dir=tmp_path / "moved")
    assert moved.reference == tmp_path / "moved" / "proj" / rel
    assert (moved.files / "model.bin").read_bytes() == b"\0" * 64
    assert moved.verify() == []


def test_a_reference_to_one_file_and_a_changed_file_is_reported(tmp_path):
    run = make_run(tmp_path / "exp")
    art = promote_run_path(run.path, "files/ckpt/model.bin", "model", copy=False)
    assert art.manifest["root"] == f"runs/{run.path.name}/files/ckpt"
    assert [f["path"] for f in art.manifest["files"]] == ["model.bin"]

    (run.path / "files/ckpt/model.bin").write_bytes(b"\0" * 10)  # a resume overwrote it

    with pytest.warns(UserWarning, match="changed: model.bin"):
        art = nb.get_artifact("proj/model", dir=tmp_path / "exp")

    assert art.verify() == ["changed: model.bin"]


def test_a_copy_is_hashed_and_outlives_the_run(tmp_path):
    run = make_run(tmp_path / "exp")
    art = promote_run_path(run.path, "files/ckpt/", "best")
    assert "reference" not in art.manifest
    assert all(len(f["sha256"]) == 64 for f in art.manifest["files"])
    assert versions_needing(run.path) == []

    p = remove.plan(tmp_path / "exp", runs=[run.id])
    assert p.targets and not p.kept
    remove.apply(p)
    assert (art.files / "model.bin").exists()


def test_paths_outside_the_run_internal_files_and_live_references_are_refused(tmp_path):
    run = make_run(tmp_path / "exp")

    for bad in ("../../artifacts", "/etc/passwd", ""):
        with pytest.raises(ValueError, match="not inside the run"):
            promote_run_path(run.path, bad, "x")

    with pytest.raises(ValueError, match="written by nuboard itself"):
        promote_run_path(run.path, "run.json", "x")

    with pytest.raises(FileNotFoundError):
        promote_run_path(run.path, "files/nope.pt", "x")

    live = make_run(tmp_path / "exp", "live", finish=False)

    try:
        with pytest.raises(ValueError, match="still running"):
            promote_run_path(live.path, "files/ckpt", "x", copy=False)

        assert promote_run_path(live.path, "files/ckpt", "x").version == 1  # a copy is fine
    finally:
        live.finish()


def test_rm_keeps_a_run_whose_files_a_version_references_unless_forced(tmp_path, capsys):
    run = make_run(tmp_path / "exp")
    promote_run_path(run.path, "files/ckpt", "best", copy=False)

    p = remove.plan(tmp_path / "exp", runs=[run.id])
    assert not p.targets and [t.needed_by for t in p.kept] == [["best:v1"]]
    assert "best:v1 reference its files (unlink them, or pass --force)" in remove.render(p)

    assert remove.plan(tmp_path / "exp", runs=[run.id], force=True).targets

    unlink_artifact(run.path.parent.parent, "best")  # an unlinked version needs nothing
    p = remove.plan(tmp_path / "exp", runs=[run.id])
    assert p.targets and not p.kept


def test_artifact_add_on_a_runs_file_records_the_run(tmp_path):
    run = make_run()  # under $NUBOARD_DIR, as the CLI uses
    parser = argparse.ArgumentParser()
    _artifact_cli.add_parser(parser.add_subparsers(dest="cmd"), "NUBOARD", "experiments")
    args = parser.parse_args(
        [
            "artifact",
            "add",
            "proj/best",
            str(run.path / "files/ckpt"),
            "--reference",
            "-t",
            "model",
            "-d",
            "x",
        ]
    )
    said: list[str] = []
    assert _artifact_cli.main(args, say=said.append, interactive=False) == 0, said
    art = nb.get_artifact("proj/best")
    assert art.manifest["reference_base"] == "project"
    assert art.manifest["producer_run"] == run.id


def test_the_viewer_promotes_only_with_edit_artifacts(tmp_path):
    run = make_run()
    root = tmp_path / "exp"
    body = {"run": run.id, "path": "files/ckpt", "name": "best", "store": "reference"}

    with TestClient(create_app(root, cache_dir=tmp_path / "c1")) as c:
        assert c.post("/api/artifacts/promote", json=body).status_code == 403

    with TestClient(create_app(root, cache_dir=tmp_path / "c2", edit_artifacts=True)) as c:
        key = c.get("/api/runs").json()["runs"][0]["key"]
        body["run"] = key
        res = c.post("/api/artifacts/promote", json={**body, "type": "checkpoint"})
        assert res.json() == {"project": "proj", "name": "best", "version": 1}

        copy = c.post(
            "/api/artifacts/promote",
            json={**body, "path": "files/ckpt/model.bin", "store": "copy", "metadata": {"step": 4}},
        ).json()
        assert copy["version"] == 2

        bad = c.post("/api/artifacts/promote", json={**body, "path": "events.r0.s0.log"})
        assert bad.status_code == 400 and "itself" in bad.json()["error"]
        assert c.post("/api/artifacts/promote", json={**body, "run": "nope"}).status_code == 400
        assert c.post("/api/artifacts/promote", json={**body, "store": "x"}).status_code == 400

        listed = {a["version"]: a for a in c.get("/api/artifacts").json()["artifacts"]}
        assert listed[1]["producers"] == [key] and listed[2]["producers"] == [key]
        assert listed[1]["manifest"]["reference_base"] == "project"
        assert listed[2]["manifest"]["metadata"] == {"step": 4}


# -- reading a version's files, and versions that would contain other versions --


def test_a_version_reads_like_a_mapping_of_its_listed_files(tmp_path):
    run = make_run(tmp_path / "exp")
    folder = promote_run_path(run.path, "files/ckpt", "ckpt")
    single = promote_run_path(run.path, "files/ckpt/model.bin", "model", copy=False)

    assert sorted(folder) == ["model.bin", "state.json"] and len(folder) == 2
    assert folder["state.json"].read_text("utf-8") == "{}"
    assert "model.bin" in folder and "nope.bin" not in folder

    # a single-file reference: its folder holds other files, which are not keys
    assert list(single) == ["model.bin"] and "state.json" not in single
    assert single["model.bin"] == run.path / "files" / "ckpt" / "model.bin"

    with pytest.raises(KeyError, match=r"lists model\.bin"):
        single["state.json"]


def test_subfolder_keys_and_an_empty_version_is_still_truthy(tmp_path):
    src = tmp_path / "data"
    (src / "train").mkdir(parents=True)
    (src / "train" / "a.bin").write_bytes(b"1")
    (tmp_path / "empty").mkdir()
    art = nb.add_artifact("proj", "data", src, dir=tmp_path / "exp")
    empty = nb.add_artifact("proj", "empty", tmp_path / "empty", dir=tmp_path / "exp")

    assert art["train/a.bin"].read_bytes() == b"1"
    assert art["train\\a.bin"] == art["train/a.bin"]
    assert len(empty) == 0 and bool(empty)


def test_a_version_cannot_contain_or_live_inside_artifact_versions(tmp_path):
    from nuboard.artifacts import add_artifact

    project = tmp_path / "exp" / "proj"
    run = make_run(tmp_path / "exp")
    first = promote_run_path(run.path, "files/ckpt", "ckpt")

    for src in (project, project.parent, first.path, first.path / "files"):
        for reference in (False, True):
            with pytest.raises(ValueError, match="artifact"):
                add_artifact(project, "bad", src, reference=reference)

    other = tmp_path / "exp" / "other"  # another project's versions inside the source
    add_artifact(other, "x", run.path / "files" / "ckpt")

    with pytest.raises(ValueError, match="contains artifact versions"):
        add_artifact(project, "bad", other, reference=True)

    assert not list((project / "artifacts").glob("bad/.staging-*"))


def test_same_as_latest_matches_unchanged_files_only(tmp_path):
    from nuboard.artifacts import add_artifact, same_as_latest

    project = tmp_path / "proj"
    src = tmp_path / "best.pt"
    src.write_bytes(b"a" * 10)

    assert same_as_latest(project, "model", src) is None
    add_artifact(project, "model", src)
    assert same_as_latest(project, "model", src) == 1

    src.write_bytes(b"b" * 10)  # same size, other bytes: the copy's SHA-256 tells
    assert same_as_latest(project, "model", src) is None

    add_artifact(project, "ref", src, reference=True)
    assert same_as_latest(project, "ref", src) == 1
    os.utime(src, ns=(1, 1))
    assert same_as_latest(project, "ref", src) is None


def test_stale_staging_folders_are_removed_and_fresh_ones_kept(tmp_path):
    from nuboard.artifacts import remove_stale_staging

    adir = tmp_path / "artifacts" / "model"
    old, fresh = adir / ".staging-old", adir / ".staging-new"

    for d in (old, fresh):
        (d / "files").mkdir(parents=True)
        (d / "files" / "x.bin").write_bytes(b"x")

    for p in (old, old / "files", old / "files" / "x.bin"):
        os.utime(p, (0, 0))

    assert remove_stale_staging(adir) == [old]
    assert fresh.exists() and not old.exists()


def test_the_viewer_asks_before_adding_the_same_files_again(tmp_path):
    run = make_run(tmp_path / "exp")
    client = TestClient(
        create_app(tmp_path / "exp", cache_dir=tmp_path / "cache", edit_artifacts=True)
    )
    body = {"run": run.path.name, "path": "files/ckpt/model.bin", "name": "model", "store": "copy"}
    key = client.get("/api/runs").json()["runs"][0]["key"]
    body["run"] = key

    assert client.post("/api/artifacts/promote", json=body).json()["version"] == 1
    again = client.post("/api/artifacts/promote", json=body)
    assert again.status_code == 409 and again.json()["duplicate_of"] == 1
    assert (
        client.post("/api/artifacts/promote", json={**body, "allow_duplicate": True}).json()[
            "version"
        ]
        == 2
    )

    bad = client.post("/api/artifacts/add", json={"project": "proj", "name": "all", "path": "proj"})
    assert bad.status_code == 400 and "artifacts/ folder" in bad.json()["error"]


def test_a_broken_manifest_does_not_break_the_artifact_list(tmp_path):
    run = make_run(tmp_path / "exp")
    good = promote_run_path(run.path, "files/ckpt", "ckpt")
    broken = good.path.parent / "v2"
    broken.mkdir()
    (broken / "manifest.json").write_bytes(b'["not", "an object"]')
    client = TestClient(create_app(tmp_path / "exp", cache_dir=tmp_path / "cache"))

    listed = {a["version"]: a for a in client.get("/api/artifacts").json()["artifacts"]}
    assert listed[1]["problem"] == "" and listed[1]["file_count"] == 2
    assert "not valid JSON" in listed[2]["problem"] and listed[2]["file_count"] == 0
    files = client.get(
        "/api/artifacts/files", params={"project": "proj", "name": "ckpt", "version": 2}
    )
    assert files.json()["files"] == []
