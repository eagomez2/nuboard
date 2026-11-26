"""The integrations with the real frameworks, skipped unless they are installed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import nuboard as nb


def _meta(path) -> dict:
    return json.loads((Path(path) / "run.json").read_text("utf-8"))


def test_lightning_fit_then_test(tmp_path):
    torch = pytest.importorskip("torch")
    L = pytest.importorskip("lightning")
    from lightning.pytorch.callbacks import ModelCheckpoint

    from nuboard.integrations.lightning import NuBoardLogger

    class Model(L.LightningModule):
        def __init__(self, lr: float = 0.1):
            super().__init__()
            self.save_hyperparameters()
            self.layer = torch.nn.Linear(4, 1)

        def _loss(self, batch):
            x, y = batch
            return torch.nn.functional.mse_loss(self.layer(x), y)

        def training_step(self, batch, i):
            loss = self._loss(batch)
            self.log("train_loss", loss)
            return loss

        def validation_step(self, batch, i):
            self.log("val_loss", self._loss(batch))

        def test_step(self, batch, i):
            self.log("test_loss", self._loss(batch))
            self.logger.experiment.add_text("note", "from test_step", step=self.global_step)

        def configure_optimizers(self):
            return torch.optim.SGD(self.parameters(), lr=self.hparams.lr)

    data = torch.utils.data.TensorDataset(torch.randn(64, 4), torch.randn(64, 1))
    loader = torch.utils.data.DataLoader(data, batch_size=8)
    logger = NuBoardLogger("pl-real", run_name="tiny", log_model=True, capture_env=False)
    trainer = L.Trainer(
        max_epochs=2,
        logger=logger,
        callbacks=[ModelCheckpoint(monitor="val_loss")],
        default_root_dir=tmp_path / "pl",
        log_every_n_steps=1,
        enable_progress_bar=False,
        enable_model_summary=False,
        accelerator="cpu",
    )
    trainer.fit(Model(), loader, loader)
    trainer.test(ckpt_path="best", dataloaders=loader)

    run = logger._slot.current
    meta = _meta(run.path)
    assert meta["status"] == "finished"
    assert meta["name"] == "tiny"
    assert meta["config"]["lr"] == 0.1
    assert {"train_loss", "val_loss", "test_loss", "epoch"} <= set(meta["summary"])
    assert meta["summary"]["train_loss"]["count"] == 16
    assert len(meta["sessions"]) == 2  # fit, then test as a new session
    art = nb.get_artifact("pl-real/model:latest")
    assert art.manifest["metadata"]["monitor"] == "val_loss"


def test_hf_trainer_train_then_evaluate(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("accelerate")

    from nuboard.integrations.huggingface import NuBoardCallback

    class Tiny(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.layer = torch.nn.Linear(4, 1)

        def forward(self, x, labels=None):
            out = self.layer(x)
            loss = torch.nn.functional.mse_loss(out, labels)
            return {"loss": loss, "logits": out}

    rows = [{"x": torch.randn(4), "labels": torch.randn(1)} for _ in range(32)]
    args = transformers.TrainingArguments(
        str(tmp_path / "out"),
        report_to="none",
        logging_steps=2,
        num_train_epochs=1,
        per_device_train_batch_size=4,
        eval_strategy="epoch",
        save_strategy="no",
        use_cpu=True,
        disable_tqdm=True,
    )
    cb = NuBoardCallback("hf-real", capture_env=False)
    trainer = transformers.Trainer(
        model=Tiny(), args=args, train_dataset=rows, eval_dataset=rows, callbacks=[cb]
    )
    trainer.train()
    first = _meta(cb.run.path)
    assert first["status"] == "finished"
    assert first["config"]["per_device_train_batch_size"] == 4
    assert first["summary"]["train/loss"]["count"] == 4
    assert "eval/loss" in first["summary"]

    trainer.evaluate()
    cb.finish()
    meta = _meta(cb.run.path)
    assert len(meta["sessions"]) == 2
    assert meta["summary"]["eval/loss"]["step"] == 8  # same step: the later session wins
