"""Synthetic demo workspace: four projects, ~26 runs, media, artifacts and a live run."""

from __future__ import annotations

import itertools
import math
import random
import struct
import tempfile
import threading
import time
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from . import _fs
from .collection import save_collection
from .reports import save_fields, save_report, save_snapshot
from .run import init

LLM_LRS = {3e-4: 2.43, 1e-3: 2.345, 3e-3: 2.505, 1e-4: 2.78}  # lr -> final loss
LLM_STEPS = 25_000
LLM_EVERY = 10


def _llm_config(lr: float, seed: int) -> dict[str, Any]:
    """Return the config of a demo LLM pretraining run."""
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


def _yaml(obj: dict[str, Any], indent: int = 0) -> str:
    """Return a small config of dicts, lists and scalars as YAML text."""

    def scalar(v: Any) -> str:
        if v is None:
            return "null"

        if isinstance(v, bool):
            return "true" if v else "false"

        if isinstance(v, list):
            return "[" + ", ".join(scalar(x) for x in v) + "]"

        return str(v)

    lines = []

    for key, value in obj.items():
        if isinstance(value, dict):
            lines.append(f"{' ' * indent}{key}:")
            lines.append(_yaml(value, indent + 2).rstrip("\n"))
        else:
            lines.append(f"{' ' * indent}{key}: {scalar(value)}")

    return "\n".join(lines) + "\n"


def _add_config_file(run: Any, config: dict[str, Any]) -> None:
    """Attach `config` to `run` as `files/config.yaml`, as a YAML-based project would."""
    path = Path(tempfile.mkdtemp()) / "config.yaml"
    path.write_text(_yaml(config), "utf-8")
    run.add_file(path)


def _lr_at(step: int, lr: float) -> float:
    """Return the learning rate at `step`: 1000 steps of linear warmup, then cosine decay."""

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
    """Return synthetic LLM training metrics for one step.

    The loss decays from about 5.3 towards a final value that depends on `lr`
    (see `LLM_LRS`) and `seed`.

    Args:
        step: Training step.
        lr: Peak learning rate.
        seed: Seed of the run; shifts the final loss slightly.
        rng: Random generator for the noise.
        diverge_at: Step at which the run diverges. Loss and gradient norm grow
            over the 400 steps before it and are NaN from it on.
        dip_at: Step at which a 900-step throughput and GPU utilization dip starts.
        spike_at: Step of one bad batch that briefly spikes the loss and gradient norm.

    Returns:
        A dict with `train/loss`, `train/grad_norm`, `train/lr`, `train/tokens`,
        `sys/tokens_per_sec` and `sys/gpu_util`.
    """
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
    """Write the `llm-pretrain` project: data prep, a 12-run lr/seed sweep, an eval run.

    Also saves two collections and sets custom fields on some runs.
    """
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
        prep.add_artifact("fineweb-edu", data, type="dataset", metadata={"tokens": "10B"})
        (data / "train.txt").write_text("fineweb-edu sample shard v2\n" * 120, encoding="utf-8")
        prep.add_artifact(
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
        _add_config_file(run, _llm_config(lr, seed))
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
                run.add_text("samples/generation", _sample_text(step, rng), step=step)

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
                run.add_artifact(
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
        ev.add_artifact("eval-report", report, type="report", metadata={"mmlu": 0.447})
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
    """Return a fake text generation that gets longer and less garbled as `step` grows."""
    n = 12 + step // 2500
    quality = min(1.0, step / 20000)
    words = [
        w if rng.random() < 0.3 + 0.7 * quality else rng.choice(["qx", "zzt", "##", "lorem"])
        for w in (rng.choice(_WORDS) for _ in range(n))
    ]
    return f"Prompt: Once upon a time\nStep {step}: " + " ".join(words)


def _pattern(seed: int, epoch: int, kind: str) -> Any:
    """Return a 64x64 RGB image in [0, 1] for an augmentation kind, or None without numpy."""

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
    """Write the `vit-ablations` project: four augmentations times two seeds, with media."""
    gains = {"none": 0.0, "randaug": 0.021, "mixup": 0.015, "cutmix": 0.026}
    ids: dict[str, str] = {}
    curves: dict[str, list[float]] = {}

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
        _add_config_file(run, config)
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
                    **_vit_extra(epoch, acc, rng),
                },
                step=epoch,
                time=t,
            )
            curves.setdefault(f"{aug}-s{seed}", []).append(acc)

            if epoch % 20 == 0:
                img = _pattern(seed, epoch, aug)

                if img is not None:
                    run.add_image(
                        "samples/augmented", img, step=epoch, caption=f"{aug} epoch {epoch}"
                    )

                run.add_html("eval/report", _report_html(aug, epoch, acc), step=epoch)
                per_class = _per_class(rng, acc)
                run.add_figure("eval/per_class", _vega_per_class(per_class, epoch), step=epoch)
                run.add_figure("eval/confusion", _plotly_confusion(rng, per_class), step=epoch)

        ids[f"{aug}-s{seed}"] = run.id
        run.finish(_ended=t)

    _vit_notes(root / "vit-ablations", ids, curves)


def _vit_extra(epoch: int, acc: float, rng: random.Random) -> dict[str, float]:
    """Return the other `vit-ablations` metrics of one epoch, enough to fill the chart grid."""
    lr = 5e-4 * min(1.0, (epoch + 1) / 5) * 0.5 * (1 + math.cos(math.pi * epoch / 100))
    out = {
        "train/lr": lr,
        "train/grad_norm": 1.2 * math.exp(-epoch / 60) + 0.3 + abs(rng.gauss(0, 0.05)),
        "val/top5": min(0.999, acc + 0.12 + rng.gauss(0, 0.002)),
        "val/calibration_error": 0.08 * math.exp(-epoch / 40) + 0.02 + abs(rng.gauss(0, 0.003)),
        "sys/gpu_util": 0.9 + rng.gauss(0, 0.02),
        "sys/gpu_mem_gb": 21.5 + rng.gauss(0, 0.1),
        "sys/images_per_sec": 2400 + rng.gauss(0, 40),
    }

    for i, name in enumerate(_CLASSES):  # one chart per class: a section with many charts
        out[f"per_class/acc_{name}"] = min(0.999, acc + 0.05 * math.sin(i) + rng.gauss(0, 0.006))

    return out


def _png(width: int, height: int, pixels: bytearray) -> bytes:
    """Encode RGB `pixels` (row by row) as a PNG with the standard library."""
    rows = b"".join(
        b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        """Return one PNG chunk."""
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def _line_chart_png(curves: list[tuple[list[float], tuple[int, int, int]]]) -> bytes:
    """Draw curves on a white 720x300 image: the snapshot of a chart saved into a report."""
    w, h, pad = 720, 300, 24
    px = bytearray(b"\xff" * (w * h * 3))
    lo = min(min(c) for c, _ in curves)
    hi = max(max(c) for c, _ in curves)

    def dot(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        """Paint a 2x2 dot."""

        for dx in (0, 1):
            for dy in (0, 1):
                if 0 <= x + dx < w and 0 <= y + dy < h:
                    i = ((y + dy) * w + x + dx) * 3
                    px[i : i + 3] = bytes(rgb)

    for k in range(5):  # light grid lines
        y = pad + k * (h - 2 * pad) // 4

        for x in range(pad, w - pad):
            px[(y * w + x) * 3 : (y * w + x) * 3 + 3] = b"\xe4\xe7\xec"

    for values, rgb in curves:
        n = len(values) - 1
        pts = [
            (pad + i * (w - 2 * pad) / n, h - pad - (v - lo) / (hi - lo) * (h - 2 * pad))
            for i, v in enumerate(values)
        ]

        for (x0, y0), (x1, y1) in itertools.pairwise(pts):
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1

            for s in range(steps + 1):
                dot(round(x0 + (x1 - x0) * s / steps), round(y0 + (y1 - y0) * s / steps), rgb)

    return _png(w, h, px)


def _vit_notes(project: Path, ids: dict[str, str], curves: dict[str, list[float]]) -> None:
    """Add typed properties, a Markdown note and a report to the `vit-ablations` demo."""
    save_fields(
        project,
        [
            {"name": "verdict", "type": "choice", "options": ["keep", "drop", "rerun"]},
            {"name": "topics", "type": "tags", "options": ["augmentation", "baseline"]},
            {"name": "gpu_hours", "type": "number", "unit": "h"},
            {"name": "reviewed", "type": "bool"},
            {"name": "paper", "type": "link", "description": "Where the idea comes from"},
        ],
    )
    values = {
        "none-s0": {"verdict": "keep", "topics": ["baseline"], "gpu_hours": 6.5},
        "cutmix-s0": {
            "verdict": "keep",
            "topics": ["augmentation"],
            "gpu_hours": 6.8,
            "reviewed": True,
            "paper": "https://arxiv.org/abs/1905.04899",
        },
        "mixup-s1": {"verdict": "rerun", "topics": ["augmentation"], "gpu_hours": 6.7},
    }
    notes = {
        "cutmix-s0": (
            "**Best of the sweep** so far, about +2.6 points over the baseline.\n\n"
            "- Gains show up after epoch 20\n"
            "- Trucks and ships are still confused\n\n"
            f"![Confusion at the last epoch](media:{ids['cutmix-s0']}/eval/confusion@100)\n"
        ),
    }

    for name, run_id in ids.items():
        if name not in values and name not in notes:
            continue

        path = project / "runs" / run_id / "annotations.json"
        ann = _fs.read_json(path, {}) or {}
        ann["fields"] = values.get(name, {})

        if name in notes:
            ann["notes"] = notes[name]

        _fs.atomic_write_json(path, ann)

    # a chart saved from the Charts page: a PNG snapshot, drawn live by the viewer
    shot = save_snapshot(
        project,
        "augmentation-findings",
        _line_chart_png([(curves["cutmix-s0"], (0, 114, 178)), (curves["none-s0"], (230, 159, 0))]),
    )
    runs = ",".join(ids[n] for n in ("cutmix-s0", "none-s0"))
    spec = urlencode({"metric": "val/acc", "runs": runs, "x": "step", "smooth": "0.6"})
    save_report(
        project,
        "augmentation-findings",
        "# Augmentation findings\n\n"
        "CutMix gives the largest gain on ViT-S/16; MixUp is close but noisier across seeds.\n\n"
        "## Samples\n\n"
        f"![CutMix samples at epoch 100](media:{ids['cutmix-s0']}/samples/augmented@100)\n\n"
        f"![Baseline samples at epoch 100](media:{ids['none-s0']}/samples/augmented@100)\n\n"
        "## Accuracy\n\n"
        f'![val/acc, CutMix against the baseline]({shot} "chart:{spec}")\n\n'
        "## Errors\n\n"
        f"![CutMix confusion](media:{ids['cutmix-s0']}/eval/confusion@100)\n\n"
        "| run | val/acc |\n|---|---|\n| none-s0 | 0.80 |\n| cutmix-s0 | 0.83 |\n",
    )


_CLASSES = ["plane", "car", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]


def _per_class(rng: random.Random, acc: float) -> list[float]:
    """Return per-class accuracies around `acc`, lower for cat, dog and bird."""
    hard = {"cat": -0.12, "dog": -0.09, "bird": -0.05}
    return [min(0.99, acc + hard.get(c, 0.03) + rng.gauss(0, 0.015)) for c in _CLASSES]


def _vega_per_class(per_class: list[float], epoch: int) -> dict[str, Any]:
    """Return a Vega-Lite spec as a plain dict, as altair's `to_dict()` would produce."""
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
    """Return a Plotly figure as a plain dict, as `fig.to_dict()` would produce."""
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
    """Return a small HTML eval report with an accuracy bar and a scripted button."""
    bar = int(acc * 200)
    return (
        "<!doctype html><meta charset=utf-8><body style='font:14px system-ui;margin:12px'>"
        f"<h3 style='margin:0 0 8px'>Eval report: {aug}, epoch {epoch}</h3>"
        f"<div style='background:#0072b2;height:14px;width:{bar}px;border-radius:3px'></div>"
        f"<p>top-1 accuracy <b>{acc:.3f}</b></p>"
        "<button onclick=\"this.textContent='scripts run in a sandbox'\">click me</button></body>"
    )


SPEECH_RATE = 16_000


def _speech(rng: Any) -> Any:
    """Return about 2.5 s of a speech-like signal: voiced syllables with moving formants."""
    import numpy as np

    sr = SPEECH_RATE
    out = np.zeros(int(2.6 * sr))
    t0 = 0.15

    for _ in range(7):
        dur = rng.uniform(0.18, 0.32)
        n = int(dur * sr)
        t = np.arange(n) / sr
        f0 = rng.uniform(110, 190) * (1 + 0.12 * np.sin(2 * np.pi * t / dur))
        phase = 2 * np.pi * np.cumsum(f0) / sr
        f1, f2 = rng.uniform(300, 800), rng.uniform(900, 2400)
        syl = np.zeros(n)

        for h in range(1, 30):
            fh = h * f0.mean()

            if fh > 4000:
                break

            gain = np.exp(-(((fh - f1) / 160) ** 2)) + 0.6 * np.exp(-(((fh - f2) / 260) ** 2))
            syl += (gain + 0.02) / h**0.5 * np.sin(h * phase)

        syl *= np.hanning(n)
        start = int(t0 * sr)
        out[start : start + n] += syl[: len(out) - start]
        t0 += dur + rng.uniform(0.02, 0.12)

    return 0.6 * out / np.abs(out).max()


def _noise(rng: Any, n: int) -> Any:
    """Return café-like noise: pink noise (falling 3 dB per octave) plus a mains hum."""
    import numpy as np

    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    f = np.fft.rfftfreq(n, 1 / SPEECH_RATE)
    spectrum /= np.sqrt(np.maximum(f, 40.0))
    pink = np.fft.irfft(spectrum, n)
    t = np.arange(n) / SPEECH_RATE
    hum = sum(np.sin(2 * np.pi * 50 * k * t) / k for k in (1, 2, 3))
    return 0.08 * pink / pink.std() + 0.02 * hum


def _speech_runs(root: Path, base: float) -> None:
    """Write the `speech-denoise` project: three models with audio samples (needs numpy)."""

    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return

    models = {"unet-l1": (0.30, 0.020), "unet-sisdr": (0.16, 0.012), "convtasnet": (0.10, 0.006)}
    rng = np.random.default_rng(7)
    clean = _speech(rng)
    noise = _noise(rng, len(clean))
    noisy = np.clip(clean + noise, -1, 1)

    for i, (model, (floor, artifacts)) in enumerate(models.items()):
        prng = random.Random(model)
        started = base - 30 * 3600 + i * 2400
        run = init(
            "speech-denoise",
            name=model,
            dir=root,
            capture_env=False,
            config={
                "model": model.split("-")[0],
                "loss": model.split("-")[1] if "-" in model else "si-sdr",
                "sample_rate": SPEECH_RATE,
                "lr": 3e-4,
                "epochs": 30,
            },
            tags=["audio", "enhancement"],
            _started=started,
        )
        run.add_audio("audio/noisy", noisy, step=0, sample_rate=SPEECH_RATE, caption="input")
        run.add_audio("audio/clean", clean, step=0, sample_rate=SPEECH_RATE, caption="target")
        t = started

        for epoch in range(31):
            t = started + epoch * 70
            left = floor + (1 - floor) * math.exp(-epoch / 7)  # residual noise gain
            run.log(
                {
                    "train/loss": 0.4 * left + prng.gauss(0, 0.006),
                    "val/si_sdr": 5 + 14 * (1 - left) - 40 * artifacts + prng.gauss(0, 0.2),
                    "val/pesq": 1.4 + 2.4 * (1 - left) + prng.gauss(0, 0.03),
                },
                step=epoch,
                time=t,
            )

            if epoch % 10 == 0:
                erng = np.random.default_rng(epoch * 31 + i)
                # sparse "musical noise": short tonal blips a real model leaves behind
                blips = np.zeros(len(clean))

                for _ in range(int(12 * (1 - epoch / 40))):
                    at, n = erng.integers(0, len(clean) - 800), 800
                    f = erng.uniform(1500, 5000)
                    blips[at : at + n] += np.hanning(n) * np.sin(
                        2 * np.pi * f * np.arange(n) / SPEECH_RATE
                    )

                out = clean + left * noise + artifacts * 6 * blips
                run.add_audio(
                    "audio/enhanced",
                    np.clip(out, -1, 1),
                    step=epoch,
                    sample_rate=SPEECH_RATE,
                    caption=f"epoch {epoch}",
                )

        run.finish(_ended=t)


def _ppo_runs(root: Path, base: float) -> None:
    """Write the `ppo-atari` project: Pong and Breakout, three seeds each."""

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
    """Write the demo workspace under `root`.

    Safe to run again: each call adds new runs next to the existing ones.

    Args:
        root: Folder to write the projects into; created if missing.
        quiet: Do not print how long each project took.

    Returns:
        `root` as a `Path`.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = time.time() - 600

    for label, fn in (
        ("llm-pretrain", _llm_runs),
        ("vit-ablations", _vit_runs),
        ("ppo-atari", _ppo_runs),
        ("speech-denoise", _speech_runs),
    ):
        t0 = time.perf_counter()
        fn(root, base)

        if not quiet:
            print(f"  {label:<14} written in {time.perf_counter() - t0:.1f}s")

    return root


def live(root: str | Path, stop: threading.Event | None = None, speed: float = 1.0) -> None:
    """Keep logging a run in real time until `stop` is set, one seed after another.

    Each run logs the LLM demo metrics every 10 steps, finishes as `finished`
    after the last step, and is followed by a run with the next seed. A run cut
    short by `stop` finishes as `killed`.

    Args:
        root: Folder holding the demo workspace.
        stop: Event that ends the loop. Without one, the loop never ends.
        speed: Speed-up factor; at 1.0 a log call happens every 0.05 s.
    """
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
