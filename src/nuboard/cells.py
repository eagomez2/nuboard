"""Media cells for tables: audio and images inside a row of `Run.add_table`.

Example:
    >>> import nuboard as nb
    >>> run.add_table("eval/samples", [
    ...     {"file": "p232_001", "pesq": 2.9, "enhanced": nb.Audio(wav, sample_rate=16000)},
    ... ], step=epoch)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Audio:
    """An audio clip in a table cell, accepted in the same forms as `Run.add_audio`.

    Attributes:
        data: A file path, encoded bytes, or a `(samples,)` or `(channels, samples)`
            array or tensor.
        sample_rate: Sample rate in Hz; required for arrays.
        caption: Optional caption shown with the clip.
    """

    data: Any
    sample_rate: int | None = None
    caption: str | None = None


@dataclass
class Image:
    """An image in a table cell, accepted in the same forms as `Run.add_image`.

    Attributes:
        data: PNG/JPEG bytes, a file path, a PIL image, or an image array or tensor.
        caption: Optional caption shown with the image.
    """

    data: Any
    caption: str | None = None
