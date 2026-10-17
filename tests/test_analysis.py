from __future__ import annotations

import nuboard as nb
from nuboard import _fs


def test_load_scalars_group_by():
    for lr in (0.1, 0.01):
        with nb.init("an", config={"lr": lr}, capture_env=False) as run:
            for s in range(10):
                run.add_scalar({"loss": s * lr}, step=s)

    project = nb.load("an")
    assert len(project.runs()) == 2
    table = project.scalars("loss", group_by="config.lr")
    assert table.num_rows == 20
    assert set(table.column("config.lr").to_pylist()) == {0.1, 0.01}
    assert project.runs("where config.lr = 0.1")[0].config["lr"] == 0.1
    summary = project.summary()
    assert set(summary.column_names) >= {"run_id", "config.lr", "loss"}
    one = project.runs()[0].scalars()
    assert one.column_names == ["key", "step", "time", "value"]


def test_set_field_from_python():
    with nb.init("fields", capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

    handle = nb.load("fields").runs()[0]
    handle.set_field("verdict", "keep")
    handle.set_field("score", 4)
    assert handle.fields == {"verdict": "keep", "score": 4}
    again = nb.load("fields")
    assert again.runs("where fields.verdict = keep")[0].fields["score"] == 4
    again.runs()[0].set_field("verdict", None)
    assert nb.load("fields").runs()[0].fields == {"score": 4}


def test_audio_notes_from_python():
    with nb.init("notes", capture_env=False) as run:
        run.add_scalar({"loss": 1.0}, step=0)

    notes = {"clip@0": [{"id": "a", "start": 0.0, "end": 1.0, "text": "hiss"}]}
    _fs.atomic_write_json(run.path / "annotations.json", {"audio_notes": notes})
    assert nb.load("notes").runs()[0].audio_notes == notes
