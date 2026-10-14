"""Encoding of the append-only event log (standard library only).

See ``docs/format.md`` for the full specification. Summary::

    file   := MAGIC frame*
    frame  := kind:u8  length:u32  crc32:u32  payload[length]

All integers and floats are little-endian. ``crc32`` is ``zlib.crc32(payload)``.
A reader stops at the first frame that is incomplete or fails its checksum, so
a torn final frame (process killed mid-write) is simply ignored.
"""

from __future__ import annotations

import struct
import sys
import zlib
from array import array

MAGIC = b"RUNLOG\x00\x01"  # 6-byte tag + 2-byte log format version
HEADER = struct.Struct("<cII")  # kind, payload length, crc32

NAME = b"N"  # metric/key id -> name:   id:u32, name:utf8
SCALARS = b"S"  # n:u32, metric_id:u32[n], step:i64[n], time:f64[n], value:f64[n]
HEARTBEAT = b"H"  # time:f64
TEXT = b"T"  # key_id:u32, step:i64, time:f64, text:utf8
MEDIA = b"M"  # key_id:u32, step:i64, time:f64, offset:u64, length:u64, meta:utf8 json
END = b"E"  # time:f64, status:utf8

_TEXT_HEAD = struct.Struct("<Iqd")
_MEDIA_HEAD = struct.Struct("<IqdQQ")
_F64 = struct.Struct("<d")
_U32 = struct.Struct("<I")

_BIG_ENDIAN = sys.byteorder == "big"

for _code, _size in (("I", 4), ("q", 8), ("d", 8)):
    if array(_code).itemsize != _size:  # pragma: no cover - exotic platforms
        raise ImportError(f"array({_code!r}) is not {_size} bytes on this platform")


def frame(kind: bytes, payload: bytes) -> bytes:
    return HEADER.pack(kind, len(payload), zlib.crc32(payload)) + payload


def name_frame(metric_id: int, name: str) -> bytes:
    return frame(NAME, _U32.pack(metric_id) + name.encode("utf-8"))


def scalars_frame(ids: array, steps: array, times: array, values: array) -> bytes:
    n = len(ids)
    if _BIG_ENDIAN:  # pragma: no cover
        ids, steps, times, values = (array(a.typecode, a) for a in (ids, steps, times, values))
        for a in (ids, steps, times, values):
            a.byteswap()
    payload = b"".join(
        (_U32.pack(n), ids.tobytes(), steps.tobytes(), times.tobytes(), values.tobytes())
    )
    return frame(SCALARS, payload)


def heartbeat_frame(t: float) -> bytes:
    return frame(HEARTBEAT, _F64.pack(t))


def text_frame(key_id: int, step: int, t: float, text: str) -> bytes:
    return frame(TEXT, _TEXT_HEAD.pack(key_id, step, t) + text.encode("utf-8"))


def media_frame(key_id: int, step: int, t: float, offset: int, length: int, meta: str) -> bytes:
    return frame(MEDIA, _MEDIA_HEAD.pack(key_id, step, t, offset, length) + meta.encode("utf-8"))


def end_frame(t: float, status: str) -> bytes:
    return frame(END, _F64.pack(t) + status.encode("utf-8"))


def iter_frames(data: bytes | memoryview, pos: int = 0):
    """Yield ``(kind, payload, end)`` for each complete, valid frame from ``pos``.

    Stops silently at a torn or corrupt frame; the caller can resume reading
    from the last ``end`` once more bytes have been appended.
    """
    view = memoryview(data)
    size = len(view)
    hsize = HEADER.size
    while pos + hsize <= size:
        kind, length, crc = HEADER.unpack_from(view, pos)
        end = pos + hsize + length
        if end > size:
            return
        payload = view[pos + hsize : end]
        if zlib.crc32(payload) != crc:
            return
        yield kind, payload, end
        pos = end


def decode_scalars_py(payload: memoryview) -> tuple[array, array, array, array]:
    """Pure-Python decode of an ``S`` payload (the viewer uses NumPy instead)."""
    (n,) = _U32.unpack_from(payload, 0)
    out = []
    pos = 4
    for code, size in (("I", 4), ("q", 8), ("d", 8), ("d", 8)):
        a = array(code)
        a.frombytes(payload[pos : pos + n * size])
        if _BIG_ENDIAN:  # pragma: no cover
            a.byteswap()
        out.append(a)
        pos += n * size
    return out[0], out[1], out[2], out[3]


def decode_name(payload: memoryview) -> tuple[int, str]:
    (mid,) = _U32.unpack_from(payload, 0)
    return mid, bytes(payload[4:]).decode("utf-8")


def decode_text(payload: memoryview) -> tuple[int, int, float, str]:
    key, step, t = _TEXT_HEAD.unpack_from(payload, 0)
    return key, step, t, bytes(payload[_TEXT_HEAD.size :]).decode("utf-8")


def decode_media(payload: memoryview) -> tuple[int, int, float, int, int, str]:
    key, step, t, off, length = _MEDIA_HEAD.unpack_from(payload, 0)
    return key, step, t, off, length, bytes(payload[_MEDIA_HEAD.size :]).decode("utf-8")


def decode_f64(payload: memoryview) -> float:
    return _F64.unpack_from(payload, 0)[0]
