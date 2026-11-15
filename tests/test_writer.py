"""The background writer: flush really waits, failed batches, values taken at the call."""

from __future__ import annotations

import numpy as np
import pytest

import nuboard as nb
from nuboard._writer import Writer
from nuboard.reader import RunReader

QUIET = {"capture_env": False, "system_metrics": False, "capture_console": False}


def test_flush_waits_for_the_batch_being_written():
    run = nb.init("w", compact=False, **QUIET)

    for trial in range(10):
        base = trial * 20_000

        for i in range(20_000):
            run.add_scalar({f"m{j}": 1.0 for j in range(5)}, step=base + i)

        run.flush()
        assert len(RunReader(run.path).scalars("m0")[0]) == base + 20_000

    run.finish()


def test_failed_batch_declares_its_names_again(tmp_path):
    writer = Writer(tmp_path, 0, 0, flush_interval=60)
    real = writer._f
    calls = {"n": 0}

    class Flaky:
        def write(self, data):
            calls["n"] += 1

            if calls["n"] == 1:
                raise OSError("disk full")

            return real.write(data)

        def __getattr__(self, name):
            return getattr(real, name)

    writer._f = Flaky()  # type: ignore[assignment]

    with pytest.warns(RuntimeWarning, match="failed to write a batch"):
        writer.queue.append((0, 0, 0.0, {"loss": 1.0}))
        writer.flush()

    writer.queue.append((0, 1, 0.0, {"loss": 2.0}))
    writer.flush()
    writer._f = real
    writer.close("finished")
    reader = RunReader(tmp_path)
    assert reader.scalar_names() == ["loss"]  # not "0"
    assert list(reader.scalars("loss")[2]) == [2.0]


def test_values_are_taken_at_the_call():
    run = nb.init("w", compact=False, **QUIET)
    acc = np.array(1.0)
    nested = {"val": {"loss": 0.5}}
    run.add_scalar("acc", acc, step=0)
    run.add_scalar(nested, step=0)
    acc += 10  # in place, before the writer converts it
    nested["val"]["loss"] = 99.0
    run.finish()
    reader = RunReader(run.path)
    assert list(reader.scalars("acc")[2]) == [1.0]
    assert list(reader.scalars("val/loss")[2]) == [0.5]


def test_a_write_cut_short_leaves_no_torn_frame(tmp_path):
    writer = Writer(tmp_path, 0, 0, flush_interval=60)
    real = writer._f
    calls = {"n": 0}

    class Short:  # writes half of the first batch, then the disk is full
        def write(self, data):
            calls["n"] += 1

            if calls["n"] == 1:
                real.write(bytes(data[: len(data) // 2]))
                raise OSError("disk full")

            return real.write(data)

        def __getattr__(self, name):
            return getattr(real, name)

    writer.queue.append((0, 0, 0.0, {"loss": 1.0}))
    writer.flush()
    writer._f = Short()  # type: ignore[assignment]

    with pytest.warns(RuntimeWarning, match="failed to write a batch"):
        writer.queue.append((0, 1, 0.0, {"loss": 2.0, "acc": 0.5}))
        writer.flush()

    writer.queue.append((0, 2, 0.0, {"loss": 3.0, "acc": 0.7}))
    writer.flush()
    writer._f = real
    writer.close("finished")
    reader = RunReader(tmp_path)
    assert list(reader.scalars("loss")[0]) == [0, 2]  # step 2 is read past the failed write
    assert list(reader.scalars("acc")[2]) == [0.7]
    assert next(iter(reader.logs.values())).end is not None


def test_a_media_item_that_cannot_be_stored_drops_only_itself(tmp_path, monkeypatch):
    writer = Writer(tmp_path, 0, 0, flush_interval=60)

    def full(data):
        raise OSError("disk full")

    monkeypatch.setattr(writer, "_append_pack", full)

    with pytest.warns(RuntimeWarning, match="could not store 'img'"):
        writer.put_media("img", 0, 0.0, lambda: (b"png", "image/png"), {})
        writer.queue.append((0, 0, 0.0, {"loss": 1.0}))
        writer.flush()

    writer.close("finished")
    reader = RunReader(tmp_path)
    assert list(reader.scalars("loss")[2]) == [1.0] and reader.media() == []
