"""Single source of truth for the project name and on-disk format version.

The product name lives in three places only: `pyproject.toml`, this package's
directory name (with its display form `DISPLAY_NAME` below), and
`frontend/src/lib/brand.ts`. Everything else derives it from `NAME` so a rename
is a mechanical change.
"""

from __future__ import annotations

import datetime
import unicodedata

NAME: str = __name__.split(".")[0]
"""The package / command name (`import NAME`, `NAME up`)."""

DISPLAY_NAME: str = "NuBoard"
"""The name as shown to people, e.g. in `NAME version`."""

AUTHOR: str = "Esteban Gómez"
"""Copyright holder, as in `LICENSE`."""

COPYRIGHT_SINCE: int = 2026
"""First year of the copyright; later years extend it to a range."""

ENV_PREFIX: str = NAME.upper()
"""Prefix for environment variables, e.g. `NUBOARD_DIR`."""

FORMAT_VERSION: int = 1
"""Version of the run folder format, written into every `run.json`."""

DEFAULT_ROOT: str = "experiments"
"""Folder (relative to the working directory) used when no root is given."""


def copyright_line(version: str, year: int | None = None) -> str:
    """The line `NAME version` prints, e.g. `NuBoard 1.2.3 Copyright © 2026 … (MIT License)`.

    Args:
        version: The package version.
        year: The current year; defaults to today's, so the range grows on its own.

    Returns:
        The line, with the years as `2026` or a range such as `2026–2028`.
    """
    year = datetime.date.today().year if year is None else year
    years = str(COPYRIGHT_SINCE) if year <= COPYRIGHT_SINCE else f"{COPYRIGHT_SINCE}–{year}"
    return f"{DISPLAY_NAME} {version} Copyright © {years} {AUTHOR} (MIT License)"


def printable(text: str, encoding: str | None) -> str:
    """`text` as is if `encoding` can encode it, else an ASCII spelling.

    Windows consoles and redirected output can use code pages such as cp1252 or
    cp437 that lack `©`, `–` or accented letters, where `print` would raise.

    Args:
        text: The text to print.
        encoding: The stream's encoding (`sys.stdout.encoding`), or None.

    Returns:
        `text`, or it with `©` as `(c)`, `–` as `-` and accents dropped.
    """

    try:
        text.encode(encoding or "ascii")
        return text
    except (UnicodeEncodeError, LookupError):
        pass

    text = text.replace("©", "(c)").replace("–", "-")
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return plain.encode("ascii", "replace").decode("ascii")
