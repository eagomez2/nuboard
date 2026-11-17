"""The command line's flags: one name for each, and folders that default to $NUBOARD_DIR."""

import pytest

import nuboard as nb
from nuboard import cli


def test_old_flag_names_are_gone(capsys):
    for argv in (
        ["up", "--lock-directions"],
        ["compact", "--force"],
        ["artifact", "add", "--ref"],
    ):
        with pytest.raises(SystemExit):
            cli.main(argv)

    assert "unrecognized arguments" in capsys.readouterr().err


def test_compact_defaults_to_nuboard_dir(tmp_path, monkeypatch, capsys):
    with nb.init("proj", run_name="x", dir=tmp_path, capture_env=False, compact=False) as run:
        run.add_scalar("loss", 1.0, step=0)

    monkeypatch.setenv("NUBOARD_DIR", str(tmp_path))
    cli.main(["compact"])

    assert "1 run(s) compacted" in capsys.readouterr().out
    assert list(tmp_path.rglob("data.parquet"))


def test_merge_takes_p(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["merge", str(tmp_path / "a"), str(tmp_path / "b"), "-p", "proj", "--dry-run"])

    assert "usage:" not in capsys.readouterr().err  # argparse accepted -p


@pytest.fixture
def up_output(tmp_path, monkeypatch, capsys):
    """Run `up` with the given flags, without serving; return what it printed, lines joined."""
    import uvicorn

    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    monkeypatch.delenv("NUBOARD_TOKEN", raising=False)
    (tmp_path / "runs").mkdir()

    def run(*flags):
        cli.main(["up", str(tmp_path / "runs"), "--port", "16070", *flags])
        return " ".join(capsys.readouterr().out.split())

    return run


def test_a_local_viewer_prints_no_share_warning(up_output):
    out = up_output()
    assert "Warning" not in out and "--no-share-warning" not in out
    assert "Warning" not in up_output("--host", "127.0.0.1", "--read-only-reports")


def test_a_shared_viewer_warns_about_plain_http_and_what_others_can_change(up_output):
    out = up_output("--host", "0.0.0.0")
    assert "Warning: this app is open to other computers, and anyone with the link" in out
    assert "the token and the data travel unencrypted" in out
    assert "Anyone with the link can edit reports, hypothesis boards and directions" in out
    assert "--read-only-reports," in out and "--read-only-directions." in out
    assert "Notes, tags, fields, pins, collections and saved views" in out
    assert "--edit-artifacts" not in out
    assert out.endswith(" ".join(" ".join(cli.share_warning(True)).split()))


def test_the_share_warning_lists_only_what_can_still_change(up_output):
    some = up_output("--host", "0.0.0.0", "--read-only-reports")
    assert "can still edit hypothesis boards and directions." in some
    assert "upload files" not in some and "add --read-only-hypotheses and" in some
    one = up_output("--host", "0.0.0.0", "--read-only-reports", "--read-only-hypotheses")
    assert "can still edit directions. For" in one and "add --read-only-directions." in one
    flags = ("--read-only-reports", "--read-only-hypotheses", "--read-only-directions")
    every = up_output("--host", "0.0.0.0", *flags, "--edit-artifacts")
    assert "Reports, hypotheses and directions are read-only: nobody can change them." in every
    assert "can edit" not in every and "add --read-only" not in every
    assert "With --edit-artifacts, anyone with the link can add artifact versions" in every


def test_no_share_warning_hides_it_but_not_the_no_token_warning(up_output):
    hidden = up_output("--host", "0.0.0.0", "--no-share-warning")
    assert "Warning" not in hidden and "plain HTTP" not in hidden
    open_ = up_output("--host", "0.0.0.0", "--no-token")
    assert open_.count(cli.NO_TOKEN_WARNING.strip()) == 1
    assert "the data travel unencrypted" in open_ and "token and the data" not in open_
    assert "Anyone who can reach it can edit reports" in open_ and "with the link" not in open_
    quiet = up_output("--host", "0.0.0.0", "--no-token", "--no-share-warning")
    assert quiet.count(cli.NO_TOKEN_WARNING.strip()) == 1 and "plain HTTP" not in quiet
