import multiprocessing as mp

from nuboard.directions import change_direction, column_key, read_directions


def _save_many(project_dir, prefix, n):
    for i in range(n):
        change_direction(project_dir, f"{prefix}{i}", "min" if i % 2 else "max")


def test_two_processes_saving_at_once_keep_every_direction(tmp_path):
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_save_many, args=(tmp_path, p, 30)) for p in ("a/", "b/")]

    for p in procs:
        p.start()

    for p in procs:
        p.join(60)

    assert all(p.exitcode == 0 for p in procs)
    directions = read_directions(tmp_path)
    assert len(directions) == 60
    assert directions["a/1"] == "min" and directions["b/0"] == "max"


def test_a_table_column_never_shares_a_direction_with_a_scalar(tmp_path):
    change_direction(tmp_path, "pesq", "max")
    change_direction(tmp_path, column_key("eval/samples", "pesq"), "min")
    assert read_directions(tmp_path) == {"eval/samples › pesq": "min", "pesq": "max"}
