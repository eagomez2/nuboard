"""Conversion of images, audio, video, figures, point clouds, PR curves and HTML into pack bytes.

Standard library only: image arrays are PNG-encoded with `zlib`, video arrays
as animated PNG the same way (rows filtered with NumPy, which arrays imply),
audio arrays WAV-encoded with `wave`, point clouds packed with `array` and PR
curves counted in plain Python; figure libraries are used only if the object
passed in already comes from them.
"""

from __future__ import annotations

import array
import bisect
import io
import itertools
import json
import math
import os
import struct
import sys
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


# -- video ------------------------------------------------------------------------
_VIDEO_EXT = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".gif": "image/gif",
    ".png": "image/apng",
    ".apng": "image/apng",
}


def _sniff_video(data: bytes) -> str | None:
    """Guess a video MIME type from the first bytes of `data`, or return None."""

    if data[4:8] == b"ftyp":
        return "video/quicktime" if data[8:12] == b"qt  " else "video/mp4"

    if data[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"

    if data[:4] == b"OggS":
        return "video/ogg"

    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    if data.startswith(b"\x89PNG") and b"acTL" in data[:4096]:
        return "image/apng"

    return None


def video_frames(arr: Any) -> Any:
    """Return a video array as uint8 frames of shape (T, H, W, C).

    Args:
        arr: A (T, H, W), (T, H, W, C) or (T, C, H, W) array or tensor, or a
            (N, T, C, H, W) batch as TensorBoard takes it, whose N videos are
            tiled in a grid. C is 1, 3 or 4; floats are read as 0 to 1.

    Returns:
        A NumPy uint8 array of shape (T, H, W, C).

    Raises:
        ValueError: If the array is not 3-D to 5-D, or C is not 1, 3 or 4.
    """
    import numpy as np  # video arrays only come from code that already has NumPy

    if hasattr(arr, "detach"):  # torch tensor
        arr = (
            arr.detach().cpu().float().numpy()
            if arr.is_floating_point()
            else arr.detach().cpu().numpy()
        )

    a = np.asarray(arr)

    if a.ndim == 5:  # (N, T, C, H, W): tile the N videos in a grid
        n, t, c, h, w = a.shape
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        pad = np.zeros((rows * cols - n, t, c, h, w), a.dtype)
        a = np.concatenate([a, pad]).reshape(rows, cols, t, c, h, w)
        a = a.transpose(2, 0, 4, 1, 5, 3).reshape(t, rows * h, cols * w, c)
    elif a.ndim == 4 and a.shape[1] in (1, 3, 4) and a.shape[3] not in (1, 3, 4):
        a = a.transpose(0, 2, 3, 1)  # (T, C, H, W) -> (T, H, W, C)
    elif a.ndim == 3:
        a = a[..., None]
    elif a.ndim != 4:
        raise ValueError(f"cannot interpret array of shape {a.shape} as a video")

    if a.shape[3] not in (1, 3, 4):
        raise ValueError(f"{a.shape[3]} channels; a video takes 1, 3 or 4")

    if a.dtype.kind == "f":
        a = (np.nan_to_num(a).clip(0, 1) * 255 + 0.5).astype(np.uint8)
    elif a.dtype != np.uint8:
        a = a.clip(0, 255).astype(np.uint8)

    return np.ascontiguousarray(a)


def encode_apng(frames: Any, fps: float) -> bytes:
    """Encode uint8 frames of shape (T, H, W, C) as an animated PNG that loops.

    Each row is stored as its difference to the row above (PNG's Up filter),
    which compresses smooth frames well.

    Args:
        frames: The frames, as returned by `video_frames`.
        fps: Frames per second.

    Returns:
        The APNG file bytes.
    """
    import numpy as np

    t, h, w, c = frames.shape
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    den = max(1, min(65535, round(fps * 100)))
    out = [
        b"\x89PNG\r\n\x1a\n",
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)),
        _png_chunk(b"acTL", struct.pack(">II", t, 0)),
    ]
    seq = 0

    for i, frame in enumerate(frames):
        rows = frame.reshape(h, w * c)
        up = rows.copy()
        up[1:] = rows[1:] - rows[:-1]  # uint8 wraps around, as the filter wants
        raw = np.concatenate([np.full((h, 1), 2, np.uint8), up], axis=1).tobytes()
        data = zlib.compress(raw, 6)
        fctl = struct.pack(">IIIIIHHBB", seq, w, h, 0, 0, 100, den, 0, 0)
        out.append(_png_chunk(b"fcTL", fctl))
        seq += 1

        if i == 0:
            out.append(_png_chunk(b"IDAT", data))
        else:
            out.append(_png_chunk(b"fdAT", struct.pack(">I", seq) + data))
            seq += 1

    out.append(_png_chunk(b"IEND", b""))
    return b"".join(out)


def video_bytes(video: Any, fps: float = 4) -> tuple[bytes, str, dict[str, Any]]:
    """Convert a video to bytes, its MIME type and playback info.

    Files and bytes are stored as they are, with the format recognized from
    their first bytes (or, for a file, its extension); arrays are encoded as
    an animated PNG.

    Args:
        video: A video file path, encoded video bytes, or an array (see
            `video_frames`).
        fps: Frames per second of an array; ignored for files and bytes.

    Returns:
        `(bytes, mime type, info)`, where `info` holds `fps`, `frames`,
        `width`, `height` and `duration` for arrays, and is empty otherwise.

    Raises:
        ValueError: If the file or bytes are not a recognized video format, or
            the array has an unsupported shape.
        TypeError: If `video` is none of the supported types.
    """

    if isinstance(video, (str, os.PathLike)):
        path = os.fspath(video)

        with open(path, "rb") as f:
            data = f.read()

        mime = _sniff_video(data) or _VIDEO_EXT.get(os.path.splitext(path)[1].lower())

        if mime is None:
            raise ValueError(f"unrecognized video file {path!r}")

        return data, mime, {}

    if isinstance(video, (bytes, bytearray, memoryview)):
        data = bytes(video)
        mime = _sniff_video(data)

        if mime is None:
            raise ValueError("unrecognized video bytes; pass a file path or an array")

        return data, mime, {}

    if hasattr(video, "shape"):
        frames = video_frames(video)
        t, h, w, _ = frames.shape
        info = {
            "fps": fps,
            "frames": t,
            "width": w,
            "height": h,
            "duration": round(t / fps, 6),
        }
        return encode_apng(frames, fps), "image/apng", info

    raise TypeError(f"unsupported video type {type(video).__name__}")


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


#: MIME type of waveforms with signals in the media pack (see `waveform_bytes`)
WAVEFORM_MIME = "application/x-nuboard-waveform"


def waveform_signals(audio: Any, signals: Any) -> tuple[Any, dict[str, Any]]:
    """Check a waveform's signals against its audio and copy both.

    Args:
        audio: A `(samples,)` or `(channels, samples)` array or tensor.
        signals: An array or tensor of `samples` values, or a dict of them by name.

    Returns:
        The audio as a NumPy array of its own and the signals as float32
        arrays by name.

    Raises:
        ValueError: If the audio is not 1-D or 2-D, or a signal is not 1-D or
            does not hold one value per sample.
    """

    import numpy as np  # arrays only come from code that already has NumPy

    def array(x: Any) -> Any:
        if hasattr(x, "detach"):  # torch tensor
            x = x.detach().cpu().float() if str(x.dtype) == "torch.bfloat16" else x.detach().cpu()
            x = x.numpy()

        return np.array(x)  # a copy: the caller may reuse its buffer

    a = array(audio)

    if a.ndim not in (1, 2):
        raise ValueError(f"cannot interpret array of shape {a.shape} as audio")

    samples = max(a.shape)
    named = signals if isinstance(signals, dict) else {"signal": signals}

    if not named:
        raise ValueError("a waveform needs at least one signal")

    out = {}

    for name, values in named.items():
        v = array(values).astype("<f4")

        if v.ndim != 1 or v.shape[0] != samples:
            raise ValueError(
                f"signal {name!r} has shape {v.shape}; expected ({samples},), one value per sample"
            )

        out[str(name)] = v

    return a, out


def waveform_regions(regions: Any) -> dict[str, list[list[Any]]]:
    """Check a waveform's region tracks and convert each to `[start, end, label]` segments.

    Args:
        regions: A dict of tracks by name. A track is a sequence of
            `(start, end, label)` in seconds, which may overlap, or a
            `(classes, names, frame)` tuple: per frame, a class id (a 1-D
            array, tensor or sequence of integers) or the classes that are on
            (a 2-D `(frames, classes)` multi-hot array, for labels that can
            overlap), then the class names and the frame length in seconds.

    Returns:
        The segments of each track, in time order; consecutive frames of one
        class become one segment.

    Raises:
        ValueError: If a segment ends before it starts, a class id has no
            name, a multi-hot row does not have one value per name, or the
            frame length is not positive.
        TypeError: If `regions` is not a dict.
    """

    if not isinstance(regions, dict):
        raise TypeError(f"regions must be a dict of tracks by name, not {type(regions).__name__}")

    out: dict[str, list[list[Any]]] = {}

    for name, track in regions.items():
        frames = (
            isinstance(track, tuple)
            and len(track) == 3
            and not isinstance(track[1], (int, float))
            and isinstance(track[2], (int, float))
        )

        if frames:
            classes, names, frame = track[0], [str(n) for n in track[1]], float(track[2])

            if not frame > 0:
                raise ValueError(f"track {name!r}: the frame length must be positive, not {frame}")

            if hasattr(classes, "detach"):  # torch tensor
                classes = classes.detach().cpu().numpy()

            segments: list[list[Any]] = []
            multi = getattr(classes, "ndim", None) == 2 or (
                not hasattr(classes, "ndim") and len(classes) and hasattr(classes[0], "__len__")
            )

            if multi:
                # several classes can be on at once: each class's runs of frames, in time order
                rows = [list(r) for r in classes]

                if any(len(r) != len(names) for r in rows):
                    raise ValueError(f"track {name!r}: each multi-hot row needs one value per name")

                for c, label in enumerate(names):
                    start = None

                    for i, row in enumerate([*rows, [0] * len(names)]):
                        if row[c] and start is None:
                            start = i
                        elif not row[c] and start is not None:
                            segments.append([round(start * frame, 6), round(i * frame, 6), label])
                            start = None

                out[str(name)] = sorted(segments, key=lambda g: (g[0], g[1]))
                continue

            for i, raw in enumerate(_values(classes)):
                k = int(raw)

                if not 0 <= k < len(names):
                    raise ValueError(f"track {name!r}: class id {k} has no name in {names}")

                if segments and segments[-1][2] == names[k]:  # frames are contiguous
                    segments[-1][1] = round((i + 1) * frame, 6)
                else:
                    segments.append([round(i * frame, 6), round((i + 1) * frame, 6), names[k]])
        else:
            segments = []

            for seg in track:
                start, end, label = float(seg[0]), float(seg[1]), str(seg[2])

                if not end >= start:
                    raise ValueError(f"track {name!r}: segment {tuple(seg)} ends before it starts")

                segments.append([round(start, 6), round(end, 6), label])

            segments.sort(key=lambda g: (g[0], g[1]))

        out[str(name)] = segments

    return out


def waveform_bytes(
    audio: Any,
    sample_rate: int,
    signals: dict[str, Any],
    value_range: tuple[float, float] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Pack a waveform as WAV bytes followed by its signals as float32.

    Args:
        audio: The audio array (see `waveform_signals`).
        sample_rate: Samples per second.
        signals: Float32 arrays of one value per sample, by name.
        value_range: The values at the bottom and top of the waveform; -1
            and 1 (the waveform's own full scale) when None.

    Returns:
        The bytes (the WAV, then each signal as little-endian float32, in
        order), the MIME type and metadata: the audio info, `audio_bytes`
        (the WAV's length), `samples`, the `signals` names and the `range`.
    """

    wav, info = array_to_wav(audio, sample_rate)
    lo, hi = (-1.0, 1.0) if value_range is None else value_range

    meta = {
        **info,
        "audio_bytes": len(wav),
        "samples": int(next(iter(signals.values())).shape[0]),
        "signals": list(signals),
        "range": [float(lo), float(hi)],
    }
    data = wav + b"".join(v.astype("<f4").tobytes() for v in signals.values())
    return data, WAVEFORM_MIME, meta


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


#: MIME type of point clouds in the media pack (see `points_bytes`)
POINTS_MIME = "application/x-nuboard-points"


def _flat(values: Any, kind: str, width: int, name: str) -> tuple[array.array, int]:
    """Return an N x `width` array or nested sequence as a flat `array` and N.

    Args:
        values: A NumPy array, torch tensor or sequence of rows.
        kind: The `array` type code to convert to (`f` or `B`).
        width: The number of values per row.
        name: The argument name, for error messages.

    Returns:
        The flat values and the number of rows.

    Raises:
        ValueError: If the rows do not hold `width` values each.
    """

    if hasattr(values, "detach"):  # torch tensor
        values = values.detach().cpu().numpy()

    if hasattr(values, "shape") and hasattr(values, "tobytes"):  # NumPy array
        shape = tuple(values.shape)

        if len(shape) != 2 or shape[1] != width:
            raise ValueError(f"{name} must have shape (N, {width}), not {shape}")

        dtype = "<f4" if kind == "f" else "uint8"
        out = array.array(kind, values.astype(dtype).tobytes(order="C"))

        if sys.byteorder == "big" and kind == "f":
            out.byteswap()  # read back as little-endian below

        return out, shape[0]

    rows = [list(r) for r in values]

    if any(len(r) != width for r in rows):
        raise ValueError(f"each row of {name} must hold {width} values")

    return array.array(kind, [v for r in rows for v in r]), len(rows)


def points_bytes(points: Any, colors: Any = None) -> tuple[bytes, str, dict[str, Any]]:
    """Pack a point cloud as little-endian float32 positions and optional RGB bytes.

    Args:
        points: An (N, 3) array, tensor or sequence of x, y, z positions.
        colors: An optional (N, 3) array or sequence of RGB colors, as uint8
            values or floats in [0, 1].

    Returns:
        The bytes (N x 12 bytes of positions, then N x 3 bytes of colors if
        given), the MIME type and the `points` and `colors` metadata.

    Raises:
        ValueError: If the shapes do not match.
    """

    xyz, n = _flat(points, "f", 3, "points")

    if sys.byteorder == "big":
        xyz.byteswap()

    data = xyz.tobytes()

    if colors is not None:
        if hasattr(colors, "detach"):
            colors = colors.detach().cpu().numpy()

        floats = getattr(getattr(colors, "dtype", None), "kind", "") == "f" or (
            not hasattr(colors, "dtype") and any(isinstance(v, float) for r in colors for v in r)
        )

        if floats:
            scaled, m = _flat(colors, "f", 3, "colors")
            rgb = array.array("B", [min(255, max(0, round(v * 255))) for v in scaled])
        else:
            rgb, m = _flat(colors, "B", 3, "colors")

        if m != n:
            raise ValueError(f"colors has {m} rows but points has {n}")

        data += rgb.tobytes()

    return data, POINTS_MIME, {"points": n, "colors": colors is not None}


#: MIME type of precision-recall curves in the media pack (see `pr_curve_bytes`)
PR_MIME = "application/x-nuboard-pr+json"


def _values(x: Any) -> list[Any]:
    """Return a flat list of the values of an array, tensor or sequence."""

    if hasattr(x, "detach"):  # torch tensor
        x = x.detach().cpu().numpy()

    if hasattr(x, "ravel"):  # NumPy array
        return x.ravel().tolist()

    return list(x)


def pr_curve_json(counts: dict[str, list[float]]) -> tuple[bytes, str, dict[str, Any]]:
    """Encode precision-recall counts per threshold as the stored JSON.

    Args:
        counts: `tp`, `fp`, `tn` and `fn` lists (one value per threshold, the
            thresholds evenly spaced from 0 to 1), and optionally `precision`
            and `recall`, which are computed from the counts when missing.

    Returns:
        The JSON bytes, the MIME type and the `thresholds` and `positives`
        metadata.

    Raises:
        ValueError: If the lists have different lengths or fewer than 2 values.
    """

    tp, fp, tn, fn = (list(map(float, counts[k])) for k in ("tp", "fp", "tn", "fn"))
    n = len(tp)

    if n < 2 or any(len(v) != n for v in (fp, tn, fn)):
        raise ValueError("tp, fp, tn and fn need the same length, at least 2")

    precision = counts.get("precision") or [
        a / (a + b) if a + b > 0 else 1.0 for a, b in zip(tp, fp, strict=True)
    ]
    recall = counts.get("recall") or [
        a / (a + b) if a + b > 0 else 0.0 for a, b in zip(tp, fn, strict=True)
    ]
    data = {
        "thresholds": [round(i / (n - 1), 6) for i in range(n)],
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": [round(float(v), 6) for v in precision],
        "recall": [round(float(v), 6) for v in recall],
    }
    meta = {"thresholds": n, "positives": tp[0] + fn[0]}
    return json.dumps(data, separators=(",", ":")).encode("utf-8"), PR_MIME, meta


def pr_curve_bytes(
    labels: Any, predictions: Any, num_thresholds: int = 201, weights: Any = None
) -> tuple[bytes, str, dict[str, Any]]:
    """Count true and false positives at evenly spaced thresholds, as TensorBoard does.

    A prediction counts as positive at threshold `t` when it is at least `t`;
    predictions are clipped to [0, 1] and bucketed, so the cost is one pass
    over the data and the result has `num_thresholds` values per count.

    Args:
        labels: Ground truth, as booleans or 0/1 values.
        predictions: Scores in [0, 1], one per label.
        num_thresholds: How many thresholds, from 0 to 1 inclusive.
        weights: Optional weight per example (defaults to 1).

    Returns:
        The JSON bytes, the MIME type and metadata (see `pr_curve_json`).

    Raises:
        ValueError: If the inputs have different lengths or are empty.
    """

    y = _values(labels)
    p = _values(predictions)
    w = _values(weights) if weights is not None else None

    if not y or len(y) != len(p) or (w is not None and len(w) != len(y)):
        raise ValueError("labels, predictions and weights need the same, non-zero length")

    if num_thresholds < 2:
        raise ValueError("num_thresholds must be at least 2")

    top = num_thresholds - 1
    pos = [0.0] * num_thresholds  # weight of positives per bucket
    neg = [0.0] * num_thresholds

    for i, (label, score) in enumerate(zip(y, p, strict=True)):
        bucket = int(min(max(float(score), 0.0), 1.0) * top)
        weight = float(w[i]) if w is not None else 1.0

        if label:
            pos[bucket] += weight
        else:
            neg[bucket] += weight

    # At threshold i, every prediction in bucket i or above is positive
    tp, fp = [0.0] * num_thresholds, [0.0] * num_thresholds
    run_pos = run_neg = 0.0

    for i in range(top, -1, -1):
        run_pos += pos[i]
        run_neg += neg[i]
        tp[i], fp[i] = run_pos, run_neg

    fn = [tp[0] - v for v in tp]
    tn = [fp[0] - v for v in fp]
    return pr_curve_json({"tp": tp, "fp": fp, "tn": tn, "fn": fn})


#: MIME type of distributions in the media pack (see `histogram_json`)
HISTOGRAM_MIME = "application/x-nuboard-histogram+json"


def _number(v: float | None) -> float | None:
    """Return `v` rounded for JSON, or None when it is missing or not finite."""
    return None if v is None or not math.isfinite(v) else float(f"{v:.7g}")


def histogram_json(
    edges: list[float],
    counts: list[float],
    *,
    stats: dict[str, float | None] | None = None,
    outside: float = 0.0,
    nonfinite: float = 0.0,
) -> tuple[bytes, str, dict[str, Any]]:
    """Encode a histogram as the stored JSON.

    Args:
        edges: Bin edges, one more than `counts`, increasing.
        counts: Count (or total weight) per bin.
        stats: Optional `min`, `max`, `mean` and `std` of the values; missing
            ones are left out.
        outside: Count of finite values outside the edges.
        nonfinite: Count of NaN and infinite values, which are not binned.

    Returns:
        The JSON bytes, the MIME type and the `bins` and `count` metadata.

    Raises:
        ValueError: If the lengths do not match or there are no bins.
    """

    if not counts or len(edges) != len(counts) + 1:
        raise ValueError("a histogram needs at least one bin and one more edge than bins")

    data: dict[str, Any] = {
        "edges": [_number(float(e)) for e in edges],
        "counts": [float(f"{float(c):.7g}") for c in counts],
    }
    total = float(f"{sum(data['counts']) + outside:.7g}")

    for name, value in (stats or {}).items():
        if _number(value) is not None:
            data[name] = _number(value)

    data["count"] = total

    if outside:
        data["outside"] = outside

    if nonfinite:
        data["nonfinite"] = nonfinite

    meta = {"bins": len(counts), "count": total}
    return json.dumps(data, separators=(",", ":")).encode("utf-8"), HISTOGRAM_MIME, meta


def _edges(lo: float, hi: float, bins: int) -> list[float]:
    """Return `bins + 1` evenly spaced edges from `lo` to `hi` (widened when equal)."""

    if bins < 1:
        raise ValueError("bins must be at least 1")

    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5

    return [lo + (hi - lo) * i / bins for i in range(bins)] + [hi]


def _bin_edges(
    bins: int | Any, span: tuple[float, float] | None, stats: dict[str, float | None]
) -> list[float]:
    """Return the edges for `bins` (a count or edges) over `span` or the values' range."""

    if isinstance(bins, int):
        lo, hi = span or (stats.get("min") or 0.0, stats.get("max") or 0.0)
        return _edges(float(lo), float(hi), bins)

    edges = [float(e) for e in bins]

    if len(edges) < 2 or any(b <= a for a, b in itertools.pairwise(edges)):
        raise ValueError("bin edges must be increasing")

    return edges


def histogram_bytes(
    values: Any, bins: int | Any = 50, range: tuple[float, float] | None = None, weights: Any = None
) -> tuple[bytes, str, dict[str, Any]]:
    """Bin values into a histogram, with their min, max, mean and standard deviation.

    NumPy arrays and tensors are binned with NumPy; other sequences in pure
    Python. NaN and infinite values are counted but not binned, and finite
    values outside `range` are counted as `outside`.

    Args:
        values: The values, as an array, tensor or sequence of any shape.
        bins: Number of equal-width bins, or a sequence of increasing edges.
        range: The `(low, high)` the bins span. Defaults to the values' range.
        weights: Optional weight per value, of the same shape.

    Returns:
        The JSON bytes, the MIME type and metadata (see `histogram_json`).

    Raises:
        ValueError: If `weights` does not match `values` or the edges are not
            increasing.
    """

    if hasattr(values, "detach"):
        values = values.detach().cpu().numpy()

    if hasattr(weights, "detach"):
        weights = weights.detach().cpu().numpy()

    if hasattr(values, "__array__"):
        import numpy as np

        x = np.asarray(values, dtype=np.float64).ravel()
        w = None if weights is None else np.asarray(weights, dtype=np.float64).ravel()

        if w is not None and w.shape != x.shape:
            raise ValueError("weights needs one value per value")

        ok = np.isfinite(x)
        nonfinite = float((~ok).sum() if w is None else w[~ok].sum())
        x = x[ok]
        w = None if w is None else w[ok]
        stats: dict[str, float | None] = {}

        if x.size:
            mean = float(np.average(x, weights=w)) if w is None or w.sum() else None
            var = float(np.average((x - mean) ** 2, weights=w)) if mean is not None else None
            stats = {
                "min": float(x.min()),
                "max": float(x.max()),
                "mean": mean,
                "std": None if var is None else math.sqrt(var),
            }

        edges = _bin_edges(bins, range, stats)

        counts, _ = np.histogram(x, bins=np.asarray(edges), weights=w)
        inside = (x >= edges[0]) & (x <= edges[-1])
        outside = float((~inside).sum() if w is None else w[~inside].sum())
        return histogram_json(
            edges, counts.tolist(), stats=stats, outside=outside, nonfinite=nonfinite
        )

    xs = [float(v) for v in _values(values)]
    ws = [1.0] * len(xs) if weights is None else [float(v) for v in _values(weights)]

    if len(ws) != len(xs):
        raise ValueError("weights needs one value per value")

    pairs = [(v, wt) for v, wt in zip(xs, ws, strict=True) if math.isfinite(v)]
    nonfinite = sum(wt for v, wt in zip(xs, ws, strict=True) if not math.isfinite(v))
    stats = {}

    if pairs:
        total = sum(wt for _, wt in pairs)
        mean = sum(v * wt for v, wt in pairs) / total if total else None
        var = sum(wt * (v - mean) ** 2 for v, wt in pairs) / total if mean is not None else None
        stats = {
            "min": min(v for v, _ in pairs),
            "max": max(v for v, _ in pairs),
            "mean": mean,
            "std": None if var is None else math.sqrt(var),
        }

    edges = _bin_edges(bins, range, stats)

    counts = [0.0] * (len(edges) - 1)
    outside = 0.0

    for v, wt in pairs:
        if v < edges[0] or v > edges[-1]:
            outside += wt
            continue

        # the last bin includes its right edge, as in NumPy
        i = min(bisect.bisect_right(edges, v) - 1, len(counts) - 1)
        counts[i] += wt

    return histogram_json(edges, counts, stats=stats, outside=outside, nonfinite=nonfinite)


def histogram_from_buckets(
    lefts: list[float],
    rights: list[float],
    counts: list[float],
    stats: dict[str, float | None] | None = None,
    bins: int = 50,
) -> tuple[bytes, str, dict[str, Any]]:
    """Re-bin a histogram with arbitrary buckets onto evenly spaced bins.

    Used for TensorBoard histograms, whose buckets are exponentially spaced or
    whose bucket edges differ per step. Each bucket's count is spread evenly
    over its width; the new bins span the first left edge to the last right
    edge that hold any count, clipped to `stats` min and max when given.

    Args:
        lefts: Left edge of each bucket.
        rights: Right edge of each bucket.
        counts: Count per bucket.
        stats: Optional `min`, `max`, `mean` and `std`.
        bins: Number of bins to re-bin onto.

    Returns:
        The JSON bytes, the MIME type and metadata (see `histogram_json`).
    """

    stats = dict(stats or {})
    used = [(a, b, c) for a, b, c in zip(lefts, rights, counts, strict=True) if c > 0]

    if not used:
        return histogram_json(_edges(0.0, 0.0, bins), [0.0] * bins, stats=stats)

    smin, smax = stats.get("min"), stats.get("max")
    lo = max(min(a for a, _, _ in used), -math.inf if smin is None else smin)
    hi = min(max(b for _, b, _ in used), math.inf if smax is None else smax)

    if not (math.isfinite(lo) and math.isfinite(hi)) or hi < lo:
        lo, hi = min(a for a, _, _ in used), max(b for _, b, _ in used)

    edges = _edges(lo, hi, bins)
    out = [0.0] * bins
    width = edges[1] - edges[0]

    for a, b, c in used:
        a, b = max(a, edges[0]), min(b, edges[-1])

        if b <= a:  # a point bucket, or one clipped to a point
            out[min(max(int((a - edges[0]) / width), 0), bins - 1)] += c
            continue

        for i in range(
            max(int((a - edges[0]) / width), 0), min(int((b - edges[0]) / width) + 1, bins)
        ):
            overlap = min(b, edges[i + 1]) - max(a, edges[i])

            if overlap > 0:
                out[i] += c * overlap / (b - a)

    return histogram_json(edges, out, stats=stats)


#: MIME type of tables in the media pack (see `table_bytes`)
TABLE_MIME = "application/x-nuboard-table+json"


def cell_value(value: Any) -> Any:
    """Return a table cell as a JSON value: a number, bool, string or None.

    NumPy and torch scalars become numbers, non-finite numbers become None and
    anything else becomes its `str`.
    """

    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()  # NumPy or torch scalar
        except (TypeError, ValueError):
            pass

    if value is None or isinstance(value, (bool, str)):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None

    return str(value)


def table_bytes(
    columns: list[str], kinds: dict[str, str], rows: list[list[Any]], row_id: str
) -> tuple[bytes, str, dict[str, Any]]:
    """Encode a table as the stored JSON.

    Column types are `number`, `bool` or `text` from the values, or the kind of
    the media cells (`audio`, `image`) given in `kinds`.

    Args:
        columns: Column names, in order.
        kinds: Media kind of the columns that hold media cells.
        rows: One list of cell values per row, in column order; media cells are
            `{"$cell": <media key>}`.
        row_id: The column whose values match rows across steps.

    Returns:
        The JSON bytes, the MIME type and the `rows` and `columns` metadata.
    """

    def kind(i: int, name: str) -> str:
        if name in kinds:
            return kinds[name]

        values = [r[i] for r in rows if r[i] is not None]

        if values and all(isinstance(v, bool) for v in values):
            return "bool"

        if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return "number"

        return "text"

    data = {
        "columns": [{"name": c, "type": kind(i, c)} for i, c in enumerate(columns)],
        "id": row_id,
        "rows": rows,
    }
    meta = {"rows": len(rows), "columns": len(columns)}
    return json.dumps(data, separators=(",", ":")).encode("utf-8"), TABLE_MIME, meta
