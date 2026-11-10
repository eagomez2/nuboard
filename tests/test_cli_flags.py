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
