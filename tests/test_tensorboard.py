import json
import shutil
import struct
from pathlib import Path

import pytest

import nuboard as nb
from nuboard.cli import main
from nuboard.tensorboard import import_logdir, read_events

DATA = Path(__file__).parent / "data" / "tensorboard"


def _runs(root: Path) -> dict:
    return {h.name: h for h in nb.load("tb", dir=str(root)).runs()}


def test_imports_tf2_pytorch_and_tensorboardx_logs(tmp_path):
    results = import_logdir(DATA, "tb", dir=tmp_path)

    assert [r.name for r in results] == [
        "tbx/exp1",
        "tf2/lr0.01/train",
        "tf2/lr0.01/validation",
        "torch/run_a",
        "torch/run_a/cmp_a",
        "torch/run_a/cmp_b",
    ]
    assert not any(r.ignored for r in results)  # histograms are imported too

    runs = _runs(tmp_path)
    tf_train = runs["tf2-lr0.01-train"]
    assert tf_train.config == {"lr": 0.01, "optimizer": "adam", "layers": 3, "dropout_on": True}
    assert tf_train.record["group"] == "tf2/lr0.01"
    assert tf_train.record["status"] == "finished"
    assert "tensorboard" in tf_train.record["tags"]

    reader = tf_train.reader()
    steps, _, loss = reader.scalars("loss")
    assert list(steps) == [0, 1, 2, 3, 4]
    assert loss[1] == pytest.approx(0.5)
    _, _, acc = reader.scalars("acc")  # an int64 tensor in TF2
    assert list(acc) == [0, 1, 2, 3, 4]

    media = {(m.key, m.meta["mime"]) for m in reader.media()}
    assert media == {
        ("samples/0", "image/png"),
        ("samples/1", "image/png"),
        ("tone", "audio/wav"),
        ("weights", "application/x-nuboard-histogram+json"),
    }

    # TF2's histogram tensor (left, right, count per bucket) is re-binned evenly
    (weights,) = [m for m in reader.media() if m.key == "weights"]
    data = json.loads(reader.read_media(weights))
    assert len(data["counts"]) == 50 and sum(data["counts"]) == pytest.approx(100)
    assert data["edges"][0] == data["min"] and data["edges"][-1] == data["max"]
    assert [t.text for t in reader.texts("note")] == ["hello **tf**"]

    # PyTorch's add_hparams sub-folder is folded into its run
    torch_run = runs["torch-run_a"]
    assert torch_run.config == {"lr": 0.1, "bs": 32, "opt": "sgd"}
    assert set(torch_run.summary) == {"train/loss", "hparam/acc"}
    assert {m.key for m in torch_run.reader().media()} == {"img", "snd", "h"}

    # PyTorch writes TF1 HistogramProtos, which carry the sum and sum of squares
    (h,) = [m for m in torch_run.reader().media() if m.key == "h"]
    data = json.loads(torch_run.reader().read_media(h))
    assert data["count"] == 50 and sum(data["counts"]) == pytest.approx(50)
    assert data["min"] < data["mean"] < data["max"] and data["std"] > 0
    assert [t.text for t in torch_run.reader().texts()] == ["torch text"]
    assert [t.text for t in torch_run.reader().texts("txt")] == ["torch text"]
    assert len(runs) == 6

    tbx = runs["tbx-exp1"]
    assert {m.key for m in tbx.reader().media()} == {"img", "snd"}
    _, _, loss = tbx.reader().scalars("loss")
    assert loss[0] == pytest.approx(3.0)


def test_keeps_the_original_wall_times(tmp_path):
    import_logdir(DATA / "tbx", "tb", dir=tmp_path)
    run = next(iter(_runs(tmp_path).values()))
    times = [
        e.wall_time for f in sorted((DATA / "tbx").rglob("*tfevents*")) for e in read_events(f)
    ]

    assert run.record["started"] == pytest.approx(min(times))
    assert run.record["ended"] == pytest.approx(max(times))
    _, t, _ = run.reader().scalars("loss")
    assert min(t) >= min(times) and max(t) <= max(times)


def test_importing_twice_skips_existing_runs(tmp_path):
    first = import_logdir(DATA / "torch", "tb", dir=tmp_path)
    again = import_logdir(DATA / "torch", "tb", dir=tmp_path)

    assert not any(r.skipped for r in first)
    assert all(r.skipped for r in again)
    assert [r.run_id for r in again] == [r.run_id for r in first]
    assert len(_runs(tmp_path)) == len(first)


def test_single_run_folder_and_truncated_file(tmp_path):
    src = tmp_path / "logs" / "solo"
    shutil.copytree(DATA / "tbx" / "exp1", src)
    event_file = next(src.iterdir())
    event_file.write_bytes(event_file.read_bytes()[:-7])  # a writer killed mid-record

    (result,) = import_logdir(src, "tb", dir=tmp_path / "out")

    assert result.name == "solo"
    assert result.scalars > 0


def test_negative_and_packed_tensor_values():
    from nuboard.tensorboard import _tensor

    def varint(n):
        n &= (1 << 64) - 1
        out = bytearray()

        while True:
            byte = n & 0x7F
            n >>= 7

            if n:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                return bytes(out)

    packed = varint(-3) + varint(5)
    proto = b"\x08\x03" + b"\x3a" + varint(len(packed)) + packed  # dtype=int32, int_val
    assert _tensor(proto) == (3, [], [-3, 5])

    content = struct.pack("<2d", 1.5, -2.0)
    proto = b"\x08\x02" + b"\x22" + varint(len(content)) + content  # dtype=double, tensor_content
    assert _tensor(proto) == (2, [], [1.5, -2.0])


def test_cli_import_tensorboard(tmp_path, capsys):
    main(
        [
            "import-tensorboard",
            str(DATA / "tf2"),
            "-p",
            "tb",
            "--dir",
            str(tmp_path),
            "--tag",
            "keras",
        ]
    )
    out = capsys.readouterr().out

    assert "imported  lr0.01/train: 10 scalars, 5 media, 4 hparams\n" in out
    assert "2 run(s) imported" in out
    assert all(h.record["tags"] == ["keras"] for h in _runs(tmp_path).values())

    main(["import-tensorboard", str(DATA / "tf2"), "-p", "tb", "--dir", str(tmp_path)])
    assert capsys.readouterr().out.count("skipped   ") == 2

    with pytest.raises(SystemExit, match="no TensorBoard event files"):
        main(["import-tensorboard", str(tmp_path / "tb" / "runs"), "--dir", str(tmp_path)])


def _varint(n: int) -> bytes:
    out = bytearray()

    while True:
        byte, n = n & 0x7F, n >> 7

        if not n:
            out.append(byte)
            return bytes(out)

        out.append(byte | 0x80)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def test_imports_pr_curves(tmp_path):
    # TensorBoard's pr_curves tensor: rows TP, FP, TN, FN, precision, recall
    rows = [[3, 2, 0], [2, 1, 0], [0, 1, 2], [0, 1, 3], [0.6, 0.667, 1.0], [1.0, 0.667, 0.0]]
    content = struct.pack("<18f", *(v for r in rows for v in r))
    shape = _field(2, _field(2, b"\x08\x06") + _field(2, b"\x08\x03"))
    tensor = b"\x08\x01" + shape + _field(4, content)  # dtype float
    meta = _field(1, _field(1, b"pr_curves"))
    value = _field(1, b"pr/cat") + _field(9, meta) + _field(8, tensor)
    event = b"\x09" + struct.pack("<d", 1700000000.0) + b"\x10\x07" + _field(5, _field(1, value))
    folder = tmp_path / "logs" / "pr"
    folder.mkdir(parents=True)
    record = struct.pack("<Q", len(event)) + b"\0" * 4 + event + b"\0" * 4
    (folder / "events.out.tfevents.1.host").write_bytes(record)

    (result,) = import_logdir(folder, "tb", dir=tmp_path / "out")

    assert result.media == 1 and not result.ignored
    reader = next(iter(_runs(tmp_path / "out").values())).reader()
    (item,) = reader.media()
    assert item.key == "pr/cat" and item.step == 7
    assert item.meta["mime"] == "application/x-nuboard-pr+json"
    data = json.loads(reader.read_media(item))
    assert data["tp"] == [3, 2, 0] and data["thresholds"] == [0, 0.5, 1]
    assert data["precision"][1] == pytest.approx(0.667, abs=1e-6)
