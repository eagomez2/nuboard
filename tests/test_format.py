"""The event log: round trips, torn frames, corruption and incremental reads."""

from __future__ import annotations

from array import array

import numpy as np

from nuboard import _format as fmt
from nuboard.reader import LogFile


def write_log(path, frames):
    with open(path, "wb") as f:
        f.write(fmt.MAGIC)
        for fr in frames:
            f.write(fr)


def scalars(ids, steps, values, t=0.0):
    return fmt.scalars_frame(
        array("I", ids), array("q", steps), array("d", [t] * len(ids)), array("d", values)
    )


def test_round_trip(tmp_path):
    p = tmp_path / "events.r0.s0.log"
    write_log(
        p,
        [
            fmt.name_frame(0, "loss"),
            fmt.name_frame(1, "acc/top1 ✓"),
            scalars([0, 1, 0], [0, 0, 1], [2.5, 0.1, 2.0]),
            fmt.text_frame(0, 3, 1.0, "héllo"),
            fmt.heartbeat_frame(9.0),
            fmt.end_frame(10.0, "finished"),
        ],
    )
    log = LogFile(p)
    assert log.update()
    series = log.series()
    assert list(series["loss"][0]) == [0, 1]
    assert list(series["loss"][2]) == [2.5, 2.0]
    assert list(series["acc/top1 ✓"][2]) == [0.1]
    assert log.texts[0].text == "héllo"
    assert log.heartbeat == 9.0
    assert log.end == (10.0, "finished")


def test_torn_final_frame_is_ignored_then_completed(tmp_path):
    p = tmp_path / "events.r0.s0.log"
    good = [fmt.name_frame(0, "loss"), scalars([0, 0], [0, 1], [1.0, 2.0])]
    tail = scalars([0], [2], [3.0])
    write_log(p, [*good, tail[: len(tail) // 2]])  # process died mid-write
    log = LogFile(p)
    log.update()
    assert list(log.series()["loss"][2]) == [1.0, 2.0]
    with open(p, "ab") as f:  # the rest arrives (e.g. a slow network filesystem)
        f.write(tail[len(tail) // 2 :])
    assert log.update()
    assert list(log.series()["loss"][2]) == [1.0, 2.0, 3.0]


def test_corrupt_frame_stops_reading(tmp_path):
    p = tmp_path / "events.r0.s0.log"
    bad = bytearray(scalars([0], [5], [9.0]))
    bad[-1] ^= 0xFF
    write_log(
        p,
        [fmt.name_frame(0, "loss"), scalars([0], [1], [1.0]), bytes(bad), scalars([0], [6], [6.0])],
    )
    log = LogFile(p)
    log.update()
    assert list(log.series()["loss"][0]) == [1]


def test_incremental_reads_only_new_bytes(tmp_path):
    p = tmp_path / "events.r0.s0.log"
    write_log(p, [fmt.name_frame(0, "x"), scalars([0], [0], [0.0])])
    log = LogFile(p)
    log.update()
    first = log.offset
    assert not log.update()
    with open(p, "ab") as f:
        f.write(scalars([0], [1], [1.0]))
    assert log.update()
    assert log.offset > first
    assert list(log.series()["x"][0]) == [0, 1]


def test_little_endian_on_disk(tmp_path):
    frame = scalars([1], [2], [3.0])
    payload = frame[fmt.HEADER.size :]
    assert payload[:4] == (1).to_bytes(4, "little")
    assert np.frombuffer(payload, "<i8", 1, 8)[0] == 2
