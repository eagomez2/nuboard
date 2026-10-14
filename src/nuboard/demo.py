"""Synthetic demo workspace: three projects, ~26 runs, media, artifacts and a live run."""

from __future__ import annotations

import math
import random
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import _fs
from .collection import save_collection
from .run import init

LLM_LRS = {3e-4: 2.43, 1e-3: 2.345, 3e-3: 2.505, 1e-4: 2.78}  # lr -> final loss
LLM_STEPS = 25_000
LLM_EVERY = 10


def _llm_config(lr: float, seed: int) -> dict[str, Any]:
    return {
        "model": {"size": "1.3B", "layers": 24, "d_model": 2048},
        "optim": {
            "name": "adamw",
            "lr": lr,
            "weight_decay": 0.01,
            "warmup_steps": 1000,
            "betas": [0.9, 0.95],
        },
        "data": {"dataset": "fineweb-edu:v2", "batch_size": 512, "seq_len": 2048},
        "train": {"steps": LLM_STEPS, "precision": "bf16", "grad_clip": 1.0},
        "seed": seed,
    }


def _lr_at(step: int, lr: float) -> float:
    if step < 1000:
        return lr * step / 1000
    return lr * 0.5 * (1 + math.cos(math.pi * (step - 1000) / (LLM_STEPS - 1000)))


def llm_point(
    step: int,
    lr: float,
    seed: int,
    rng: random.Random,
    *,
    diverge_at: int | None = None,
    dip_at: int | None = None,
    spike_at: int | None = None,
) -> dict[str, float]:
    final = LLM_LRS.get(lr, 2.5) + 0.004 * (seed - 2)
    tau = 2600 * (1e-3 / lr) ** 0.45
    loss = (
        final
        + (5.3 - final) * math.exp(-step / tau)
        + rng.gauss(0, 0.025 + 0.04 * math.exp(-step / 4000))
    )
    grad = 0.45 + 1.6 * math.exp(-step / 5000) + abs(rng.gauss(0, 0.05))
    tps = 412_000 + rng.gauss(0, 2500)
    util = 93 + rng.gauss(0, 1.2)
    if dip_at is not None and dip_at <= step < dip_at + 900:
        tps, util = 261_000 + rng.gauss(0, 4000), 62 + rng.gauss(0, 2)
    if spike_at is not None and spike_at <= step < spike_at + 40:  # one bad batch
        loss += 1.4 * math.exp(-(step - spike_at) / 15)
        grad += 4.0 * math.exp(-(step - spike_at) / 15)
    if diverge_at is not None and step >= diverge_at - 400:
        grad *= 1 + (step - diverge_at + 400) / 60
        loss += (step - diverge_at + 400) / 600
        if step >= diverge_at:
            loss = grad = float("nan")
    return {
        "train/loss": loss,
        "train/grad_norm": grad,
        "train/lr": _lr_at(step, lr),
        "train/tokens": step * 512 * 2048,
        "sys/tokens_per_sec": tps,
        "sys/gpu_util": util,
    }


def _llm_runs(root: Path, base: float) -> None:
    data = Path(tempfile.mkdtemp())
    (data / "train.txt").write_text("fineweb-edu sample shard\n" * 100, encoding="utf-8")
    with init(
        "llm-pretrain",
        name="prepare-data",
        dir=root,
        capture_env=False,
        config={"source": "fineweb-edu", "shards": 64},
        tags=["data"],
        _started=base - 4.8 * 3600,
    ) as prep:
        prep.log({"data/tokens_b": 10.2}, step=0, time=base - 4.8 * 3600 + 30)
        prep.log_artifact("fineweb-edu", data, type="dataset", metadata={"tokens": "10B"})
        (data / "train.txt").write_text("fineweb-edu sample shard v2\n" * 120, encoding="utf-8")
        prep.log_artifact(
            "fineweb-edu", data, type="dataset", metadata={"tokens": "12B", "dedup": True}
        )
        prep.finish(_ended=base - 4.8 * 3600 + 120)

    order = [
        (1e-4, 1),
        (1e-4, 2),
        (1e-4, 3),
        (3e-3, 1),
        (3e-3, 2),
        (3e-3, 3),
        (1e-3, 1),
        (1e-3, 2),
        (1e-3, 3),
        (3e-4, 1),
        (3e-4, 2),
        (3e-4, 3),
    ]
    runs: dict[str, str] = {}
    for i, (lr, seed) in enumerate(order):
        rng = random.Random(f"{lr}-{seed}")
        started = base - 4.6 * 3600 + i * 600
        name = f"lr{lr:.0e}".replace("e-0", "e-") + f"-s{seed}"
        crashed = lr == 3e-3 and seed == 2
        run = init(
            "llm-pretrain",
            name=name,
            dir=root,
            config=_llm_config(lr, seed),
            tags=["sweep", "seeds"],
            group=f"lr={lr:g}",
            _started=started,
        )
        run.use_artifact("fineweb-edu:v2")
        sec_per_step = 0.22
        t = started
        last = LLM_STEPS
        for step in range(0, LLM_STEPS + 1, LLM_EVERY):
            t = started + step * sec_per_step
            point = llm_point(
                step,
                lr,
                seed,
                rng,
                diverge_at=18_400 if crashed else None,
                dip_at=18_000 if (lr == 1e-3 and seed == 1) else None,
                spike_at=9_000 if (lr == 3e-4 and seed == 3) else None,
            )
            run.log(point, step=step, time=t)
            if step % 500 == 0:
                run.log(
                    {"eval/loss": point["train/loss"] + 0.03 + rng.gauss(0, 0.01)},
                    step=step,
                    time=t,
                )
            if step % 5000 == 0:
                run.log_text("samples/generation", _sample_text(step, rng), step=step)
            if crashed and step >= 18_420:
                last = step
                break
        if crashed:
            run.finish(
                "crashed",
                exit_code=1,
                _ended=t,
                error="FloatingPointError: loss is NaN at step 18420 (rank 5)",
            )
        else:
            if lr == 1e-3 and seed == 1:
                ckpt = Path(tempfile.mkdtemp())
                (ckpt / "model.safetensors").write_bytes(b"\0" * 2048)
                run.log_artifact(
                    "model", ckpt, type="checkpoint", metadata={"step": last, "eval/loss": 2.37}
                )
            run.finish(_ended=t)
        runs[name] = run.id

    # downstream of the checkpoint: an evaluation run that writes a report artifact
    with init(
        "llm-pretrain",
        name="eval-mmlu",
        dir=root,
        capture_env=False,
        config={"model": "model:v1", "benchmark": "mmlu", "shots": 5},
        tags=["eval"],
        _started=base - 600,
    ) as ev:
        ev.use_artifact("model:latest")
        rng = random.Random("eval")
        for i, subject in enumerate(("stem", "humanities", "social", "other")):
            ev.log(
                {f"eval/mmlu_{subject}": 0.41 + rng.random() * 0.08}, step=i, time=base - 600 + i
            )
        report = Path(tempfile.mkdtemp())
        (report / "mmlu.json").write_text('{"accuracy": 0.447}', encoding="utf-8")
        ev.log_artifact("eval-report", report, type="report", metadata={"mmlu": 0.447})
        ev.finish(_ended=base - 300)

    # a hand-picked collection and a few custom fields, as a reviewer would leave them
    project = root / "llm-pretrain"
    save_collection(
        project,
        "shortlist",
        add=[runs["lr1e-3-s1"], runs["lr1e-3-s2"], runs["lr3e-4-s1"]],
        description="Candidates for the 7B run",
    )
    save_collection(
        project, "paper-figures", add=[runs[f"lr{x}-s1"] for x in ("1e-4", "3e-4", "1e-3")]
    )
    verdicts = {
        "lr1e-3-s1": "keep",
        "lr1e-3-s2": "keep",
        "lr3e-3-s2": "diverged",
        "lr1e-4-s1": "too slow",
    }
    for path in (project / "runs").iterdir():
        meta = _fs.read_json(path / "run.json", {})
        if meta.get("name") in verdicts:
            ann = _fs.read_json(path / "annotations.json", {}) or {}
            ann["fields"] = {"verdict": verdicts[meta["name"]], "owner": "esteban"}
            _fs.atomic_write_json(path / "annotations.json", ann)


_WORDS = (
    "the model learns to predict tokens and the loss goes down while the data "
    "streams in shards across many nodes"
).split()


def _sample_text(step: int, rng: random.Random) -> str:
    n = 12 + step // 2500
    quality = min(1.0, step / 20000)
    words = [
        w if rng.random() < 0.3 + 0.7 * quality else rng.choice(["qx", "zzt", "##", "lorem"])
        for w in (rng.choice(_WORDS) for _ in range(n))
    ]
    return f"Prompt: Once upon a time\nStep {step}: " + " ".join(words)


def _pattern(seed: int, epoch: int, kind: str) -> Any:
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None
    rng = np.random.default_rng(seed * 1000 + epoch)
    y, x = np.mgrid[0:64, 0:64] / 64.0
    img = np.stack(
        [
            0.5 + 0.5 * np.sin(6 * x + epoch / 7 + seed),
            0.5 + 0.5 * np.cos(5 * y - epoch / 9),
            0.5 + 0.5 * np.sin(4 * (x + y) + seed),
        ],
        axis=-1,
    )
    if kind == "mixup":
        img = 0.5 * img + 0.5 * img[::-1, ::-1]
    elif kind == "cutmix":
        img[16:40, 16:40] = img[::-1, :][16:40, 16:40]
    elif kind == "randaug":
        img = np.rot90(img, k=epoch % 4)
    img += rng.normal(0, 0.08 * max(0.0, 1 - epoch / 100), img.shape)
    return img.clip(0, 1)


def _vit_runs(root: Path, base: float) -> None:
    gains = {"none": 0.0, "randaug": 0.021, "mixup": 0.015, "cutmix": 0.026}
    for i, (aug, seed) in enumerate((a, s) for a in gains for s in (0, 1)):
        rng = random.Random(f"{aug}{seed}")
        started = base - 20 * 3600 + i * 1800
        config = {
            "model": "vit-s16",
            "augment": aug,
            "epochs": 100,
            "lr": 5e-4,
            "batch_size": 256,
            "seed": seed,
            "mixup_alpha": 0.2 if aug == "mixup" else None,
        }
        run = init(
            "vit-ablations",
            name=f"{aug}-s{seed}",
            dir=root,
            config=config,
            tags=["ablation"],
            capture_env=False,
            _started=started,
        )
        t = started
        for epoch in range(101):
            t = started + epoch * 60
            acc = 0.62 + gains[aug] + 0.18 * (1 - math.exp(-epoch / 25)) + rng.gauss(0, 0.004)
            run.log(
                {
                    "train/loss": 2.2 * math.exp(-epoch / 30)
                    + 0.35
                    - gains[aug]
                    + rng.gauss(0, 0.02),
                    "val/acc": acc,
                    "val/loss": 1.6 - acc + rng.gauss(0, 0.01),
                },
                step=epoch,
                time=t,
            )
            if epoch % 20 == 0:
                img = _pattern(seed, epoch, aug)
                if img is not None:
                    run.log_image(
                        "samples/augmented", img, step=epoch, caption=f"{aug} epoch {epoch}"
                    )
                run.log_html("eval/report", _report_html(aug, epoch, acc), step=epoch)
                per_class = _per_class(rng, acc)
                run.log_figure("eval/per_class", _vega_per_class(per_class, epoch), step=epoch)
                run.log_figure("eval/confusion", _plotly_confusion(rng, per_class), step=epoch)
        run.finish(_ended=t)


_CLASSES = ["plane", "car", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]


def _per_class(rng: random.Random, acc: float) -> list[float]:
    hard = {"cat": -0.12, "dog": -0.09, "bird": -0.05}
    return [min(0.99, acc + hard.get(c, 0.03) + rng.gauss(0, 0.015)) for c in _CLASSES]


def _vega_per_class(per_class: list[float], epoch: int) -> dict[str, Any]:
    """A Vega-Lite spec as a plain dict, as altair's ``to_dict()`` would produce."""
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "title": f"Per-class accuracy, epoch {epoch}",
        "width": "container",
        "height": 260,
        "data": {"values": [{"class": c, "acc": round(a, 4)} for c, a in zip(_CLASSES, per_class)]},
        "mark": {"type": "bar", "cornerRadiusEnd": 3, "tooltip": True},
        "encoding": {
            "x": {"field": "class", "type": "nominal", "sort": "-y", "title": None},
            "y": {"field": "acc", "type": "quantitative", "scale": {"zero": False}},
            "color": {"value": "#0072b2"},
        },
    }


def _plotly_confusion(rng: random.Random, per_class: list[float]) -> dict[str, Any]:
    """A Plotly figure as a plain dict, as ``fig.to_dict()`` would produce."""
    rows = []
    for i, a in enumerate(per_class):
        rest = [rng.random() ** 3 for _ in _CLASSES]
        rest[i] = 0.0
        if _CLASSES[i] in ("cat", "dog"):  # cats and dogs get confused with each other
            rest[_CLASSES.index("dog" if _CLASSES[i] == "cat" else "cat")] += 4.0
        total = sum(rest)
        rows.append([round(a if j == i else (1 - a) * r / total, 4) for j, r in enumerate(rest)])
    return {
        "data": [
            {
                "type": "heatmap",
                "z": rows,
                "x": _CLASSES,
                "y": _CLASSES,
                "colorscale": [[0, "rgba(0,114,178,0.04)"], [1, "#0072b2"]],
                "hovertemplate": "true %{y}<br>predicted %{x}<br>%{z:.3f}<extra></extra>",
            }
        ],
        "layout": {
            "title": {"text": "Confusion matrix"},
            "height": 460,
            "xaxis": {"title": {"text": "predicted"}},
            "yaxis": {"title": {"text": "true"}, "autorange": "reversed"},
        },
    }


def _report_html(aug: str, epoch: int, acc: float) -> str:
    bar = int(acc * 200)
    return (
        "<!doctype html><meta charset=utf-8><body style='font:14px system-ui;margin:12px'>"
        f"<h3 style='margin:0 0 8px'>Eval report: {aug}, epoch {epoch}</h3>"
        f"<div style='background:#0072b2;height:14px;width:{bar}px;border-radius:3px'></div>"
        f"<p>top-1 accuracy <b>{acc:.3f}</b></p>"
        "<button onclick=\"this.textContent='scripts run in a sandbox'\">click me</button></body>"
    )


def _ppo_runs(root: Path, base: float) -> None:
    for i, (env, seed) in enumerate((e, s) for e in ("Pong", "Breakout") for s in (0, 1, 2)):
        rng = random.Random(f"{env}{seed}")
        started = base - 40 * 3600 + i * 2400
        top = 21 if env == "Pong" else 380
        run = init(
            "ppo-atari",
            name=f"{env.lower()}-s{seed}",
            dir=root,
            capture_env=False,
            config={
                "env": f"ALE/{env}-v5",
                "algo": "ppo",
                "seed": seed,
                "num_envs": 16,
                "total_steps": 2_000_000,
                "clip": 0.1,
                "lr": 2.5e-4,
            },
            tags=["rl", env.lower()],
            _started=started,
        )
        t = started
        for k in range(201):
            step = k * 10_000
            t = started + k * 9
            frac = 1 / (1 + math.exp(-(k - 90 - 10 * seed) / 18))
            ret = (-21 + (top + 21) * frac if env == "Pong" else top * frac) + rng.gauss(
                0, top * 0.04
            )
            run.log(
                {
                    "charts/episode_return": ret,
                    "losses/value": 0.5 * (1 - frac) + abs(rng.gauss(0, 0.05)),
                    "losses/policy": rng.gauss(-0.01, 0.005),
                    "charts/fps": 4200 + rng.gauss(0, 120),
                },
                step=step,
                time=t,
            )
        run.finish(_ended=t)


def generate(root: str | Path, *, quiet: bool = False) -> Path:
    """Write the demo workspace under ``root`` (safe to run again: adds new runs)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = time.time() - 600
    for label, fn in (
        ("llm-pretrain", _llm_runs),
        ("vit-ablations", _vit_runs),
        ("ppo-atari", _ppo_runs),
    ):
        t0 = time.perf_counter()
        fn(root, base)
        if not quiet:
            print(f"  {label:<14} written in {time.perf_counter() - t0:.1f}s")
    return root


def live(root: str | Path, stop: threading.Event | None = None, speed: float = 1.0) -> None:
    """Keep logging a run in real time (until ``stop`` is set), one seed after another."""
    stop = stop or threading.Event()
    seed = 4
    while not stop.is_set():
        lr = 1e-3
        rng = random.Random(seed)
        run = init(
            "llm-pretrain",
            name=f"lr1e-3-live-s{seed}",
            dir=root,
            config=_llm_config(lr, seed),
            tags=["sweep", "live"],
            group=f"lr={lr:g}",
            capture_env=False,
            heartbeat_interval=3.0,
        )
        step = 0
        while step <= LLM_STEPS and not stop.is_set():
            point = llm_point(step, lr, seed, rng)
            run.log(point, step=step)
            if step % 500 == 0:
                run.log({"eval/loss": point["train/loss"] + 0.03}, step=step)
            step += LLM_EVERY
            time.sleep(0.05 / speed)
        run.finish("finished" if step > LLM_STEPS else "killed")
        seed += 1
