"""Waveform figure bundles: a logged `nb.WaveformFigure` as files other tools open.

A waveform figure is stored as one media item: its WAV, then each signal as
little-endian float32 (see `waveform_bytes` in `_media.py`). A bundle is a zip
of the same data in open formats:

    audio.wav               the audio, as logged (16-bit PCM)
    signals/<name>.npy      one float32 array per signal, one value per audio sample
    metadata.json           sample rate, signal names and files, range, regions, ...

The viewer builds the same bundle in the browser (`waveformBundle` in
`frontend/src/lib/waveform.ts`). Writing needs the standard library only;
reading back (`read_bundle`) needs NumPy.
"""

from __future__ import annotations

import io
import json
import re
import struct
import wave
import zipfile
from importlib import metadata as _metadata
from pathlib import Path
from typing import Any

from ._meta import NAME

#: `format` of a bundle's metadata.json
BUNDLE_FORMAT = "nuboard-waveform"
#: `format_version` of a bundle's metadata.json
BUNDLE_VERSION = 1

_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def signal_files(names: list[str]) -> list[str]:
    """Return the bundle path of each signal: `signals/<name>.npy`, safe and unique on every OS.

    Characters that are not allowed in file names on some OS become `_`; names
    that would then collide, ignoring case, get `-2`, `-3`, ... appended.

    Args:
        names: The signal names, in order.

    Returns:
        One path per name.
    """
    out: list[str] = []
    taken: set[str] = set()

    for name in names:
        stem = _UNSAFE.sub("_", name).strip(" .") or "signal"
        candidate, n = stem, 1

        while candidate.lower() in taken:
            n += 1
            candidate = f"{stem}-{n}"

        taken.add(candidate.lower())
        out.append(f"signals/{candidate}.npy")

    return out


def npy_bytes(raw: bytes, count: int) -> bytes:
    """Wrap `count` little-endian float32 values as a `.npy` file (format 1.0, shape `(count,)`)."""
    header = f"{{'descr': '<f4', 'fortran_order': False, 'shape': ({count},), }}"
    pad = 64 - (10 + len(header) + 1) % 64
    header += " " * (pad % 64) + "\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin-1") + raw


def _version() -> str:
    """Return `<name> <version>` of the installed package."""

    try:
        return f"{NAME} {_metadata.version(NAME)}"
    except _metadata.PackageNotFoundError:  # pragma: no cover - running from a source tree
        return NAME


def bundle_metadata(
    item: dict[str, Any], *, run: dict[str, Any], key: str, step: int
) -> dict[str, Any]:
    """Return a bundle's metadata.json for a waveform media item.

    Args:
        item: The item's media metadata (`sample_rate`, `channels`, `duration`,
            `samples`, `signals`, `range`, `caption`, `regions`, and `notes`
            when the viewer added any).
        run: `id`, `name` and `project` of the run that logged it.
        key: The media key.
        step: The step.

    Returns:
        The metadata, as written to the bundle.
    """
    names = [str(n) for n in item.get("signals") or []]
    samples = int(item.get("samples") or 0)
    return {
        "format": BUNDLE_FORMAT,
        "format_version": BUNDLE_VERSION,
        "run": {"id": run.get("id"), "name": run.get("name"), "project": run.get("project")},
        "key": key,
        "step": step,
        "caption": item.get("caption"),
        "audio": {
            "file": "audio.wav",
            "sample_rate": item.get("sample_rate"),
            "channels": item.get("channels"),
            "samples": samples,
            "duration": item.get("duration"),
        },
        "signals": [
            {"name": name, "file": file, "dtype": "float32", "samples": samples}
            for name, file in zip(names, signal_files(names), strict=True)
        ],
        "range": list(item.get("range") or [-1.0, 1.0]),
        "regions": item.get("regions") or None,
        "notes": item.get("notes") or [],
        "exported_with": _version(),
    }


def waveform_bundle(
    item: dict[str, Any], data: bytes, *, run: dict[str, Any], key: str, step: int
) -> bytes:
    """Return the zip bundle of a stored waveform figure.

    Args:
        item: The item's media metadata (see `bundle_metadata`), with `audio_bytes`.
        data: The stored bytes: the WAV, then each signal as float32.
        run: `id`, `name` and `project` of the run that logged it.
        key: The media key.
        step: The step.

    Returns:
        The zip file's bytes.
    """
    meta = bundle_metadata(item, run=run, key=key, step=step)
    cut = int(item.get("audio_bytes") or 0)
    size = meta["audio"]["samples"] * 4
    buf = io.BytesIO()

    # stored, not deflated: PCM and float32 hardly compress, and stored members can be memory-mapped
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("audio.wav", data[:cut])

        for k, sig in enumerate(meta["signals"]):
            raw = data[cut + k * size : cut + (k + 1) * size]
            zf.writestr(sig["file"], npy_bytes(raw, len(raw) // 4))

        zf.writestr("metadata.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    return buf.getvalue()


def read_wav(data: bytes) -> tuple[Any, int]:
    """Decode 16-bit PCM WAV bytes into int16 samples (NumPy).

    Returns:
        `(samples, sample_rate)`: a `(samples,)` array for mono, else `(channels, samples)`.
    """
    import numpy as np

    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM audio, not {8 * w.getsampwidth()}-bit")

        channels, rate = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.int16)

    audio = pcm if channels == 1 else pcm.reshape(-1, channels).T.copy()
    return audio, rate


def read_stored(item: dict[str, Any], data: bytes) -> tuple[Any, int, dict[str, Any]]:
    """Split a stored waveform figure into its audio and signals (NumPy).

    Args:
        item: The item's media metadata, with `audio_bytes`, `samples` and `signals`.
        data: The stored bytes.

    Returns:
        `(audio, sample_rate, signals)`: int16 audio as `read_wav` returns it
        and float32 signals by name.
    """
    import numpy as np

    cut = int(item["audio_bytes"])
    samples = int(item["samples"])
    audio, rate = read_wav(data[:cut])
    signals = {
        str(name): np.frombuffer(data, "<f4", samples, cut + k * samples * 4).astype(np.float32)
        for k, name in enumerate(item.get("signals") or [])
    }
    return audio, rate, signals


def read_bundle(path: str | Path | bytes) -> tuple[Any, int, dict[str, Any], dict[str, Any]]:
    """Read a waveform bundle (NumPy).

    Args:
        path: The zip file, or its bytes.

    Returns:
        `(audio, sample_rate, signals, metadata)`: int16 audio (`(samples,)`
        for mono, else `(channels, samples)`), float32 signals by name and the
        parsed metadata.json.

    Raises:
        ValueError: If the zip is not a waveform bundle, or of a newer format version.
    """
    import numpy as np

    source = io.BytesIO(path) if isinstance(path, (bytes, bytearray)) else path

    with zipfile.ZipFile(source) as zf:
        meta = json.loads(zf.read("metadata.json"))

        if meta.get("format") != BUNDLE_FORMAT:
            raise ValueError(
                "not a waveform bundle: metadata.json has no 'nuboard-waveform' format"
            )

        if int(meta.get("format_version", 0)) > BUNDLE_VERSION:
            raise ValueError(
                f"bundle format_version {meta['format_version']} is newer than this version reads"
            )

        audio, rate = read_wav(zf.read(meta["audio"]["file"]))
        signals = {
            s["name"]: np.load(io.BytesIO(zf.read(s["file"])), allow_pickle=False).astype(
                np.float32
            )
            for s in meta["signals"]
        }

    return audio, rate, signals, meta
