"""The Lightning logger and the Hugging Face callback, against stand-ins of both frameworks.

The stand-ins have only what the integrations use, so these tests need neither
framework; `test_integrations_real.py` runs the real ones when installed.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from argparse import Namespace
from pathlib import Path

import pytest

import nuboard as nb


def _module(monkeypatch, name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


@pytest.fixture
def lightning(monkeypatch):
    """`nuboard.integrations.lightning` on a stand-in `lightning` package."""

    def rank_zero_only(fn):
        def wrapped(*a, **k):
            return fn(*a, **k) if rank_zero_only.rank == 0 else None

        return wrapped

    rank_zero_only.rank = 0

    class DummyExperiment:
        pass

    def rank_zero_experiment(fn):
        def experiment(self):
            return fn(self) if rank_zero_only.rank == 0 else DummyExperiment()

        return experiment

    class Logger:
        def __init__(self):
            pass

    for name in ("lightning", "lightning.pytorch", "lightning.pytorch.loggers"):
        _module(monkeypatch, name)

    _module(monkeypatch, "lightning.pytorch.utilities")
    _module(
        monkeypatch,
        "lightning.pytorch.loggers.logger",
        Logger=Logger,
        rank_zero_experiment=rank_zero_experiment,
    )
    _module(monkeypatch, "lightning.pytorch.utilities.rank_zero", rank_zero_only=rank_zero_only)
    monkeypatch.delitem(sys.modules, "nuboard.integrations.lightning", raising=False)
    mod = importlib.import_module("nuboard.integrations.lightning")
    mod.rank_zero_only_stub = rank_zero_only
    yield mod
    sys.modules.pop("nuboard.integrations.lightning", None)


def _meta(run) -> dict:
    return json.loads((Path(run.path) / "run.json").read_text("utf-8"))


def _losses(run_path: Path, key: str) -> list[tuple[int, float]]:
    table = nb.load(str(run_path.parent.parent)).run(run_path.name).scalars(key)
    return list(zip(table["step"].to_pylist(), table["value"].to_pylist()))


def test_import_nuboard_imports_no_framework():
    code = (
        "import sys, nuboard, nuboard.integrations;"
        "bad = [m for m in ('lightning', 'pytorch_lightning', 'transformers', 'torch', 'IPython')"
        " if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)"
    )
    import subprocess

    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_lightning_without_lightning_says_what_to_install(monkeypatch):
    for name in ("lightning", "lightning.pytorch.loggers.logger", "pytorch_lightning"):
        monkeypatch.setitem(sys.modules, name, None)  # blocks the import

    monkeypatch.delitem(sys.modules, "nuboard.integrations.lightning", raising=False)

    with pytest.raises(ImportError, match="pip install lightning"):
        importlib.import_module("nuboard.integrations.lightning")


def test_lightning_logs_metrics_and_hyperparameters(lightning):
    logger = lightning.NuBoardLogger(
        "pl", run_name="baseline", config={"seed": 1}, capture_env=False
    )
    assert logger.name == "pl"
    assert logger.save_dir is None
    # Lightning asks for the version (to place checkpoints) before the hyperparameters
    version = logger.version
    run = logger.experiment
    assert version == run.id
    assert logger.log_dir == str(run.path)

    logger.log_hyperparams(Namespace(lr=0.01, optim=Namespace(name="adam")))

    for step in range(5):
        logger.log_metrics({"train_loss": 1.0 / (step + 1), "epoch": 0, "note": "x"}, step=step)

    logger.save()
    logger.finalize("success")

    meta = _meta(run)
    assert meta["status"] == "finished"
    assert meta["name"] == "baseline"
    assert meta["config"] == {"seed": 1, "lr": 0.01, "optim": {"name": "adam"}}
    assert [v for _, v in _losses(run.path, "train_loss")] == pytest.approx(
        [1, 1 / 2, 1 / 3, 1 / 4, 1 / 5]
    )


def test_lightning_hyperparameters_before_the_run_go_into_init(lightning):
    logger = lightning.NuBoardLogger("pl", capture_env=False)
    logger.log_hyperparams({"lr": 0.1})
    logger.log_metrics({"loss": 1.0}, step=0)
    logger.finalize("success")
    assert _meta(logger._slot.current)["config"] == {"lr": 0.1}


def test_lightning_test_after_fit_resumes_the_same_run(lightning):
    logger = lightning.NuBoardLogger("pl", capture_env=False)
    logger.log_metrics({"loss": 1.0}, step=0)
    logger.finalize("success")
    first = logger.version
    assert logger.version == first  # asking for the version does not resume the run
    logger.log_metrics({"test_acc": 0.9}, step=10)
    logger.finalize("success")

    run = logger._slot.current
    assert run.id == first
    assert _meta(run)["status"] == "finished"
    assert len(_meta(run)["sessions"]) == 2
    assert _losses(run.path, "test_acc") == [(10, pytest.approx(0.9))]


def test_lightning_failed_fit_marks_the_run_crashed(lightning):
    logger = lightning.NuBoardLogger("pl", capture_env=False)
    logger.log_metrics({"loss": 1.0}, step=0)
    logger.finalize("failed")
    assert _meta(logger._slot.current)["status"] == "crashed"


def test_lightning_other_ranks_write_nothing(lightning, tmp_path):
    lightning.rank_zero_only_stub.rank = 1
    logger = lightning.NuBoardLogger("pl", capture_env=False)
    assert logger.version == ""
    assert type(logger.experiment).__name__ == "DummyExperiment"
    logger.log_metrics({"loss": 1.0}, step=0)
    logger.log_hyperparams({"lr": 1})
    logger.finalize("success")
    assert logger._slot.current is None
    assert not (tmp_path / "exp").exists()


def test_lightning_logs_to_a_given_run_without_finishing_it(lightning):
    run = nb.init("mine", capture_env=False)
    logger = lightning.NuBoardLogger(run=run)
    assert logger.name == "mine"
    logger.log_hyperparams({"lr": 0.5})
    logger.log_metrics({"loss": 2.0}, step=3)
    logger.finalize("success")
    assert not run.finished
    assert run.config == {"lr": 0.5}
    run.finish()


def test_lightning_log_model_adds_the_best_checkpoint(lightning, tmp_path):
    ckpt = tmp_path / "ckpt" / "epoch=1.ckpt"
    ckpt.parent.mkdir()
    ckpt.write_bytes(b"weights")
    callback = types.SimpleNamespace(
        best_model_path=str(ckpt), best_model_score=0.25, monitor="val_loss"
    )
    logger = lightning.NuBoardLogger("pl", log_model=True, capture_env=False)
    logger.log_metrics({"val_loss": 0.25}, step=1)
    logger.after_save_checkpoint(callback)
    logger.finalize("success")

    art = nb.get_artifact("pl/model:latest")
    assert art.manifest["type"] == "checkpoint"
    assert art.manifest["metadata"] == {
        "file": "epoch=1.ckpt",
        "monitor": "val_loss",
        "score": 0.25,
    }


# -- Hugging Face -------------------------------------------------------------
@pytest.fixture
def hf(monkeypatch):
    """`nuboard.integrations.huggingface` without `transformers` installed."""
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.delitem(sys.modules, "nuboard.integrations.huggingface", raising=False)
    yield importlib.import_module("nuboard.integrations.huggingface")
    sys.modules.pop("nuboard.integrations.huggingface", None)


class _Args:
    output_dir = "out"
    run_name = "out"
    metric_for_best_model = None

    def __init__(self, **extra):
        self.__dict__.update(extra)

    def to_dict(self):
        return {"learning_rate": 5e-5, "per_device_train_batch_size": 8, "hub_token": "<HUB_TOKEN>"}


def _state(step=0, **extra):
    return types.SimpleNamespace(
        **{"is_world_process_zero": True, "global_step": step, "trial_params": None, **extra}
    )


def test_hf_scalar_names(hf):
    assert hf.scalar_name("loss") == "train/loss"
    assert hf.scalar_name("eval_loss") == "eval/loss"
    assert hf.scalar_name("test_accuracy") == "test/accuracy"
    assert hf.scalar_name("custom/thing") == "custom/thing"


def test_hf_logs_training_and_evaluation(hf):
    cb = hf.NuBoardCallback("glue", capture_env=False, config={"seed": 3})
    args = _Args()
    model = types.SimpleNamespace(config=types.SimpleNamespace(to_dict=lambda: {"hidden": 32}))
    cb.on_init_end(args, _state(), None)  # events it does not use are ignored
    cb.on_train_begin(args, _state(), None, model=model)
    run = cb.run

    for step in (10, 20):
        cb.on_log(args, _state(step), None, logs={"loss": 1 / step, "learning_rate": 1e-5})

    cb.on_log(args, _state(20), None, logs={"eval_loss": 0.4, "eval_runtime": 1.5, "x": "skip"})
    cb.on_some_future_event(args, _state(), None)
    cb.on_train_end(args, _state(20), None)

    meta = _meta(run)
    assert meta["status"] == "finished"
    assert meta["name"] != "out"  # run_name defaults to output_dir, which is not a name
    assert meta["config"] == {
        "learning_rate": 5e-5,
        "per_device_train_batch_size": 8,
        "hub_token": "<HUB_TOKEN>",
        "model": {"hidden": 32},
        "seed": 3,
    }
    assert _losses(run.path, "train/loss") == [(10, 0.1), (20, 0.05)]
    assert _losses(run.path, "eval/loss") == [(20, 0.4)]

    # evaluate() after train() resumes the same run
    cb.on_log(args, _state(20), None, logs={"eval_accuracy": 0.8})
    assert cb.run.id == run.id
    cb.finish()
    assert len(_meta(cb.run)["sessions"]) == 2


def test_hf_each_trial_of_a_search_is_its_own_run(hf):
    cb = hf.NuBoardCallback("search", capture_env=False)
    ids = []

    for lr in (1e-4, 1e-3):
        state = _state(trial_params={"learning_rate": lr})
        cb.on_train_begin(_Args(run_name="trial"), state, None)
        cb.on_log(_Args(), _state(1), None, logs={"loss": lr})
        cb.on_train_end(_Args(), state, None)
        ids.append(cb.run.id)
        assert _meta(cb.run)["config"]["trial"] == {"learning_rate": lr}
        assert _meta(cb.run)["name"] == "trial"

    assert ids[0] != ids[1]


def test_hf_other_processes_write_nothing(hf, tmp_path):
    cb = hf.NuBoardCallback("glue", capture_env=False)
    state = types.SimpleNamespace(is_world_process_zero=False, global_step=1, trial_params=None)
    cb.on_train_begin(_Args(), state, None)
    cb.on_log(_Args(), state, None, logs={"loss": 1.0})
    cb.on_train_end(_Args(), state, None)
    assert cb.run is None
    assert not (tmp_path / "exp").exists()


def test_hf_log_model_adds_the_last_checkpoint(hf, tmp_path):
    out = tmp_path / "out"

    for step in (5, 40, 10):
        (out / f"checkpoint-{step}").mkdir(parents=True)
        (out / f"checkpoint-{step}" / "model.safetensors").write_bytes(b"w")

    cb = hf.NuBoardCallback("glue", log_model=True, capture_env=False)
    args = _Args(output_dir=str(out))
    cb.on_train_begin(args, _state(), None)
    cb.on_train_end(args, _state(40, best_model_checkpoint=None, best_metric=None), None)
    art = nb.get_artifact("glue/model:latest")
    assert art.manifest["metadata"] == {"folder": "checkpoint-40"}
    assert art.manifest["type"] == "checkpoint"
