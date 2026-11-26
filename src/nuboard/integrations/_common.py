"""The run an integration logs to: created on first use, resumed after a finish."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping
from typing import Any

from ..run import Run


def plain(params: Any) -> dict[str, Any]:
    """Turn hyperparameters (a dict, `Namespace` or `AttributeDict`) into a plain dict.

    Nested namespaces and mappings become dicts. Other values are kept as they
    are: `run.json` stores what JSON can encode and the `repr` of the rest.
    """

    if isinstance(params, Namespace):
        params = vars(params)

    if not isinstance(params, Mapping):
        return {}

    out: dict[str, Any] = {}

    for k, v in params.items():
        out[str(k)] = plain(v) if isinstance(v, (Mapping, Namespace)) else v

    return out


def numbers(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the values `add_scalar` takes: numbers, bools and tensor or array scalars."""
    out: dict[str, Any] = {}

    for k, v in values.items():
        if isinstance(v, (bool, int, float)):
            out[k] = v
        elif getattr(v, "ndim", None) == 0 or (
            hasattr(v, "item") and getattr(v, "numel", lambda: 0)() == 1
        ):
            out[k] = v

    return out


class RunSlot:
    """Holds the run an integration logs to.

    With a run given, the integration only logs to it and never finishes it.
    Otherwise the run is created with `nb.init` on first use, finished by
    `finish`, and resumed (a new session of the same run) if something is
    logged after that, as when a test follows a fit.

    Args:
        run: A run to log to, or None to create one.
        init_kwargs: Arguments for `nb.init` when the run is created.
    """

    def __init__(self, run: Run | None, init_kwargs: dict[str, Any]) -> None:
        self._run = run
        self.owned = run is None
        self.init_kwargs = init_kwargs
        self.pending_config: dict[str, Any] = {}

    @property
    def current(self) -> Run | None:
        """The run, if it was created; None before."""
        return self._run

    def get(self) -> Run:
        """Return the run, creating it, or resuming it after `finish`."""

        if self._run is None:
            kwargs = dict(self.init_kwargs)
            config = {**plain(kwargs.pop("config", None) or {}), **self.pending_config}
            self.pending_config = {}
            self._run = Run(config=config or None, **kwargs)
        elif self.owned and self._run.finished and self._run.id:
            kwargs = {
                k: v
                for k, v in self.init_kwargs.items()
                if k in ("project", "dir", "flush_interval", "heartbeat_interval")
            }
            self._run = Run(run_id=self._run.id, resume="must", capture_env=False, **kwargs)

        return self._run

    def new(self) -> None:
        """Start the next `get` with a fresh run (a new trial of a search)."""

        if self.owned:
            self._run = None

    def configure(self, values: Mapping[str, Any]) -> None:
        """Add settings to the config: kept for `init` if the run does not exist yet."""

        if not values:
            return

        if self._run is None:
            self.pending_config.update(values)
        else:
            self._run.update_config(values)

    def finish(self, status: str = "finished") -> None:
        """Finish the run if this integration created it."""

        if self.owned and self._run is not None and not self._run.finished:
            self._run.finish(status=status, exit_code=0 if status == "finished" else 1)
