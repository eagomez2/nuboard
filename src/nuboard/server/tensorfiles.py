"""Read the structure of checkpoint and array files without loading their data.

Supports PyTorch (`.pth`, `.pt`, `.ckpt`, `.bin`; zip and legacy formats),
safetensors, `.npy` and `.npz`. Only headers and the pickled structure are
read, so multi-GB files open at once, and nothing needs torch installed.

PyTorch pickles are read with an unpickler that never imports or calls
anything: every global becomes an inert placeholder, except the few torch
helpers that rebuild tensors, which are replaced by functions that record a
shape and dtype. A malicious checkpoint can therefore not run code here.

`inspect_file` never raises: a malformed, truncated or hostile file gives an
`error` message (and whatever was read before the problem).
"""

from __future__ import annotations

import ast
import collections
import io
import json
import math
import pickle
import struct
import zipfile
from pathlib import Path
from typing import Any

TORCH_SUFFIXES = (".pth", ".pt", ".ckpt", ".bin")
SUFFIXES = (*TORCH_SUFFIXES, ".safetensors", ".npy", ".npz")

MAX_PICKLE = 256 * 1024 * 1024  # bytes of pickled structure read from a checkpoint
MAX_HEADER = 100 * 1024 * 1024  # bytes of a safetensors JSON header
MAX_ENTRIES = 20_000  # entries listed; the totals still count everything
MAX_DEPTH = 64  # nesting followed in the pickled structure
MAX_MEMBERS = 10_000  # arrays read from one .npz

# Element sizes and names of PyTorch storage classes and dtypes
_STORAGE_DTYPES = {
    "DoubleStorage": "float64",
    "FloatStorage": "float32",
    "HalfStorage": "float16",
    "BFloat16Storage": "bfloat16",
    "LongStorage": "int64",
    "IntStorage": "int32",
    "ShortStorage": "int16",
    "CharStorage": "int8",
    "ByteStorage": "uint8",
    "BoolStorage": "bool",
    "ComplexDoubleStorage": "complex128",
    "ComplexFloatStorage": "complex64",
    "QInt8Storage": "qint8",
    "QUInt8Storage": "quint8",
    "QInt32Storage": "qint32",
    "UntypedStorage": "uint8",
}
_ITEMSIZE = {
    "float64": 8,
    "float32": 4,
    "float16": 2,
    "bfloat16": 2,
    "int64": 8,
    "int32": 4,
    "int16": 2,
    "int8": 1,
    "uint8": 1,
    "uint16": 2,
    "uint32": 4,
    "uint64": 8,
    "bool": 1,
    "complex128": 16,
    "complex64": 8,
    "complex32": 4,
    "qint8": 1,
    "quint8": 1,
    "qint32": 4,
    "float8_e4m3fn": 1,
    "float8_e5m2": 1,
    "float8_e4m3fnuz": 1,
    "float8_e5m2fnuz": 1,
}
_TORCH_DTYPES = {
    "float": "float32",
    "double": "float64",
    "half": "float16",
    "long": "int64",
    "int": "int32",
    "short": "int16",
    "cfloat": "complex64",
    "cdouble": "complex128",
    **{k: k for k in _ITEMSIZE},
}
_SAFETENSORS_DTYPES = {
    "F64": "float64",
    "F32": "float32",
    "F16": "float16",
    "BF16": "bfloat16",
    "I64": "int64",
    "I32": "int32",
    "I16": "int16",
    "I8": "int8",
    "U64": "uint64",
    "U32": "uint32",
    "U16": "uint16",
    "U8": "uint8",
    "BOOL": "bool",
    "F8_E4M3": "float8_e4m3fn",
    "F8_E5M2": "float8_e5m2",
    "C64": "complex64",
}


class InspectError(Exception):
    """A file that cannot be read as the format its name says."""


def inspect_file(path: Path) -> dict[str, Any]:
    """Describe the tensors and values stored in a checkpoint or array file.

    Args:
        path: The file. Its suffix picks the reader; a zip is read as a PyTorch
            archive whatever its suffix.

    Returns:
        A dict with `format`, `entries` (each with `path`, a list of keys from
        the root, and `kind`: `tensor` with `shape`, `dtype` and `bytes`, or
        `value` with `type` and a short `value`), `tensors`, `params` and
        `bytes` (totals over every tensor), `truncated` (more entries than
        listed) and `error` (None, or why the file could not be fully read).
    """
    out = _Collector()
    fmt = "unknown"

    try:
        suffix = path.suffix.lower()

        if suffix == ".safetensors":
            fmt = "safetensors"
            _read_safetensors(path, out)
        elif suffix == ".npy":
            fmt = "npy"

            with path.open("rb") as f:
                _read_npy(f, [], out)
        elif suffix == ".npz":
            fmt = "npz"
            _read_npz(path, out)
        else:
            fmt = "pytorch"
            _read_torch(path, out)
    except InspectError as exc:
        out.error = str(exc)
    except (Exception, RecursionError, MemoryError) as exc:  # never fail the request
        out.error = f"could not read the file ({type(exc).__name__}: {exc})"[:300]

    return {
        "format": fmt,
        "entries": out.entries,
        "tensors": out.tensors,
        "params": out.params,
        "bytes": out.bytes,
        "truncated": out.truncated,
        "error": out.error,
    }


class _Collector:
    """Gathers entries, with totals that keep counting past `MAX_ENTRIES`."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.tensors = 0
        self.params = 0
        self.bytes = 0
        self.truncated = False
        self.error: str | None = None

    def _add(self, entry: dict[str, Any]) -> None:
        if len(self.entries) < MAX_ENTRIES:
            self.entries.append(entry)
        else:
            self.truncated = True

    def tensor(self, path: list[str], shape: list[int], dtype: str) -> None:
        numel = math.prod(shape) if shape else 1
        size = numel * _ITEMSIZE.get(dtype, 0) if dtype in _ITEMSIZE else None
        self.tensors += 1
        self.params += numel
        self.bytes += size or 0
        self._add({"path": path, "kind": "tensor", "shape": shape, "dtype": dtype, "bytes": size})

    def value(self, path: list[str], type_: str, value: str | None) -> None:
        self._add({"path": path, "kind": "value", "type": type_, "value": value})


def _shape(v: Any) -> list[int]:
    """A shape as a list of non-negative ints, or InspectError."""

    if not isinstance(v, (list, tuple)) or len(v) > 64:
        raise InspectError("a tensor shape is not a list of sizes")

    if not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d < 2**62 for d in v):
        raise InspectError("a tensor shape has an invalid size")

    return [int(d) for d in v]


# -- safetensors ------------------------------------------------------------------------
def _read_safetensors(path: Path, out: _Collector) -> None:
    size = path.stat().st_size

    with path.open("rb") as f:
        head = f.read(8)

        if len(head) < 8:
            raise InspectError("not a safetensors file: shorter than its 8-byte header size")

        (n,) = struct.unpack("<Q", head)

        if n > MAX_HEADER or n + 8 > size:
            raise InspectError(f"not a safetensors file: header size {n} does not fit the file")

        raw = f.read(n)

    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InspectError(f"not a safetensors file: header is not JSON ({exc})") from None

    if not isinstance(header, dict):
        raise InspectError("not a safetensors file: header is not a JSON object")

    meta = header.pop("__metadata__", None)

    if isinstance(meta, dict):
        for k, v in meta.items():
            out.value(["__metadata__", str(k)], "str", str(v)[:200])

    for name in sorted(header, key=str):
        info = header[name]

        if not isinstance(info, dict):
            raise InspectError(f"tensor {name!r} has no description")

        dtype = _SAFETENSORS_DTYPES.get(str(info.get("dtype")), str(info.get("dtype")).lower())
        out.tensor([str(name)], _shape(info.get("shape")), dtype)


# -- NumPy --------------------------------------------------------------------------------
def _read_npy(f: io.BufferedIOBase | Any, path: list[str], out: _Collector) -> None:
    magic = f.read(8)

    if len(magic) < 8 or magic[:6] != b"\x93NUMPY":
        raise InspectError("not a .npy file: missing the NUMPY magic")

    major = magic[6]

    if major == 1:
        (n,) = struct.unpack("<H", f.read(2))
    elif major in (2, 3):
        (n,) = struct.unpack("<I", f.read(4))
    else:
        raise InspectError(f"unknown .npy version {major}")

    if n > 1_000_000:
        raise InspectError(".npy header is too large")

    raw = f.read(n)

    try:
        header = ast.literal_eval(raw.decode("latin-1"))  # literals only: no code runs
    except (ValueError, SyntaxError, UnicodeDecodeError, MemoryError, RecursionError):
        raise InspectError(".npy header is not readable") from None

    if not isinstance(header, dict) or "descr" not in header or "shape" not in header:
        raise InspectError(".npy header lacks descr or shape")

    out.tensor(path or ["array"], _shape(header["shape"]), _numpy_dtype(header["descr"]))


def _numpy_dtype(descr: Any) -> str:
    """A dtype name for a .npy `descr`, without building the dtype when numpy is missing."""

    try:
        import numpy as np

        dt = np.dtype(descr)
        _ITEMSIZE.setdefault(str(dt), dt.itemsize)
        return "object (pickled)" if dt.hasobject else str(dt)
    except Exception:
        return str(descr)[:60]


def _read_npz(path: Path, out: _Collector) -> None:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise InspectError("not a .npz file: not a zip archive") from None

    with zf:
        names = [n for n in zf.namelist() if n.endswith(".npy")]

        if len(names) > MAX_MEMBERS:
            out.truncated = True

        for name in names[:MAX_MEMBERS]:
            try:
                with zf.open(name) as f:
                    _read_npy(f, [name[:-4]], out)
            except InspectError as exc:
                out.value([name[:-4]], "error", str(exc))


# -- PyTorch --------------------------------------------------------------------------------
class _Tensor:
    """A tensor's shape and dtype, standing in for a rebuilt torch tensor."""

    def __init__(self, shape: list[int], dtype: str) -> None:
        self.shape = shape
        self.dtype = dtype


class _Storage:
    """A storage reference from `persistent_load`: just its dtype."""

    def __init__(self, dtype: str) -> None:
        self.dtype = dtype


class _DType:
    """A pickled `torch.<dtype>` global."""

    def __init__(self, name: str) -> None:
        self.name = _TORCH_DTYPES.get(name, name)


class _Opaque:
    """An instance of any class the pickle names; it keeps only its state."""

    _qualname = "object"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._state: Any = None

    def __setstate__(self, state: Any) -> None:
        self._state = state


def _opaque_class(module: str, name: str) -> type:
    """An inert class named after the global, which records what it is given."""

    def new(cls: type, *args: Any, **kwargs: Any) -> Any:
        obj = object.__new__(cls)
        object.__setattr__(obj, "_args", args)
        object.__setattr__(obj, "_state", None)
        return obj

    return type(name, (_Opaque,), {"_qualname": f"{module}.{name}", "__new__": new})


def _storage_dtype(storage_type: Any) -> str:
    name = getattr(storage_type, "__name__", None) or getattr(storage_type, "name", None) or ""

    if isinstance(storage_type, _DType):
        return storage_type.name

    return _STORAGE_DTYPES.get(str(name), str(name) or "unknown")


def _rebuild_tensor(storage: Any, _offset: Any = 0, size: Any = (), *rest: Any) -> _Tensor:
    # _rebuild_tensor_v2(storage, offset, size, stride, requires_grad, hooks[, metadata])
    # _rebuild_tensor_v3(storage, offset, size, stride, requires_grad, hooks, dtype, metadata)
    dtype = storage.dtype if isinstance(storage, _Storage) else "unknown"

    for r in rest:
        if isinstance(r, _DType):
            dtype = r.name

    return _Tensor(_shape(size), dtype)


def _rebuild_parameter(data: Any, *_: Any) -> Any:
    return data


def _rebuild_other(*args: Any) -> Any:
    # Quantized, sparse, nested and wrapper-subclass tensors: keep the first tensor seen
    for a in args:
        if isinstance(a, _Tensor):
            return a

        if isinstance(a, (tuple, list)):
            for b in a:
                if isinstance(b, _Tensor):
                    return b

    return _opaque_class("torch", "Tensor")()


_SAFE_GLOBALS: dict[tuple[str, str], Any] = {
    ("collections", "OrderedDict"): collections.OrderedDict,
    ("builtins", "set"): set,
    ("builtins", "frozenset"): frozenset,
    ("builtins", "complex"): complex,
    ("builtins", "slice"): slice,
    ("torch._utils", "_rebuild_tensor"): _rebuild_tensor,
    ("torch._utils", "_rebuild_tensor_v2"): _rebuild_tensor,
    ("torch._utils", "_rebuild_tensor_v3"): _rebuild_tensor,
    ("torch._utils", "_rebuild_parameter"): _rebuild_parameter,
    ("torch._utils", "_rebuild_parameter_with_state"): _rebuild_parameter,
}


class _SafeUnpickler(pickle.Unpickler):
    """Unpickles structure only: globals become inert placeholders."""

    def find_class(self, module: str, name: str) -> Any:
        hit = _SAFE_GLOBALS.get((module, name))

        if hit is not None:
            return hit

        if module == "torch" and name.endswith("Storage"):
            return _opaque_class(module, name)

        if module == "torch" and name in _TORCH_DTYPES:
            return _DType(name)

        if module.startswith("torch") and name.startswith("_rebuild"):
            return _rebuild_other

        return _opaque_class(module, name)

    def persistent_load(self, pid: Any) -> Any:
        # ("storage", storage_type, key, location, numel[, view_metadata])
        if isinstance(pid, tuple) and len(pid) >= 2 and pid[0] == "storage":
            return _Storage(_storage_dtype(pid[1]))

        return _Storage("unknown")


_MALFORMED = (
    pickle.UnpicklingError,
    EOFError,
    ValueError,
    TypeError,
    AttributeError,
    IndexError,
    KeyError,
)


def _unpickle(data: bytes | io.BufferedIOBase) -> Any:
    f = io.BytesIO(data) if isinstance(data, bytes) else data

    try:
        return _SafeUnpickler(f, encoding="latin-1").load()
    except _MALFORMED as exc:
        reason = f"{type(exc).__name__}: {exc}"[:240]
        raise InspectError(f"the pickled structure is malformed ({reason})") from None


def _read_torch(path: Path, out: _Collector) -> None:
    if zipfile.is_zipfile(path):
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise InspectError("not a PyTorch file: a broken zip archive") from None

        with zf:
            pkl = next((i for i in zf.infolist() if Path(i.filename).name == "data.pkl"), None)

            if pkl is None:
                raise InspectError("not a PyTorch checkpoint: the zip has no data.pkl")

            if pkl.file_size > MAX_PICKLE:
                raise InspectError(f"the pickled structure is too large ({pkl.file_size} bytes)")

            with zf.open(pkl) as f:
                data = f.read(MAX_PICKLE + 1)

        if len(data) > MAX_PICKLE:
            raise InspectError("the pickled structure is too large")

        _walk(_unpickle(data), [], out, 0, set())
        return

    with path.open("rb") as f:
        head = f.read(2)
        f.seek(0)

        if not head or head[0] != 0x80:
            raise InspectError("not a PyTorch checkpoint: neither a zip archive nor a pickle")

        # Legacy format: magic number, protocol version, system info, then the object
        first = _unpickle(f)

        if first == 0x1950A86A20F9469CFC6C:
            _unpickle(f)
            _unpickle(f)
            obj = _unpickle(f)
        else:
            obj = first  # a plain pickle

    _walk(obj, [], out, 0, set())


def _walk(obj: Any, path: list[str], out: _Collector, depth: int, seen: set[int]) -> None:
    """Add the tensors and plain values under `obj`, keyed by their path from the root."""

    if depth > MAX_DEPTH:
        out.value(path, "…", "nested too deeply")
        return

    if isinstance(obj, _Tensor):
        out.tensor(path, obj.shape, obj.dtype)
        return

    if isinstance(obj, (dict, list, tuple, set, frozenset, _Opaque)):
        if id(obj) in seen:
            out.value(path, "…", "already shown (a reference cycle)")
            return

        seen = seen | {id(obj)}

    if isinstance(obj, dict):
        if not obj:
            out.value(path, "dict", "{}")

        for k, v in obj.items():
            _walk(v, [*path, _key(k)], out, depth + 1, seen)

        return

    if isinstance(obj, (list, tuple)):
        if not obj:
            out.value(path, type(obj).__name__, "[]" if isinstance(obj, list) else "()")
        elif all(_is_scalar(v) for v in obj) and len(obj) <= 64:
            out.value(path, type(obj).__name__, _short(obj))
        else:
            for i, v in enumerate(obj):
                _walk(v, [*path, str(i)], out, depth + 1, seen)

        return

    if isinstance(obj, _Opaque):
        state = object.__getattribute__(obj, "_state")
        args = object.__getattribute__(obj, "_args")
        inner = state if state is not None else (args if args else None)
        name = type(obj)._qualname

        out.value(path, name, None)

        if inner is not None:
            _walk(inner, path, out, depth + 1, seen)

        return

    if isinstance(obj, (_Storage, _DType)):
        out.value(path, "torch", getattr(obj, "name", None) or getattr(obj, "dtype", ""))
        return

    out.value(path, type(obj).__name__, _short(obj))


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str, bytes, complex))


def _key(k: Any) -> str:
    return k if isinstance(k, str) else _short(k)


def _short(v: Any, limit: int = 200) -> str:
    try:
        text = repr(v)
    except Exception:
        text = f"<{type(v).__name__}>"

    return text if len(text) <= limit else text[: limit - 1] + "…"
