"""Conversion of images, audio, figures and HTML into bytes for the media pack.

Standard library only: image arrays are PNG-encoded with `zlib` and audio
arrays WAV-encoded with `wave`; figure libraries are used only if the object
passed in already comes from them.
"""

from __future__ import annotations

import io
import json
import os
import struct
import wave
import zlib
from typing import Any


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """Build one PNG chunk: length, tag, data and CRC32."""
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def encode_png(pixels: bytes, width: int, height: int, channels: int) -> bytes:
    """Encode 8-bit `pixels` as a PNG image.

    Args:
        pixels: Row-major pixel bytes, `channels` bytes per pixel.
        width: Image width in pixels.
        height: Image height in pixels.
        channels: 1 (gray), 2 (gray and alpha), 3 (RGB) or 4 (RGBA).

    Returns:
        The PNG file bytes.

    Raises:
        KeyError: If `channels` is not 1 to 4.
    """
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
    """Encode an image array as PNG.

    Torch tensors are moved to the CPU first. A 3-D array whose first axis is
    1, 3 or 4 and whose last axis is not is taken as CxHxW. Floats are clipped
    to [0, 1] and scaled to 0-255; other non-uint8 arrays are clipped to
    0-255.

    Args:
        arr: An HxW, HxWxC or CxHxW array (uint8, or float in [0, 1]), such as
            a NumPy array or a torch tensor.

    Returns:
        The PNG file bytes.

    Raises:
        ValueError: If the array is not 2-D or 3-D.
    """

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
    """Convert an image to bytes plus its MIME type.

    Bytes and files are passed through unchanged, with the type guessed from
    their first bytes; PIL images and arrays are encoded as PNG.

    Args:
        img: Encoded image bytes, a file path, a PIL image or an array.

    Returns:
        `(bytes, mime type)`.

    Raises:
        TypeError: If `img` is none of the supported types.
    """

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
    """Guess an image MIME type from the first bytes of `data`."""

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
    """Serialize a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure.

    Plotly, Vega-Lite and Bokeh figures are stored as JSON specs for the
    viewer to render; matplotlib figures (or the `pyplot` module) as SVG.
    Plain dicts are accepted as Vega-Lite specs (with a Vega `$schema`) or
    Plotly figure dicts (with a `data` list).

    Args:
        fig: The figure object or spec dict.

    Returns:
        `(bytes, mime type)`.

    Raises:
        TypeError: If `fig` is none of the supported types.
    """
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


# -- audio ------------------------------------------------------------------------

_AUDIO_EXT = {
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".webm": "audio/webm",
}


def array_to_wav(arr: Any, sample_rate: int) -> tuple[bytes, dict[str, Any]]:
    """Encode an audio array as 16-bit PCM WAV.

    Floats are taken as [-1, 1] and clipped (NaN becomes 0); integer arrays
    are taken as int16 samples (int32 is scaled down). The shorter axis is the
    channel axis. Torch tensors are moved to the CPU first.

    Args:
        arr: A mono (N,) or multichannel (C, N) / (N, C) array.
        sample_rate: Samples per second.

    Returns:
        `(wav bytes, info)`, where `info` holds `sample_rate`, `channels` and
        `duration` in seconds.

    Raises:
        ValueError: If the array is not 1-D or 2-D, or has more than 16
            channels.
    """

    if hasattr(arr, "detach"):  # torch tensor
        arr = arr.detach().cpu().numpy()

    import numpy as np  # arrays only come from code that already has NumPy

    a = np.asarray(arr)

    if a.ndim == 1:
        a = a[:, None]
    elif a.ndim == 2:
        if a.shape[0] < a.shape[1]:
            a = a.T  # (C, N) -> (N, C)
    else:
        raise ValueError(f"cannot interpret array of shape {a.shape} as audio")

    if a.shape[1] > 16:
        raise ValueError(f"{a.shape[1]} channels; expected (samples,) or (channels, samples)")

    if a.dtype.kind == "f":
        pcm = (np.clip(np.nan_to_num(a), -1.0, 1.0) * 32767.0).round().astype("<i2")
    elif a.dtype.itemsize >= 4:
        pcm = (a >> (8 * a.dtype.itemsize - 16)).astype("<i2")
    else:
        pcm = a.astype("<i2")

    buf = io.BytesIO()

    with wave.open(buf, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(np.ascontiguousarray(pcm).tobytes())

    info = {
        "sample_rate": int(sample_rate),
        "channels": int(pcm.shape[1]),
        "duration": round(pcm.shape[0] / sample_rate, 6),
    }
    return buf.getvalue(), info


def audio_bytes(audio: Any, sample_rate: int | None) -> tuple[bytes, str, dict[str, Any]]:
    """Convert audio to bytes, its MIME type and playback info.

    Files and bytes are stored as they are, with the format recognized from
    their first bytes (or, for a file, its extension); arrays are encoded as
    WAV. `info` is filled for WAV data only.

    Args:
        audio: An audio file path, encoded audio bytes or an array.
        sample_rate: Samples per second; required for arrays, ignored
            otherwise.

    Returns:
        `(bytes, mime type, info)`, where `info` may hold `sample_rate`,
        `channels` and `duration`.

    Raises:
        ValueError: If the file or bytes are not a recognized audio format, or
            `sample_rate` is missing for an array.
        TypeError: If `audio` is none of the supported types.
    """

    if isinstance(audio, (str, os.PathLike)):
        path = os.fspath(audio)

        with open(path, "rb") as f:
            data = f.read()

        mime = _sniff_audio(data) or _AUDIO_EXT.get(os.path.splitext(path)[1].lower())

        if mime is None:
            raise ValueError(f"unrecognized audio file {path!r}")

        return data, mime, _wav_info(data) if mime == "audio/wav" else {}

    if isinstance(audio, (bytes, bytearray, memoryview)):
        data = bytes(audio)
        mime = _sniff_audio(data)

        if mime is None:
            raise ValueError("unrecognized audio bytes; pass a file path or an array")

        return data, mime, _wav_info(data) if mime == "audio/wav" else {}

    if hasattr(audio, "shape"):
        if not sample_rate:
            raise ValueError("sample_rate is required when logging an array")

        data, info = array_to_wav(audio, sample_rate)
        return data, "audio/wav", info

    raise TypeError(f"unsupported audio type {type(audio).__name__}")


def _sniff_audio(data: bytes) -> str | None:
    """Guess an audio MIME type from the first bytes of `data`, or return None."""

    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"

    if data[:4] == b"fLaC":
        return "audio/flac"

    if data[:4] == b"OggS":
        return "audio/ogg"

    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"

    if data[4:8] == b"ftyp":
        return "audio/mp4"

    if data[:4] == b"\x1aE\xdf\xa3":
        return "audio/webm"

    return None


def _wav_info(data: bytes) -> dict[str, Any]:
    """Read sample rate, channels and duration from WAV bytes; empty if unreadable."""

    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, frames = w.getframerate(), w.getnframes()
            return {
                "sample_rate": rate,
                "channels": w.getnchannels(),
                "duration": round(frames / rate, 6) if rate else None,
            }
    except (wave.Error, EOFError):  # e.g. float WAV, which `wave` does not read
        return {}
