import pytest

import nuboard as nb
from nuboard import remove
from nuboard.cli import main


def make_run(root, name, *, tags=(), data=None, project="proj"):
    """Log a finished run in `root/project`, optionally adding artifact `corpus`."""

    with nb.init(project, dir=root, run_name=name, tags=list(tags), capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

        if data is not None:
            run.add_artifact("corpus", data, type="dataset")

    return run.path


def test_runs_matching_the_query_are_listed_then_deleted(tmp_path):
    keep = make_run(tmp_path, "keep")
    debug = make_run(tmp_path, "debug", tags=["debug"])

    p = remove.plan(tmp_path, 'tags has "debug"')
    assert [t.path for t in p.targets] == [debug]
    assert debug.exists()  # planning deletes nothing
    assert "Total: 1 run(s)" in remove.render(p)

    assert [t.path for t in remove.apply(p)] == [debug]
    assert not debug.exists() and keep.exists()
    assert not (tmp_path / "proj" / remove.TMP).exists()


def test_runs_are_picked_by_id_or_name_and_unknown_ones_reported(tmp_path):
    a = make_run(tmp_path, "a")
    b = make_run(tmp_path, "b")

    p = remove.plan(tmp_path, runs=[a.name, "b", "nope"])
    assert sorted(t.path for t in p.targets) == sorted([a, b])
    assert p.unknown == ["nope"]
    assert "? nope: no such run" in remove.render(p)


def test_a_query_or_runs_is_required(tmp_path):
    make_run(tmp_path, "a")

    with pytest.raises(ValueError):
        remove.plan(tmp_path)

    with pytest.raises(ValueError):
        remove.plan(tmp_path / "missing", "status = finished")


def test_running_runs_are_skipped_unless_asked(tmp_path):
    run = nb.init("proj", dir=tmp_path, run_name="live", capture_env=False)

    try:
        run.add_scalar({"loss": 1.0}, step=0)
        run.flush()
        p = remove.plan(tmp_path, runs=["live"])
        assert not p.targets and len(p.skipped) == 1
        assert "--include-running" in remove.render(p)
        assert len(remove.plan(tmp_path, runs=["live"], include_running=True).targets) == 1
    finally:
        run.finish()


def test_produced_artifact_versions_are_mentioned_and_kept(tmp_path):
    (tmp_path / "x.txt").write_text("data")
    make_run(tmp_path / "root", "prep", data=tmp_path / "x.txt")

    p = remove.plan(tmp_path / "root", runs=["prep"])
    assert "produced corpus:v1 (the versions are kept)" in remove.render(p)
    remove.apply(p)
    assert (tmp_path / "root/proj/artifacts/corpus/v1").exists()


def test_cli_asks_first_and_dry_run_deletes_nothing(tmp_path, capsys):
    run = make_run(tmp_path, "r")

    for extra, code in ((["--dry-run"], 0), ([], 2)):  # pytest's stdin is not a terminal
        with pytest.raises(SystemExit) as exc:
            main(["rm", str(tmp_path), "--run", "r", *extra])

        assert exc.value.code == code
        assert run.exists()

    assert "Pass --yes" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["rm", str(tmp_path), "-q", "name = r", "--yes"])

    assert exc.value.code == 0
    assert not run.exists()

    with pytest.raises(SystemExit) as exc:
        main(["rm", str(tmp_path)])

    assert exc.value.code == 2
