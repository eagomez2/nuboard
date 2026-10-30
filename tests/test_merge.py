import json
import shutil

import pytest

import nuboard as nb
from nuboard import merge
from nuboard.cli import main


def make_run(root, name, *, data=None, uses=None, project="proj"):
    """Log a finished run in `root/project`, optionally adding or using artifact `corpus`."""

    with nb.init(project, dir=root, run_name=name, capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

        if data is not None:
            run.add_artifact("corpus", data, type="dataset")

        if uses is not None:
            run.use_artifact(uses)

    return run.path


def by_kind(plan, kind):
    return [(a.op, a.name.split(" ")[0], a.detail) for a in plan.actions if a.kind == kind]


def test_runs_missing_in_dest_are_copied_and_a_second_merge_does_nothing(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    shared = make_run(a, "shared")
    shutil.copytree(shared, b / "proj" / "runs" / shared.name)
    new = make_run(b, "new")

    p = merge.plan(b, a)
    assert sorted(by_kind(p, "run")) == sorted(
        [("+", new.name, "copied"), ("=", shared.name, "identical")]
    )
    assert (a / "proj" / "runs" / new.name).exists() is False  # planning writes nothing

    merge.apply(p)
    assert (a / "proj" / "runs" / new.name / "run.json").exists()
    assert not (a / "proj" / merge.TMP).exists()
    assert merge.plan(b, a).changes == []


def test_a_clashing_artifact_version_is_renumbered_and_copied_runs_repointed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (tmp_path / "x.txt").write_text("from a")
    (tmp_path / "y.txt").write_text("from b, different")
    make_run(a, "prep-a", data=tmp_path / "x.txt")
    make_run(b, "prep-b", data=tmp_path / "y.txt")
    user = make_run(b, "train", uses="corpus:v1")

    p = merge.plan(b, a)
    assert by_kind(p, "artifact") == [
        ("!", "corpus:v1", "copied as v2 (DEST has a different v1); copied runs repointed")
    ]
    merge.apply(p)

    manifest = json.loads((a / "proj/artifacts/corpus/v2/manifest.json").read_text())
    assert manifest["version"] == 2
    meta = json.loads((a / "proj" / "runs" / user.name / "run.json").read_text())
    assert meta["inputs"][0]["version"] == 2
    assert json.loads((user / "run.json").read_text())["inputs"][0]["version"] == 1  # SRC untouched
    assert merge.plan(b, a).changes == []  # v1 of b is now known as a's v2


def test_identical_artifacts_are_skipped(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (tmp_path / "x.txt").write_text("same")
    make_run(a, "prep", data=tmp_path / "x.txt")
    make_run(b, "prep", data=tmp_path / "x.txt")

    assert by_kind(merge.plan(b, a), "artifact") == [("=", "corpus:v1", "identical, skipped")]


def test_a_run_that_differs_on_both_sides_is_a_conflict(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run = make_run(a, "r")
    copy = b / "proj" / "runs" / run.name
    shutil.copytree(run, copy)
    (run / "files").mkdir(exist_ok=True)
    (run / "files" / "only-a.txt").write_text("a")
    (copy / "files").mkdir(exist_ok=True)
    (copy / "files" / "only-b.txt").write_text("b")

    p = merge.plan(b, a)
    assert by_kind(p, "run") == [("!", run.name, "same id, different files: skipped")]
    assert p.conflicts and not p.changes


def test_dry_run_exit_codes_and_no_terminal(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    make_run(b, "r")

    with pytest.raises(SystemExit) as exc:
        main(["merge", str(b), str(a), "--dry-run"])

    assert exc.value.code == 0
    assert not (a / "proj").exists()

    with pytest.raises(SystemExit) as exc:  # pytest's stdin is not a terminal
        main(["merge", str(b), str(a)])

    assert exc.value.code == 2
    assert "Pass --yes" in capsys.readouterr().out
    assert not (a / "proj").exists()

    with pytest.raises(SystemExit) as exc:
        main(["merge", str(b), str(a), "--yes"])

    assert exc.value.code == 0
    assert len(list((a / "proj" / "runs").iterdir())) == 1


def test_dry_run_exits_1_on_conflicts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run = make_run(a, "r")
    copy = b / "proj" / "runs" / run.name
    shutil.copytree(run, copy)
    (run / "x.txt").write_text("a")
    (copy / "y.txt").write_text("b")

    with pytest.raises(SystemExit) as exc:
        main(["merge", str(b), str(a), "--dry-run"])

    assert exc.value.code == 1


def test_a_later_copy_of_a_run_replaces_the_older_one_which_is_kept(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run = make_run(a, "r")
    copy = b / "proj" / "runs" / run.name
    shutil.copytree(run, copy)
    (copy / "files").mkdir(exist_ok=True)
    (copy / "files" / "late.txt").write_text("logged after the first copy")

    p = merge.plan(b, a)
    assert by_kind(p, "run")[0][0] == "~"
    merge.apply(p)
    assert (run / "files" / "late.txt").exists()
    assert len(list((a / "proj" / merge.REPLACED).iterdir())) == 1
    # and the other way round, the later copy in DEST is kept
    assert by_kind(merge.plan(a, b), "run")[0][0] == "="


def test_running_runs_are_skipped_unless_asked(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run = nb.init("proj", dir=b, run_name="live", capture_env=False)

    try:
        run.add_scalar({"loss": 1.0}, step=0)
        run.flush()
        p = merge.plan(b, a)
        assert by_kind(p, "run")[0][:1] == ("!",)
        assert p.conflicts
        assert by_kind(merge.plan(b, a, include_running=True), "run")[0][0] == "+"
    finally:
        run.finish()


def test_project_files_are_combined_or_copied_next_to_dest(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rid_a, rid_b = make_run(a, "ra").name, make_run(b, "rb").name

    def put(root, rel, obj):
        path = root / "proj" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(obj if isinstance(obj, str) else json.dumps(obj))

    put(a, "reports/notes.md", "# A")
    put(b, "reports/notes.md", "# B")
    put(b, "reports/new.md", "# new")
    put(b, "reports/files/abc.png", "png")
    put(a, "views/v.json", {"page": "charts"})
    put(b, "views/v.json", {"page": "charts"})
    put(a, "collections/best.json", {"name": "best", "runs": [rid_a]})
    put(b, "collections/best.json", {"name": "best", "runs": [rid_a, rid_b]})
    put(a, "sweeps.json", {"hide": "!seed"})
    put(b, "sweeps.json", {"hide": "!seed !path"})
    put(a, "fields.json", {"fields": [{"name": "verdict", "type": "text"}]})
    put(
        b,
        "fields.json",
        {"fields": [{"name": "verdict", "type": "bool"}, {"name": "gpu", "type": "number"}]},
    )

    p = merge.plan(b, a)
    assert by_kind(p, "report") == [
        ("+", "reports/new.md", "new"),
        ("!", "reports/notes.md", "both differ: SRC's saved as notes-from-b.md"),
    ]
    assert by_kind(p, "view") == [("=", "views/v.json", "identical")]
    assert by_kind(p, "collection") == [("~", "collections/best.json", "1 run id added")]
    assert by_kind(p, "sweeps.json") == [("~", "sweeps.json", "hide rules combined: !seed !path")]
    assert (
        "!",
        "fields.json",
        "defined differently on each side, DEST's kept: verdict",
    ) in by_kind(p, "fields.json")
    merge.apply(p)

    reports = a / "proj" / "reports"
    assert (reports / "notes.md").read_text() == "# A"
    assert (reports / "notes-from-b.md").read_text() == "# B"
    assert (reports / "files" / "abc.png").exists()
    assert json.loads((a / "proj/collections/best.json").read_text())["runs"] == [rid_a, rid_b]
    assert json.loads((a / "proj/sweeps.json").read_text()) == {"hide": "!seed !path"}
    names = [f["name"] for f in json.loads((a / "proj/fields.json").read_text())["fields"]]
    assert names == ["verdict", "gpu"]
    again = merge.plan(b, a)
    assert [a.name for a in again.changes] == []
    assert by_kind(again, "report")[1] == (
        "=",
        "reports/notes.md",
        "already copied as notes-from-b.md",
    )


def test_annotations_of_the_same_run_are_combined(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run = make_run(a, "r")
    copy = b / "proj" / "runs" / run.name
    shutil.copytree(run, copy)
    (run / "annotations.json").write_text(json.dumps({"tags": ["x"], "notes": "old"}))
    (copy / "annotations.json").write_text(
        json.dumps({"tags": ["y"], "starred": True, "notes": "new"})
    )

    p = merge.plan(b, a)
    assert by_kind(p, "annotations") == [("~", run.name, "notes, tags and stars combined")]
    merge.apply(p)
    assert json.loads((run / "annotations.json").read_text()) == {
        "tags": ["x", "y"],
        "notes": "new",
        "starred": True,
    }


def test_a_change_after_the_plan_stops_the_merge(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_run(b, "r1")
    p = merge.plan(b, a)
    make_run(b, "r2")

    with pytest.raises(merge.StalePlan):
        merge.apply(p)

    assert not (a / "proj").exists()


def test_the_plan_is_rendered_with_every_change(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"

    for i in range(5):
        make_run(b, f"r{i}")

    text = merge.render(merge.plan(b, a))
    assert "proj" in text
    assert "+ 5 to copy" in text
    assert "(list with -v)" in text
    assert "Total: 5 run(s)" in text
    assert text.count("copied") == 0
    assert merge.render(merge.plan(b, a), verbose=True).count("copied") == 5


def test_bad_folders_are_refused(tmp_path):
    with pytest.raises(ValueError):
        merge.plan(tmp_path / "missing", tmp_path)

    (tmp_path / "a" / "b").mkdir(parents=True)

    with pytest.raises(ValueError):
        merge.plan(tmp_path / "a", tmp_path / "a" / "b")

    with pytest.raises(ValueError):
        merge.plan(tmp_path / "a", tmp_path / "c", project="nope")
