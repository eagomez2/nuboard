"""A PyTorch Lightning logger that writes NuBoard runs.

```python
import lightning as L
from nuboard.integrations.lightning import NuBoardLogger

trainer = L.Trainer(logger=NuBoardLogger("mnist", run_name="baseline"))
trainer.fit(model, datamodule)
```

Works with both `lightning` and the older `pytorch_lightning` package; this
module imports whichever is installed, and nothing else.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

try:
    from lightning.pytorch.loggers.logger import (  # type: ignore[import-not-found]
        Logger,
        rank_zero_experiment,
    )
    from lightning.pytorch.utilities.rank_zero import (  # type: ignore[import-not-found]
        rank_zero_only,
    )
except ImportError:  # the older package name
    try:
        from pytorch_lightning.loggers.logger import (  # type: ignore[import-not-found]
            Logger,
            rank_zero_experiment,
        )
        from pytorch_lightning.utilities.rank_zero import (  # type: ignore[import-not-found]
            rank_zero_only,
        )
    except ImportError as exc:
        raise ImportError(
            "nuboard.integrations.lightning needs PyTorch Lightning "
            "(pip install lightning, or pytorch-lightning)"
        ) from exc

from ..run import Run
from ._common import RunSlot, numbers, plain

# Lightning's final status of a fit, validate or test, as a run status
_STATUS = {"success": "finished", "finished": "finished", "failed": "crashed"}


class NuBoardLogger(Logger):  # type: ignore[misc]
    """Log a Lightning `Trainer` to a NuBoard run.

    Metrics from `self.log` become scalars at the trainer's global step, and
    the hyperparameters (`self.save_hyperparameters()`) are merged into the
    run's config. Only global rank 0 creates and writes the run, so every
    process can use the same logger.

    The run is created when Lightning first needs it and finished when a fit,
    validate or test ends. If the trainer is used again (a test after a fit),
    the same run is resumed as a new session. With `run=` the logger writes
    to that run and never finishes it.

    For images, figures, text and anything else, use the run itself:
    `self.logger.experiment.add_image(...)` inside a `LightningModule`.

    Args:
        project: Project name, as for `nb.init`.
        run_name: Display name of the run.
        config: Settings to record, merged with the hyperparameters.
        dir: Root folder of the projects (default `$NUBOARD_DIR` or `./experiments`).
        log_model: True records the best checkpoint (or the last, without a
            monitored metric) as a `"checkpoint"` artifact when the run ends.
        model_name: Artifact name for `log_model`.
        run: An existing run to log to instead of creating one.
        **init_kwargs: More arguments for `nb.init`, such as `tags`, `group`,
            `notes` or `run_id` and `resume`.
    """

    def __init__(
        self,
        project: str | os.PathLike[str] | None = None,
        *,
        run_name: str | None = None,
        config: Any = None,
        dir: str | os.PathLike[str] | None = None,
        log_model: bool = False,
        model_name: str = "model",
        run: Run | None = None,
        **init_kwargs: Any,
    ) -> None:
        super().__init__()
        kwargs = {"project": project, "run_name": run_name, "dir": dir, **init_kwargs}
        self._slot = RunSlot(run, {**kwargs, "config": config})
        self._project = run.project if run is not None else str(project or "default")
        self._log_model = log_model
        self._model_name = model_name
        self._checkpoint: Any = None

    # -- what Lightning asks of a logger --------------------------------------
    @property
    def name(self) -> str:
        """The project name."""
        return self._project

    @property
    def version(self) -> str:
        """The run id (created on first use, on rank 0)."""
        run = self._slot.current

        if run is None and rank_zero_only.rank == 0:
            run = self._slot.get()

        return run.id if run is not None else ""

    @property
    def save_dir(self) -> None:
        """None: checkpoints go under the trainer's `default_root_dir`, not into the run."""
        return None

    @property
    def log_dir(self) -> str | None:
        """The run's folder, on rank 0 once the run exists."""
        run = self._slot.current
        return str(run.path) if run is not None and run.id else None

    @property
    @rank_zero_experiment
    def experiment(self) -> Run:
        """The `nb.Run`, for logging media: `self.logger.experiment.add_image(...)`."""
        return self._slot.get()

    @rank_zero_only
    def log_hyperparams(self, params: Any, *args: Any, **kwargs: Any) -> None:
        """Merge hyperparameters into the run's config."""
        self._slot.configure(plain(params))

    @rank_zero_only
    def log_metrics(self, metrics: Mapping[str, Any], step: int | None = None) -> None:
        """Log metrics as scalars at `step`."""
        values = numbers(metrics)

        if values:
            self._slot.get().add_scalar(values, step=step)

    @rank_zero_only
    def after_save_checkpoint(self, checkpoint_callback: Any) -> None:
        """Remember the checkpoint callback, for `log_model`."""
        self._checkpoint = checkpoint_callback

    @rank_zero_only
    def save(self) -> None:
        """Flush what was logged so far to disk."""
        run = self._slot.current

        if run is not None and not run.finished:
            run.flush()

    @rank_zero_only
    def finalize(self, status: str) -> None:
        """Record the checkpoint (with `log_model`) and finish the run."""
        run = self._slot.current

        if run is None or run.finished:
            return

        if self._log_model and self._checkpoint is not None:
            self._add_checkpoint(run, self._checkpoint)
            self._checkpoint = None

        self._slot.finish(_STATUS.get(status, "finished"))

    def _add_checkpoint(self, run: Run, callback: Any) -> None:
        """Add the best (or last) checkpoint file as an artifact version."""
        path = getattr(callback, "best_model_path", "") or getattr(callback, "last_model_path", "")

        if not path or not os.path.exists(path):
            return

        score = getattr(callback, "best_model_score", None)
        metadata: dict[str, Any] = {"file": os.path.basename(path)}

        if getattr(callback, "monitor", None):
            metadata["monitor"] = callback.monitor

        if score is not None:
            metadata["score"] = float(score)

        run.add_artifact(self._model_name, path, type="checkpoint", metadata=metadata)
