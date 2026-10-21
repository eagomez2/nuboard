"""Figures made by NuBoard itself, logged with `Run.add_figure` like a plotting library's.

Example:
    >>> import nuboard as nb
    >>> run.add_figure("eval/vad", nb.WaveformFigure(wav, 16000, {"vad": probs}), step=epoch)
"""

from __future__ import annotations

from dataclasses import dataclass
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
        caption: Optional caption shown with the figure.

    Example:
        >>> run.add_figure("eval/vad", nb.WaveformFigure(wav, 16000, {"vad": probs}, range=(0, 1)))
    """

    audio: Any
    sample_rate: int
    signals: Any
    range: tuple[float, float] | None = None
    caption: str | None = None
