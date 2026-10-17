"""A local, folder-based experiment tracker for ML training.

Example:
    >>> import nuboard as nb
    >>> with nb.init("my-project", config={"lr": 1e-3}) as run:
    ...     run.add_scalar({"loss": 0.5}, step=0)
"""

from __future__ import annotations

from importlib import metadata as _metadata
from typing import TYPE_CHECKING

from ._meta import FORMAT_VERSION, NAME
from .artifacts import Artifact
from .cells import Audio, Image
from .run import Run, add_artifact, get_artifact, init

try:
    __version__ = _metadata.version(NAME)
except _metadata.PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

if TYPE_CHECKING:
    from .analysis import Project


def load(project: str, *, dir: str | None = None) -> Project:
    """Open a project (or any folder of runs) for analysis.

    Needs the `viewer` extra (`NAME[viewer]`), which provides PyArrow and NumPy.

    Args:
        project: A project name, resolved the same way as in `init`, or the path of an
            existing folder of runs (a project, or a tree of projects).
        dir: Root folder holding the projects. Defaults to `$NUBOARD_DIR` or
            `./experiments`. When given, `project` is always treated as a name.

    Returns:
        A `Project` covering every run found under the folder.

    Example:
        >>> import nuboard as nb
        >>> project = nb.load("my-project")
        >>> losses = project.scalars("loss", group_by="config.lr")
    """
    from .analysis import Project

    return Project.open(project, dir=dir)


__all__ = [
    "FORMAT_VERSION",
    "NAME",
    "Artifact",
    "Audio",
    "Image",
    "Run",
    "__version__",
    "add_artifact",
    "get_artifact",
    "init",
    "load",
]
