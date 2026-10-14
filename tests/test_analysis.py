from __future__ import annotations

import nuboard as nm


def test_load_scalars_group_by():
    for lr in (0.1, 0.01):
        with nm.init("an", config={"lr": lr}, capture_env=False) as run:
            for s in range(10):
                run.log({"loss": s * lr}, step=s)
    project = nm.load("an")
    assert len(project.runs()) == 2
    table = project.scalars("loss", group_by="config.lr")
    assert table.num_rows == 20
    assert set(table.column("config.lr").to_pylist()) == {0.1, 0.01}
    assert project.runs("where config.lr = 0.1")[0].config["lr"] == 0.1
    summary = project.summary()
    assert set(summary.column_names) >= {"run_id", "config.lr", "loss"}
    one = project.runs()[0].scalars()
    assert one.column_names == ["metric", "step", "time", "value"]
