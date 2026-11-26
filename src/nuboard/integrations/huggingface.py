"""A Hugging Face `Trainer` callback that writes NuBoard runs.

```python
from transformers import Trainer, TrainingArguments
from nuboard.integrations.huggingface import NuBoardCallback

args = TrainingArguments("out", report_to="none", logging_steps=10)
trainer = Trainer(model, args, train_dataset=train, eval_dataset=val,
                  callbacks=[NuBoardCallback("glue-mrpc")])
trainer.train()
```

This module imports `transformers` only if it is installed, to subclass its
`TrainerCallback`; the callback works the same without it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from ..run import Run
from ._common import RunSlot, numbers, plain

try:
    from transformers import TrainerCallback as _Base  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - the callback only needs the method names
    _Base = object

# `logs` keys that start with these go to their own group, as in the Trainer's other loggers
_GROUPS = ("eval_", "test_")


def scalar_name(key: str) -> str:
    """Map a `Trainer` log key to a scalar name.

    `eval_loss` becomes `eval/loss`, `test_acc` becomes `test/acc` and `loss`
    becomes `train/loss`. A key with a `/` is kept as it is.
    """

    for prefix in _GROUPS:
        if key.startswith(prefix):
            return f"{prefix[:-1]}/{key[len(prefix) :]}"

    return key if "/" in key else f"train/{key}"


class NuBoardCallback(_Base):  # type: ignore[misc, valid-type]
    """Log a Hugging Face `Trainer` to a NuBoard run.

    Whatever the trainer logs (loss, learning rate, grad norm, evaluation
    metrics) becomes a scalar at the trainer's global step: `eval_*` keys under
    `eval/`, `test_*` under `test/` and the rest under `train/`. The
    `TrainingArguments` and the model's config (under `model`) are recorded as
    the run's config. Only the main process writes.

    The run starts with training and is finished when training ends. Metrics
    logged later, as by `trainer.evaluate()` after `trainer.train()`, resume
    the same run as a new session. In a hyperparameter search each trial is a
    run of its own, with the trial's parameters in its config. With `run=` the
    callback writes to that run and never finishes it.

    Pass `report_to="none"` (or a list without `"tensorboard"`) in
    `TrainingArguments` to stop the trainer adding its own loggers.

    Args:
        project: Project name, as for `nb.init`.
        run_name: Display name of the run. Defaults to `TrainingArguments.run_name`
            when it was set.
        config: More settings to record, on top of the arguments.
        dir: Root folder of the projects (default `$NUBOARD_DIR` or `./experiments`).
        log_model: True records the trainer's best checkpoint (or the last one
            saved) as a `"checkpoint"` artifact when training ends.
        model_name: Artifact name for `log_model`.
        run: An existing run to log to instead of creating one.
        **init_kwargs: More arguments for `nb.init`, such as `tags`, `group`
            or `notes`.
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
        self._kwargs = {"project": project, "run_name": run_name, "dir": dir, **init_kwargs}
        self._config = plain(config) if config is not None else {}
        self._slot = RunSlot(run, {**self._kwargs, "config": self._config})
        self._log_model = log_model
        self._model_name = model_name

    @property
    def run(self) -> Run | None:
        """The run being written, once training has started (None before)."""
        return self._slot.current

    # -- events -------------------------------------------------------------
    def on_train_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
        """Start the run with the arguments and the model's config."""

        if not getattr(state, "is_world_process_zero", True):
            return

        config: dict[str, Any] = {}
        to_dict = getattr(args, "to_dict", None)

        if callable(to_dict):
            config.update(plain(to_dict()))  # tokens are masked by `TrainingArguments.to_dict`

        model_config = getattr(kwargs.get("model"), "config", None)

        if model_config is not None and callable(getattr(model_config, "to_dict", None)):
            config["model"] = model_config.to_dict()

        trial = getattr(state, "trial_params", None)

        if trial:
            config["trial"] = plain(trial)

        config.update(self._config)
        name = self._kwargs.get("run_name")
        arg_name = getattr(args, "run_name", None)

        if name is None and arg_name and arg_name != getattr(args, "output_dir", None):
            name = arg_name

        run = self._slot.current

        if not self._slot.owned:  # a run of the caller's
            assert run is not None
            run.update_config(config)
            return

        if run is not None and not run.finished and not trial:
            run.update_config(config)  # metrics were logged before training began
            return

        self._slot.new()  # the first training, a new trial, or train() called again
        self._slot.init_kwargs = {**self._kwargs, "run_name": name, "config": config}
        self._slot.get()

    def on_log(
        self,
        args: Any,
        state: Any,
        control: Any,
        logs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log the trainer's metrics as scalars at the global step."""

        if not getattr(state, "is_world_process_zero", True) or not logs:
            return

        values = {scalar_name(k): v for k, v in numbers(logs).items()}

        if values:
            self._slot.get().add_scalar(values, step=int(getattr(state, "global_step", 0)))

    def on_train_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
        """Record the checkpoint (with `log_model`) and finish the run."""

        if not getattr(state, "is_world_process_zero", True):
            return

        run = self._slot.current

        if run is None or run.finished:
            return

        if self._log_model:
            path = getattr(state, "best_model_checkpoint", None) or _last_checkpoint(
                getattr(args, "output_dir", None)
            )

            if path and os.path.exists(path):
                metadata: dict[str, Any] = {"folder": os.path.basename(path)}

                if getattr(state, "best_metric", None) is not None:
                    metadata["score"] = float(state.best_metric)

                metric = getattr(args, "metric_for_best_model", None)

                if metric:
                    metadata["monitor"] = metric

                run.add_artifact(self._model_name, path, type="checkpoint", metadata=metadata)

        self._slot.finish()

    def finish(self) -> None:
        """Finish the run now, as after `trainer.evaluate()` in a notebook."""
        self._slot.finish()

    def __getattr__(self, name: str) -> Callable[..., None]:
        """Ignore the other events, including ones newer versions add."""

        if name.startswith("on_"):
            return _ignore

        raise AttributeError(name)


def _ignore(*args: Any, **kwargs: Any) -> None:
    """An event the callback does not use."""


def _last_checkpoint(output_dir: str | None) -> str | None:
    """The newest `checkpoint-<step>` folder in `output_dir`, or None."""

    if not output_dir or not os.path.isdir(output_dir):
        return None

    steps = []

    for name in os.listdir(output_dir):
        tail = name.removeprefix("checkpoint-")

        if tail != name and tail.isdigit() and os.path.isdir(os.path.join(output_dir, name)):
            steps.append(int(tail))

    return os.path.join(output_dir, f"checkpoint-{max(steps)}") if steps else None
