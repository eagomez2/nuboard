"""Timers: `Run.timer`, `Timer`, configurable prefixes and the reserved-prefix warning."""

from __future__ import annotations

import json
import time
import warnings

import pytest

import nuboard as nb
from nuboard.reader import RunReader
from nuboard.timing import COUNT


def _run(**kw):
    return nb.init("t", capture_env=False, system_metrics=False, capture_console=False, **kw)


def test_context_manager_logs_duration_at_its_start_time():
    run = _run()
    before = time.time()

    with run.timer("train/epoch", step=3):
        time.sleep(0.02)

    run.finish()
    steps, times, values = RunReader(run.path).scalars("timing/train/epoch")
    assert steps.tolist() == [3]
    assert 0.015 < values[0] < 1.0
    assert before <= times[0] <= before + 0.5  # the span's start, not when it was logged


def test_same_name_is_the_same_timer_so_it_can_stop_in_another_method():
    run = _run()

    class Callbacks:
        def on_validation_start(self):
            run.timer("val/epoch").start()

        def on_validation_end(self, epoch):
            return run.timer("val/epoch").stop(step=epoch)

    cb = Callbacks()

    for epoch in range(3):
        cb.on_validation_start()
        assert run.timer("val/epoch").running
        assert cb.on_validation_end(epoch) >= 0

    assert run.timer("val/epoch") is run.timer("val/epoch")
    run.finish()
    assert RunReader(run.path).scalars("timing/val/epoch")[0].tolist() == [0, 1, 2]


def test_step_defaults_to_the_runs_latest_step_and_does_not_move_it():
    run = _run()
    run.add_scalar("loss", 1.0, step=7)
    run.timer("ckpt").start().stop()
    run.add_scalar("loss", 0.5)  # still the step after 7
    run.finish()
    r = RunReader(run.path)
    assert r.scalars("timing/ckpt")[0].tolist() == [7]
    assert r.scalars("loss")[0].tolist() == [7, 8]


def test_misuse_warns_once_and_never_raises():
    run = _run()
    t = run.timer("x")

    with pytest.warns(RuntimeWarning, match="stopped without being started"):
        assert t.stop() == 0.0

    t.start()

    with pytest.warns(RuntimeWarning, match="already running"):
        t.start()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        t.stop()
        t.stop()  # the second warning of a kind is not repeated

    run.finish()
    assert len(RunReader(run.path).scalars("timing/x")[0]) == 1


def test_exception_inside_with_still_stops_and_logs():
    run = _run()

    with pytest.raises(KeyError), run.timer("boom", step=1):
        raise KeyError

    assert not run.timer("boom").running
    run.finish()
    assert RunReader(run.path).scalars("timing/boom")[0].tolist() == [1]


def test_accumulate_sums_spans_and_logs_total_and_count_on_flush():
    run = _run()
    wait = run.timer("data/wait", accumulate=True)

    for epoch in range(2):
        for _ in range(4):
            with wait:
                time.sleep(0.002)

        assert wait.flush(step=epoch) > 0.007

    assert wait.flush() == 0.0  # nothing summed since: logs nothing
    run.finish()
    r = RunReader(run.path)
    steps, _, totals = r.scalars("timing/data/wait")
    assert steps.tolist() == [0, 1] and (totals > 0.007).all()
    assert r.scalars("timing/data/wait" + COUNT)[2].tolist() == [4.0, 4.0]
    assert "timing/data/wait" + COUNT not in r.scalar_names()  # hidden, like band bounds


def test_finish_flushes_accumulated_spans_and_drops_running_timers():
    run = _run()
    acc = run.timer("acc", accumulate=True)

    with acc:
        pass

    run.timer("open").start()

    with pytest.warns(RuntimeWarning, match="still running at finish.*open"):
        run.finish()

    r = RunReader(run.path)
    assert len(r.scalars("timing/acc")[0]) == 1
    assert "timing/open" not in r.scalar_names()


def test_options_are_fixed_by_the_first_call():
    run = _run()
    t = run.timer("a", accumulate=True)

    with pytest.warns(RuntimeWarning, match="accumulate=True; accumulate=False is ignored"):
        assert run.timer("a", accumulate=False) is t

    assert t.accumulate
    run.finish()


def test_fast_timer_suggests_accumulate():
    run = _run()

    with pytest.warns(RuntimeWarning, match="points per second.*accumulate=True"):
        for _ in range(60):
            with run.timer("batch"):
                pass

    run.finish()


def test_invalid_names_raise():
    run = _run()

    for bad in ("", "/", "a\x1fb"):
        with pytest.raises(ValueError):
            run.timer(bad)

    run.finish()


def test_disabled_timer_measures_and_logs_nothing():
    t = nb.Timer.disabled("x")

    with t:
        time.sleep(0.005)

    with pytest.warns(RuntimeWarning):
        assert t.stop() == 0.0  # already stopped by the with block

    t.start()
    assert t.stop() >= 0.0
    assert t.elapsed == 0.0


def test_prefixes_are_configurable_and_recorded(tmp_path):
    run = _run(timing_prefix="perf", system_prefix="sys")

    with run.timer("epoch", step=0):
        pass

    run._log_system({"system/memory/used_gb": 1.0})
    run.finish()
    meta = json.loads((run.path / "run.json").read_text("utf-8"))
    assert meta["prefixes"] == {"system": "sys", "timing": "perf"}
    names = RunReader(run.path).scalar_names()
    assert "perf/epoch" in names and "sys/memory/used_gb" in names


def test_resume_keeps_the_recorded_prefixes():
    run = _run(timing_prefix="perf")
    run.finish()
    again = _run(run_id=run.id, resume="must")

    with again.timer("epoch", step=1):
        pass

    again.finish()
    assert again.prefixes["timing"] == "perf"
    assert "perf/epoch" in RunReader(run.path).scalar_names()


@pytest.mark.parametrize("bad", ["", "a/b", "x\x1f", " pad"])
def test_bad_prefixes_raise(bad):
    with pytest.raises(ValueError, match="timing_prefix"):
        _run(timing_prefix=bad)


def test_hand_logged_reserved_prefix_warns_once_and_is_still_logged():
    run = _run()

    with pytest.warns(RuntimeWarning, match="'timing/mine' starts with 'timing/'"):
        run.add_scalar({"timing": {"mine": 1.0}, "train/timing": 2.0, "Timing/x": 3.0}, step=0)
        run.add_scalar("timing/mine", 1.5, step=1)
        run.flush()

    with warnings.catch_warnings():
        warnings.simplefilter("error")

        with run.timer("ok"):  # the run's own timers do not warn
            pass

        run.finish()

    assert RunReader(run.path).scalars("timing/mine")[0].tolist() == [0, 1]


def test_only_rank_zero_logs_timers_unless_all_ranks(monkeypatch):
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("TORCHELASTIC_RUN_ID", "job-7")
    monkeypatch.setenv("RANK", "0")
    r0 = _run()
    monkeypatch.setenv("RANK", "1")
    r1 = _run()

    for r in (r0, r1):
        with r.timer("epoch", step=0):
            pass

        with r.timer("all", step=0, all_ranks=True):
            pass

    r1.finish()
    r0.finish()
    reader = RunReader(r0.path)
    assert reader.scalar_names(rank=0) == ["timing/all", "timing/epoch"]
    assert reader.scalar_names(rank=1) == ["timing/all"]


def test_timing_all_ranks_sets_the_default(monkeypatch):
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("TORCHELASTIC_RUN_ID", "job-8")
    monkeypatch.setenv("RANK", "0")
    r0 = _run(timing_all_ranks=True)
    monkeypatch.setenv("RANK", "1")
    r1 = _run(timing_all_ranks=True)
    assert r1.timer("epoch").all_ranks and not _run().timer("epoch").all_ranks
    r1.finish()
    r0.finish()


def test_a_helper_job_times_under_its_own_name():
    run = _run()
    run.finish()
    job = _run(run_id=run.id, job="eval")

    with job.timer("ckpt", step=0):
        pass

    job.finish()
    assert any(n == "timing/eval/ckpt" for n in RunReader(run.path).scalar_names())
