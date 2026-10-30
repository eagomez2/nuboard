"""`nuboard demo` writes its workspace once and opens it again afterwards."""

from __future__ import annotations

from nuboard.cli import main
from nuboard.demo import MARKER, is_demo


def test_demo_is_written_once_and_reused(tmp_path, capsys):
    root = tmp_path / "demo-runs"
    main(["demo", str(root)])
    runs = sorted(root.rglob("run.json"))
    assert runs and is_demo(root) and (root / MARKER).is_file()
    assert "Writing demo runs" in capsys.readouterr().out

    main(["demo", str(root)])
    assert sorted(root.rglob("run.json")) == runs  # no second set of runs
    assert "Opening the demo" in capsys.readouterr().out


def test_a_folder_without_the_marker_is_not_a_demo(tmp_path):
    assert not is_demo(tmp_path)
    assert not is_demo(tmp_path / "missing")
