"""Artifact versions made from a run's files: copies, and references inside the project."""

from __future__ import annotations

import argparse
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
            "--ref",
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
