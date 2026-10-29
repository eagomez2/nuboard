"""Figures made by NuBoard itself, logged with `Run.add_figure` like a plotting library's.

Example:
    >>> import nuboard as nb
    >>> run.add_figure("eval/vad", nb.WaveformFigure(wav, 16000, {"vad": probs}), step=epoch)
"""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import Any


@dataclass
class WaveformFigure:
    """A waveform with signals drawn over it: a figure for `Run.add_figure`.

    The viewer plots the waveform with each signal over it, accurately at
    every zoom down to single samples, with their values under the pointer;
    a voice activity probability, for example. Each signal holds one value
    per audio sample.

    Attributes:
        audio: A `(samples,)` or `(channels, samples)` array or tensor, as
            `Run.add_audio` takes it.
        sample_rate: Sample rate in Hz.
        signals: An array or tensor of `samples` values, or a dict of them by name.
        range: The values at the bottom and top of the waveform. Defaults to
            the waveform's own axis, -1 to 1 (full scale), so a signal lines up
            with the samples: an envelope traces the waveform and a
            probability of 1 reaches full scale.
        regions: Optional labelled time regions logged with the figure, such as
            the target and predicted classes of a classifier, as a dict of
            tracks by name. A track is a list of `(start, end, label)` in
            seconds, or `(ids, names, frame)`: a class id per frame, the class
            names and the frame length in seconds. Each track is drawn in its
            own lane, each label in its own color; notes added in the viewer
            are kept apart from them.
        caption: Optional caption shown with the figure.

    Example:
        >>> run.add_figure("eval/vad", nb.WaveformFigure(wav, 16000, {"vad": probs}, range=(0, 1)))
    """

    audio: Any
    sample_rate: int
    signals: Any
    _: KW_ONLY
    range: tuple[float, float] | None = None
    regions: dict[str, Any] | None = None
    caption: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> WaveformFigure:
        """Rebuild a figure from a downloaded bundle (the waveform's **Data (.zip)**).

        Logging the result again with `Run.add_figure` stores an identical
        figure: the same 16-bit audio, signals, range, regions and caption.
        Needs NumPy.

        Args:
            path: The bundle's `.zip` file.

        Returns:
            The figure, with the audio as int16 samples, `(samples,)` for mono
            or `(channels, samples)`, and the signals as float32 by name.

        Raises:
            ValueError: If the file is not a waveform bundle.

        Example:
            >>> fig = nb.WaveformFigure.load("unet-l1-eval_vad-1200.zip")
            >>> run.add_figure("eval/vad", fig, step=0)
        """
        from ._waveform import read_bundle

        audio, rate, signals, meta = read_bundle(path)
        regions = meta.get("regions") or None
        tracks = (
            {name: [tuple(seg) for seg in segs] for name, segs in regions.items()}
            if regions
            else None
        )
        bounds = meta.get("range")
        return cls(
            audio,
            rate,
            signals,
            range=(float(bounds[0]), float(bounds[1])) if bounds else None,
            regions=tracks,
            caption=meta.get("caption"),
        )
