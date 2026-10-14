"""Conversion of images, figures and HTML into bytes for the media pack.

Standard library only: arrays are PNG-encoded with ``zlib``; figure libraries
are used only if the object passed in already comes from them.
"""

from __future__ import annotations

import io
import json
import os
import struct
import zlib
from typing import Any


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def encode_png(pixels: bytes, width: int, height: int, channels: int) -> bytes:
    """Encode 8-bit ``pixels`` (row-major, ``channels`` per pixel) as PNG."""
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\x00" + pixels[y * stride : (y + 1) * stride] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 6))
        + _png_chunk(b"IEND", b"")
    )


def array_to_png(arr: Any) -> bytes:
    """Encode an HxW, HxWxC or CxHxW array (uint8, or float in [0, 1]) as PNG."""
    if hasattr(arr, "detach"):  # torch tensor
        arr = arr.detach().cpu().numpy()
    shape = tuple(arr.shape)
    if len(shape) == 3 and shape[0] in (1, 3, 4) and shape[2] not in (1, 3, 4):
        arr = arr.transpose(1, 2, 0)  # CHW -> HWC
        shape = tuple(arr.shape)
    if len(shape) == 2:
        h, w, c = shape[0], shape[1], 1
    elif len(shape) == 3:
        h, w, c = shape
    else:
        raise ValueError(f"cannot interpret array of shape {shape} as an image")
    if arr.dtype.kind == "f":
        arr = (arr.clip(0, 1) * 255 + 0.5).astype("uint8")
    elif arr.dtype.name != "uint8":
        arr = arr.clip(0, 255).astype("uint8")
    return encode_png(arr.tobytes(order="C"), w, h, c)


def image_bytes(img: Any) -> tuple[bytes, str]:
    """Return (bytes, mime type) for bytes, a path, a PIL image or an array."""
    if isinstance(img, (bytes, bytearray, memoryview)):
        data = bytes(img)
        return data, _sniff(data)
    if isinstance(img, (str, os.PathLike)):
        with open(img, "rb") as f:
            data = f.read()
        return data, _sniff(data)
    if hasattr(img, "save") and hasattr(img, "mode"):  # PIL.Image
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    if hasattr(img, "shape"):
        return array_to_png(img), "image/png"
    raise TypeError(f"unsupported image type {type(img).__name__}")


def _sniff(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.lstrip()[:5] in (b"<svg ", b"<?xml"):
        return "image/svg+xml"
    return "application/octet-stream"


def figure_bytes(fig: Any) -> tuple[bytes, str]:
    """Serialize a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure."""
    module = type(fig).__module__.split(".")[0]
    if module == "plotly" or hasattr(fig, "to_plotly_json"):
        return fig.to_json().encode("utf-8"), "application/vnd.plotly.v1+json"
    if module == "altair":
        return json.dumps(fig.to_dict()).encode("utf-8"), "application/vnd.vegalite+json"
    if module == "bokeh":
        from bokeh.embed import json_item  # type: ignore[import-not-found]

        return json.dumps(json_item(fig)).encode("utf-8"), "application/vnd.bokeh+json"
    if hasattr(fig, "savefig"):  # matplotlib Figure (or pyplot module)
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", bbox_inches="tight")
        return buf.getvalue(), "image/svg+xml"
    if isinstance(fig, dict) and "$schema" in fig and "vega" in str(fig["$schema"]):
        return json.dumps(fig).encode("utf-8"), "application/vnd.vegalite+json"
    if isinstance(fig, dict) and isinstance(fig.get("data"), list):  # Plotly figure dict
        return json.dumps(fig).encode("utf-8"), "application/vnd.plotly.v1+json"
    raise TypeError(f"unsupported figure type {type(fig).__name__}")
