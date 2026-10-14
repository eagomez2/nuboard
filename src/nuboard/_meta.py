"""Single source of truth for the project name and on-disk format version.

The product name lives in three places only: `pyproject.toml`, this package's
directory name, and `frontend/src/lib/brand.ts`. Everything else derives it
from `NAME` so a rename is a mechanical change.
"""

from __future__ import annotations

NAME: str = __name__.split(".")[0]
"""The package / command name (`import NAME`, `NAME up`)."""

ENV_PREFIX: str = NAME.upper()
"""Prefix for environment variables, e.g. `NUBOARD_DIR`."""

FORMAT_VERSION: int = 1
"""Version of the run folder format, written into every `run.json`."""

DEFAULT_ROOT: str = "experiments"
"""Folder (relative to the working directory) used when no root is given."""
