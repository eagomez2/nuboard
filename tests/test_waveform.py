"""Waveform figure bundles: the audio, one .npy per signal and metadata.json."""

from __future__ import annotations

import io
import json
import wave
import zipfile

import numpy as np
import pytest

import nuboard as nb
from nuboard._waveform import npy_bytes, signal_files, waveform_bundle
from nuboard.reader import RunReader


def _log(figure: nb.WaveformFigure, key: str = "eval/vad", step: int = 3):
    """Log `figure` in a new run and return the run, the stored item's metadata and bytes."""
    run = nb.init("w", run_name="base", capture_env=False)
    run.add_figure(key, figure, step=step)
    run.finish()
    reader = RunReader(run.path)
    [entry] = reader.media(key)
    return run, entry.meta, reader.read_media(entry)


def _bundle_bytes(run, meta, data, key="eval/vad", step=3) -> bytes:
    info = {"id": run.id, "name": "base", "project": "w"}
    return waveform_bundle(meta, data, run=info, key=key, step=step)


def _bundle(run, meta, data):
    return zipfile.ZipFile(io.BytesIO(_bundle_bytes(run, meta, data)))


def test_npy_bytes_load_with_numpy():
    values = np.array([0.5, np.nan, -2.0], dtype="<f4")

    for n in (0, 3, 10**7, 10**12):  # the header is 64-byte aligned whatever its length
        assert (npy_bytes(b"", n).index(b"\n") + 1) % 64 == 0

    out = np.load(io.BytesIO(npy_bytes(values.tobytes(), 3)))
    assert out.dtype == np.float32 and out.shape == (3,)
    assert np.array_equal(out, values, equal_nan=True)


def test_signal_files_are_safe_and_unique():
    files = signal_files(["vad", "a/b", "A:B", "VAD", "", "a?b"])
    assert files == [
        "signals/vad.npy",
        "signals/a_b.npy",
        "signals/A_B-2.npy",
        "signals/VAD-2.npy",
        "signals/signal.npy",
        "signals/a_b-3.npy",
    ]


def test_mono_bundle_round_trips():
    rate = 8000
    audio = np.linspace(-0.5, 0.5, 800)
    vad = np.linspace(0, 1, 800).astype(np.float32)
    vad[100:120] = np.nan  # a gap
    regions = {"target": [(0.01, 0.05, "speech")], "predicted": [(0.0, 0.04, "speech")]}
    figure = nb.WaveformFigure(
        audio,
        rate,
        {"speech_prob": vad, "gain": -vad},
        range=(0, 1),
        regions=regions,
        caption="VAD",
    )
    run, meta, data = _log(figure)
    zf = _bundle(run, meta, data)
    assert sorted(zf.namelist()) == [
        "audio.wav",
        "metadata.json",
        "signals/gain.npy",
        "signals/speech_prob.npy",
    ]

    # the audio is the logged WAV, byte for byte
    assert zf.read("audio.wav") == data[: meta["audio_bytes"]]

    with wave.open(io.BytesIO(zf.read("audio.wav"))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (rate, 1, 800)

    prob = np.load(io.BytesIO(zf.read("signals/speech_prob.npy")))
    assert prob.dtype == np.float32 and np.array_equal(prob, vad, equal_nan=True)
    assert np.array_equal(np.load(io.BytesIO(zf.read("signals/gain.npy"))), -vad, equal_nan=True)

    info = json.loads(zf.read("metadata.json"))
    assert info["format"] == "nuboard-waveform" and info["format_version"] == 1
    assert info["run"] == {"id": run.id, "name": "base", "project": "w"}
    assert (info["key"], info["step"], info["caption"]) == ("eval/vad", 3, "VAD")
    assert info["audio"] == {
        "file": "audio.wav",
        "sample_rate": rate,
        "channels": 1,
        "samples": 800,
        "duration": 0.1,
    }
    assert info["signals"][0] == {
        "name": "speech_prob",
        "file": "signals/speech_prob.npy",
        "dtype": "float32",
        "samples": 800,
    }
    assert info["range"] == [0.0, 1.0]
    assert info["regions"] == {
        "target": [[0.01, 0.05, "speech"]],
        "predicted": [[0.0, 0.04, "speech"]],
    }
    assert info["exported_with"].startswith("nuboard")


def test_stereo_bundle_and_relog_are_identical(tmp_path):
    rate = 16000
    t = np.arange(1600) / rate
    audio = np.stack([np.sin(2 * np.pi * 440 * t), 0.5 * np.cos(2 * np.pi * 220 * t)])
    env = np.abs(audio[0]).astype(np.float32)
    run, meta, data = _log(nb.WaveformFigure(audio, rate, env, caption=None))
    path = tmp_path / "bundle.zip"
    path.write_bytes(_bundle_bytes(run, meta, data))

    with wave.open(io.BytesIO(zipfile.ZipFile(path).read("audio.wav"))) as w:
        assert w.getnchannels() == 2

    figure = nb.WaveformFigure.load(path)
    assert figure.audio.shape == (2, 1600) and figure.audio.dtype == np.int16
    assert figure.sample_rate == rate and list(figure.signals) == ["signal"]
    assert figure.range == (-1.0, 1.0) and figure.regions is None and figure.caption is None

    # logged again, the figure is stored exactly as the first time
    _, meta2, data2 = _log(figure)
    assert data2 == data
    assert {k: meta2[k] for k in ("signals", "range", "regions", "samples", "channels")} == {
        k: meta[k] for k in ("signals", "range", "regions", "samples", "channels")
    }


def test_relog_keeps_regions_and_caption(tmp_path):
    audio = np.zeros(400)
    regions = {"t": ([0, 0, 1, 1], ["noise", "speech"], 0.0125)}
    run, meta, data = _log(
        nb.WaveformFigure(audio, 8000, audio, range=(0, 2), regions=regions, caption="c")
    )
    path = tmp_path / "b.zip"
    path.write_bytes(_bundle_bytes(run, meta, data))
    _, meta2, data2 = _log(nb.WaveformFigure.load(path))
    assert data2 == data
    assert (
        meta2["regions"]
        == meta["regions"]
        == {"t": [[0.0, 0.025, "noise"], [0.025, 0.05, "speech"]]}
    )
    assert meta2["range"] == [0.0, 2.0] and meta2["caption"] == "c"


def test_load_rejects_other_zips(tmp_path):
    path = tmp_path / "x.zip"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("metadata.json", "{}")

    with pytest.raises(ValueError, match="not a waveform bundle"):
        nb.WaveformFigure.load(path)


def test_run_handle_waveform():
    audio = np.linspace(-1, 1, 800)
    vad = np.linspace(0, 1, 800)
    run = nb.init("p", run_name="base", capture_env=False)
    run.add_figure("vad", nb.WaveformFigure(audio, 8000, {"vad": vad}), step=1)
    run.add_figure("vad", nb.WaveformFigure(audio, 8000, {"vad": vad * 0.5}), step=2)
    run.finish()

    handle = nb.load("p").run(run.id)
    pcm, rate, signals, meta = handle.waveform("vad")
    assert rate == 8000 and pcm.dtype == np.int16 and pcm.shape == (800,)
    assert pcm[0] == -32767 and pcm[-1] == 32767
    assert np.allclose(signals["vad"], vad * 0.5) and meta["step"] == 2
    assert meta["run"]["id"] == run.id and meta["run"]["project"] == "p"
    assert np.allclose(handle.waveform("vad", step=1)[2]["vad"], vad)

    with pytest.raises(KeyError):
        handle.waveform("vad", step=9)
