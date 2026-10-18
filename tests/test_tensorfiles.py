"""Checkpoint inspection: structure without data, and no crash on bad files."""

from __future__ import annotations

import collections
import io
import json
import os
import pickle
import struct
import sys
import types
import zipfile

import numpy as np
import pytest

from nuboard.server.runfiles import list_files
from nuboard.server.tensorfiles import MAX_ENTRIES, inspect_file

# -- PyTorch files written the way torch.save writes them, without torch ------------------


def _fake_torch() -> tuple[types.ModuleType, types.ModuleType]:
    """Modules named `torch` and `torch._utils` with the globals torch pickles refer to."""
    torch = types.ModuleType("torch")
    utils = types.ModuleType("torch._utils")

    for name in ("FloatStorage", "HalfStorage", "LongStorage", "BFloat16Storage"):
        setattr(torch, name, type(name, (), {"__module__": "torch"}))

    def _rebuild_tensor_v2(*args):  # pragma: no cover - only pickled, never called
        raise AssertionError

    def _rebuild_parameter(*args):  # pragma: no cover
        raise AssertionError

    for fn in (_rebuild_tensor_v2, _rebuild_parameter):
        fn.__module__ = "torch._utils"
        fn.__qualname__ = fn.__name__
        setattr(utils, fn.__name__, fn)

    return torch, utils


class _T:
    """A tensor as torch pickles it: `_rebuild_tensor_v2(storage, offset, size, stride, ...)`."""

    def __init__(self, shape, storage="FloatStorage", param=False):
        self.shape = tuple(shape)
        self.storage = storage
        self.param = param

    def __reduce__(self):
        torch = sys.modules["torch"]
        utils = sys.modules["torch._utils"]
        numel = int(np.prod(self.shape)) if self.shape else 1
        stride = tuple(int(np.prod(self.shape[i + 1 :])) for i in range(len(self.shape)))
        storage = _Persistent(("storage", getattr(torch, self.storage), "0", "cpu", numel))
        args = (storage, 0, self.shape, stride, False, collections.OrderedDict())
        tensor = (utils._rebuild_tensor_v2, args)

        if self.param:
            return (utils._rebuild_parameter, (_Rebuilt(tensor), True, collections.OrderedDict()))

        return tensor


class _Rebuilt:
    def __init__(self, reduced):
        self.reduced = reduced

    def __reduce__(self):
        return self.reduced


class _Persistent:
    def __init__(self, pid):
        self.pid = pid


class _Pickler(pickle.Pickler):
    def persistent_id(self, obj):
        return obj.pid if isinstance(obj, _Persistent) else None


def _pickle(obj) -> bytes:
    torch, utils = _fake_torch()
    saved = {k: sys.modules.get(k) for k in ("torch", "torch._utils")}
    sys.modules.update({"torch": torch, "torch._utils": utils})

    try:
        buf = io.BytesIO()
        _Pickler(buf, protocol=2).dump(obj)
        return buf.getvalue()
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _torch_zip(path, obj):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("archive/data.pkl", _pickle(obj))
        zf.writestr("archive/byteorder", "little")
        zf.writestr("archive/data/0", b"\0" * 16)
        zf.writestr("archive/version", "3\n")


def _by_path(info):
    return {"/".join(e["path"]): e for e in info["entries"]}


def test_pytorch_checkpoint_structure(tmp_path):
    ckpt = {
        "epoch": 3,
        "model": collections.OrderedDict(
            [
                ("encoder.weight", _T((256, 128))),
                ("encoder.bias", _T((256,), param=True)),
                ("head.weight", _T((10, 256), "HalfStorage")),
            ]
        ),
        "optimizer": {"state": {}, "param_groups": [{"lr": 3e-4, "betas": (0.9, 0.999)}]},
    }
    path = tmp_path / "model.pth"
    _torch_zip(path, ckpt)
    info = inspect_file(path)

    assert info["error"] is None and info["format"] == "pytorch"
    entries = _by_path(info)
    assert entries["model/encoder.weight"]["shape"] == [256, 128]
    assert entries["model/encoder.weight"]["dtype"] == "float32"
    assert entries["model/encoder.weight"]["bytes"] == 256 * 128 * 4
    assert entries["model/encoder.bias"]["shape"] == [256]  # a Parameter is its tensor
    assert entries["model/head.weight"]["dtype"] == "float16"
    assert entries["epoch"]["value"] == "3"
    assert entries["optimizer/param_groups/0/betas"]["value"] == "(0.9, 0.999)"
    assert info["tensors"] == 3
    assert info["params"] == 256 * 128 + 256 + 10 * 256


def test_legacy_pytorch_format(tmp_path):
    path = tmp_path / "old.pt"
    path.write_bytes(
        pickle.dumps(0x1950A86A20F9469CFC6C, protocol=2)
        + pickle.dumps(1001, protocol=2)
        + pickle.dumps({"little_endian": True}, protocol=2)
        + _pickle({"w": _T((4, 4), "LongStorage")})
        + b"\0" * 64
    )
    info = inspect_file(path)
    assert info["error"] is None
    assert _by_path(info)["w"]["dtype"] == "int64"


def test_unknown_classes_are_listed_not_imported(tmp_path):
    # A Lightning-style checkpoint with an argparse.Namespace of hyperparameters
    import argparse

    ckpt = {"hyper_parameters": argparse.Namespace(lr=0.1, layers=6), "state_dict": {"w": _T((2,))}}
    path = tmp_path / "last.ckpt"
    _torch_zip(path, ckpt)
    info = inspect_file(path)
    entries = _by_path(info)
    assert info["error"] is None
    assert entries["hyper_parameters"]["type"] == "argparse.Namespace"
    assert entries["hyper_parameters/lr"]["value"] == "0.1"
    assert entries["state_dict/w"]["shape"] == [2]


def test_malicious_pickle_runs_nothing(tmp_path):
    marker = tmp_path / "pwned"

    class Evil:
        def __reduce__(self):
            return (os.system, (f"touch {marker}",))

    class Evil2:
        def __reduce__(self):
            return (eval, (f"open({str(marker)!r}, 'w').write('x')",))

    for i, obj in enumerate([Evil(), {"a": Evil2()}, [Evil()]]):
        path = tmp_path / f"evil{i}.pth"

        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("archive/data.pkl", pickle.dumps(obj))

        info = inspect_file(path)
        assert isinstance(info["entries"], list)
        plain = tmp_path / f"evil{i}.pt"
        plain.write_bytes(pickle.dumps(obj))
        inspect_file(plain)

    assert not marker.exists()


def test_safetensors_npy_npz(tmp_path):
    header = {
        "__metadata__": {"format": "pt"},
        "a.weight": {"dtype": "BF16", "shape": [3, 4], "data_offsets": [0, 24]},
        "b": {"dtype": "I64", "shape": [], "data_offsets": [24, 32]},
    }
    raw = json.dumps(header).encode()
    st = tmp_path / "m.safetensors"
    st.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * 32)
    info = inspect_file(st)
    assert info["error"] is None
    assert _by_path(info)["a.weight"] == {
        "path": ["a.weight"],
        "kind": "tensor",
        "shape": [3, 4],
        "dtype": "bfloat16",
        "bytes": 24,
    }
    assert info["params"] == 13

    np.save(tmp_path / "x.npy", np.zeros((5, 2), "float32"))
    assert _by_path(inspect_file(tmp_path / "x.npy"))["array"]["shape"] == [5, 2]

    np.savez_compressed(tmp_path / "y.npz", a=np.zeros(3, "int16"), b=np.ones((2, 2)))
    entries = _by_path(inspect_file(tmp_path / "y.npz"))
    assert entries["a"]["dtype"] == "int16" and entries["b"]["bytes"] == 32


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("empty.pth", b""),
        ("noise.pth", os.urandom(4096)),
        ("text.pt", b"not a checkpoint at all\n" * 50),
        ("truncated.pth", None),  # a valid checkpoint cut in half
        ("nodata.pth", None),  # a zip without data.pkl
        ("badpickle.pth", None),  # a zip whose data.pkl is garbage
        ("cycle.pth", None),  # a structure that contains itself
        ("deep.pth", None),  # nesting far deeper than shown
        ("badshape.pth", None),  # a tensor with a negative size
        ("short.safetensors", b"\x01\x00"),
        ("huge-header.safetensors", struct.pack("<Q", 2**60) + b"{}"),
        ("not-json.safetensors", struct.pack("<Q", 5) + b"{oops"),
        ("list.safetensors", struct.pack("<Q", 2) + b"[]"),
        ("badshape.safetensors", None),
        ("bad.npy", b"\x93NUMPY\x01\x00\x10\x00{'descr': os.system}   "),
        ("version.npy", b"\x93NUMPY\x09\x00"),
        ("bad.npz", b"PK\x03\x04garbage"),
    ],
)
def test_malformed_files_never_raise(tmp_path, name, data):
    path = tmp_path / name

    if name == "truncated.pth":
        _torch_zip(tmp_path / "full.pth", {"w": _T((3, 3))})
        full = (tmp_path / "full.pth").read_bytes()
        data = full[: len(full) // 2]
    elif name == "nodata.pth":
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("archive/version", "3")
    elif name == "badpickle.pth":
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("archive/data.pkl", b"\x80\x02}q\x00(X\x01")
    elif name == "cycle.pth":
        loop: list = []
        loop.append(loop)
        _torch_zip(path, {"loop": loop})
    elif name == "deep.pth":
        deep: list = []

        for _ in range(500):
            deep = [deep, 1]

        _torch_zip(path, deep)
    elif name == "badshape.pth":
        _torch_zip(path, {"w": _T((3, -1))})
    elif name == "badshape.safetensors":
        raw = json.dumps({"w": {"dtype": "F32", "shape": ["x"], "data_offsets": [0, 0]}}).encode()
        data = struct.pack("<Q", len(raw)) + raw

    if data is not None:
        path.write_bytes(data)

    info = inspect_file(path)
    json.dumps(info)  # the result is always plain JSON
    assert set(info) >= {"format", "entries", "tensors", "params", "bytes", "error"}

    if name not in ("cycle.pth", "deep.pth"):
        assert info["error"], name
    else:
        assert any(e["kind"] == "value" for e in info["entries"])


def test_many_tensors_are_capped_but_counted(tmp_path):
    n = MAX_ENTRIES + 50
    header = {f"t{i}": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]} for i in range(n)}
    raw = json.dumps(header).encode()
    path = tmp_path / "many.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    info = inspect_file(path)
    assert len(info["entries"]) == MAX_ENTRIES and info["truncated"]
    assert info["tensors"] == n and info["params"] == 2 * n


def test_run_folder_listing(tmp_path):
    run = tmp_path / "run"
    (run / "files").mkdir(parents=True)
    (run / "checkpoints" / "sched").mkdir(parents=True)
    (run / "run.json").write_text("{}")
    (run / "events.r0.s0.log").write_bytes(b"\0" * 10)
    (run / "files" / "config.yaml").write_text("lr: 1\n")
    (run / "files" / "README").write_text("plain text without a suffix\n")
    (run / "checkpoints" / "sched" / "e1.pth").write_bytes(b"x" * 100)
    (run / "blob").write_bytes(b"\0\1\2")
    outside = tmp_path / "secret.txt"
    outside.write_text("no")

    try:
        (run / "files" / "link.txt").symlink_to(outside)
    except OSError:  # pragma: no cover - no symlinks on this system
        pass

    listing = list_files(run)
    files = {f["path"]: f for f in listing["files"]}
    assert "files/link.txt" not in files
    assert files["run.json"]["internal"] and not files["files/config.yaml"]["internal"]
    assert files["files/config.yaml"]["kind"] == "text"
    assert files["files/README"]["kind"] == "text"
    assert files["checkpoints/sched/e1.pth"] == {
        **files["checkpoints/sched/e1.pth"],
        "kind": "tensors",
        "size": 100,
    }
    assert files["blob"]["kind"] == "other"
    assert listing["count"] == 6 and listing["bytes"] == sum(f["size"] for f in files.values())
