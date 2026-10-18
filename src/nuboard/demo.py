"""Synthetic demo workspace: four projects, ~26 runs, media, video, artifacts and a live run.

Datasets live outside the projects, in `shared-data/`, and are registered as
reference artifacts of a `datasets` project that the training projects use.
"""

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
from .cells import Audio
from .collection import save_collection
from .reports import save_fields, save_report, save_snapshot
from .run import add_artifact, init

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


def _add_console_log(run: Any, lines: list[str]) -> None:
    """Attach `lines` as `files/output.log`, as `capture_console` would have written it."""
    path = Path(tempfile.mkdtemp()) / "output.log"
    path.write_text("".join(lines), "utf-8")
    run.add_file(path)


def _console_head(run: Any, name: str) -> list[str]:
    """Return the start of an LLM run's console: a header, a progress bar and a warning."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.started))
    bar = "".join(
        f"\rtokenizing shards: {p:3d}%|{'#' * (p // 10):<10}| {p * 64 // 100}/64"
        for p in range(0, 101, 20)
    )
    return [
        f"[nuboard: session 0, {stamp}]\n",
        f"run {name}: 8 x H100, bf16, global batch 512 x 2048 tokens\n",
        bar + "\n",
        "\x1b[33mUserWarning: flash-attention not found, using sdpa\x1b[0m\n",
    ]


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
        dip_at: Step at which a 900-step throughput dip starts.
        spike_at: Step of one bad batch that briefly spikes the loss and gradient norm.

    Returns:
        A dict with `train/loss`, `train/grad_norm`, `train/lr`, `train/tokens`,
        and `perf/tokens_per_sec`.
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

    if dip_at is not None and dip_at <= step < dip_at + 900:
        tps = 261_000 + rng.gauss(0, 4000)

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
        "perf/tokens_per_sec": tps,
    }


def _llm_system(step: int, rng: random.Random, dip: bool = False) -> dict[str, float]:
    """Return plausible `system/` scalars of one node with two GPUs at `step`.

    With `dip`, GPU utilization drops with the throughput dip of `llm_point`.
    """
    warm = min(1.0, step / 400)
    util = 62 if dip else 96 * warm
    out = {
        "system/cpu/percent": 30 + 8 * warm + rng.gauss(0, 2),
        "system/cpu/process_percent": 160 + 40 * warm + rng.gauss(0, 10),
        "system/memory/used_gb": 41 + 6 * warm + step / 20_000 + rng.gauss(0, 0.2),
        "system/memory/percent": (41 + 6 * warm + step / 20_000) / 2.56,
        "system/memory/process_gb": 18 + 3 * warm + step / 40_000,
        "system/torch/cuda_allocated_gb": 52.4 * warm + rng.gauss(0, 0.05),
        "system/torch/cuda_peak_gb": 61.8 * warm,
    }

    for g in (0, 1):
        out |= {
            f"system/gpu{g}/util": min(100.0, util + rng.gauss(0, 2)),
            f"system/gpu{g}/memory_gb": 66.1 * warm + 0.6,
            f"system/gpu{g}/memory_percent": (66.1 * warm + 0.6) / 0.8,
            f"system/gpu{g}/temp_c": 38 + 27 * warm + g + rng.gauss(0, 0.6),
            f"system/gpu{g}/power_w": 70 + 580 * warm + rng.gauss(0, 15),
        }

    return out


def _shared_data(root: Path, name: str, files: dict[str, str]) -> Path:
    """Write a small dataset under `<root>/shared-data/<name>/` unless it is there already.

    It is left alone when it exists, so the reference artifacts of an earlier
    `generate` keep matching their files.
    """
    folder = root / "shared-data" / name

    for rel, text in files.items():
        path = folder / rel

        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    return folder


def _llm_runs(root: Path, base: float) -> None:
    """Write the `llm-pretrain` project: data prep, a 12-run lr/seed sweep, an eval run.

    Also saves two collections and sets custom fields on some runs.
    """
    shards = {
        "2026-09": "fineweb-edu sample shard\n" * 100,
        "2026-10": "fineweb-edu sample shard v2\n" * 120,
    }
    folders = [_shared_data(root, f"fineweb-edu/{k}", {"train.txt": v}) for k, v in shards.items()]

    with init(
        "llm-pretrain",
        name="prepare-data",
        dir=root,
        capture_env=False,
        system_metrics=False,
        capture_console=False,
        config={"source": "fineweb-edu", "shards": 64},
        tags=["data"],
        _started=base - 4.8 * 3600,
    ) as prep:
        prep.add_scalar({"data/tokens_b": 10.2}, step=0, time=base - 4.8 * 3600 + 30)
        # the data stays in shared-data/; the datasets project only records it
        prep.add_artifact(
            "datasets/fineweb-edu",
            folders[0],
            type="dataset",
            metadata={"tokens": "10B"},
            description="FineWeb-Edu, September 2026 snapshot",
            reference=True,
        )
        fineweb = prep.add_artifact(
            "datasets/fineweb-edu",
            folders[1],
            type="dataset",
            metadata={"tokens": "12B", "dedup": True},
            description="FineWeb-Edu, October 2026 snapshot, deduplicated",
            reference=True,
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
            system_metrics=False,
            capture_console=False,
            _started=started,
        )
        _add_config_file(run, _llm_config(lr, seed))
        run.use_artifact(f"datasets/{fineweb.ref}")
        sec_per_step = 0.22
        t = started
        last = LLM_STEPS
        console = _console_head(run, name)

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
            run.add_scalar(point, step=step, time=t)

            if step % 1000 == 0:
                tps = point["perf/tokens_per_sec"] / 1e3
                console.append(
                    f"step {step:>6} | loss {point['train/loss']:.4f} | "
                    f"lr {point['train/lr']:.2e} | {tps:.0f}k tok/s\n"
                )

            if step % 500 == 0:
                run.add_scalar(
                    {"eval/loss": point["train/loss"] + 0.03 + rng.gauss(0, 0.01)},
                    step=step,
                    time=t,
                )

            if step % 500 == 0:
                dip = lr == 1e-3 and seed == 1 and 18_000 <= step < 18_900
                run.add_scalar(_llm_system(step, rng, dip), step=step, time=t)

            if step % 5000 == 0:
                run.add_text("samples/generation", _sample_text(step, rng), step=step)

            if crashed and step >= 18_420:
                last = step
                break

        if crashed:
            console.append(
                "Traceback (most recent call last):\n"
                '  File "train.py", line 214, in <module>\n'
                "    check_finite(loss)\n"
                "FloatingPointError: loss is NaN at step 18420 (rank 5)\n"
            )

        _add_console_log(run, console)

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
                    "model",
                    ckpt,
                    type="checkpoint",
                    metadata={"step": last, "eval/loss": 2.37},
                    description="Final checkpoint of the lr=1e-3 seed 1 run",
                )

            run.finish(_ended=t)

        runs[name] = run.id

    # downstream of the checkpoint: an evaluation run that writes a report artifact
    with init(
        "llm-pretrain",
        name="eval-mmlu",
        dir=root,
        capture_env=False,
        system_metrics=False,
        capture_console=False,
        config={"model": "model:v1", "benchmark": "mmlu", "shots": 5},
        tags=["eval"],
        _started=base - 600,
    ) as ev:
        ev.use_artifact("model:latest")
        rng = random.Random("eval")

        for i, subject in enumerate(("stem", "humanities", "social", "other")):
            ev.add_scalar(
                {f"eval/mmlu_{subject}": 0.41 + rng.random() * 0.08}, step=i, time=base - 600 + i
            )

        report = Path(tempfile.mkdtemp())
        (report / "mmlu.json").write_text('{"accuracy": 0.447}', encoding="utf-8")
        ev.add_artifact(
            "eval-report",
            report,
            type="report",
            metadata={"mmlu": 0.447},
            description="MMLU results of model:v1",
        )
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
        if not path.is_dir():  # such as macOS's .DS_Store
            continue

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


#: Class colors of the embedding demo (the viewer's series palette)
_CLASS_RGB = [
    (0, 114, 178),
    (230, 159, 0),
    (204, 121, 167),
    (0, 158, 115),
    (213, 94, 0),
    (86, 180, 233),
    (138, 122, 0),
    (106, 76, 147),
    (120, 120, 120),
    (240, 228, 66),
]


def _embeddings(seed: int, epoch: int, gain: float) -> tuple[Any, Any] | None:
    """Return 3D eval embeddings and class colors, or None without numpy.

    Ten classes start mixed and pull into their own clusters as training goes
    on; stronger augmentations end with tighter clusters.
    """

    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None

    rng = np.random.default_rng(seed * 7 + 1)  # same samples and centers at every epoch
    per = 300
    phi = np.arccos(1 - 2 * (np.arange(10) + 0.5) / 10)
    theta = np.pi * (1 + 5**0.5) * np.arange(10)
    centers = np.stack(
        [np.sin(phi) * np.cos(theta), np.sin(phi) * np.sin(theta), np.cos(phi)], axis=1
    )
    labels = np.repeat(np.arange(10), per)
    noise = rng.normal(size=(10 * per, 3))
    progress = 1 - math.exp(-epoch / 30)
    spread = 0.75 - (0.55 + 4 * gain) * progress
    points = centers[labels] * (0.15 + 0.85 * progress) + noise * spread
    colors = np.array(_CLASS_RGB, dtype="uint8")[labels]
    return points, colors


def _distributions(seed: int, epoch: int, gain: float) -> dict[str, Any]:
    """Return values for the `vit-ablations` histograms of one epoch.

    Attention weights spread out from their initialization, gradients shrink
    as the loss falls, and the logits of correct and wrong classes split into
    two modes, further apart for stronger augmentations.
    """

    progress = 1 - math.exp(-epoch / 30)

    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        rng = random.Random(f"{seed}-{epoch}-{gain}")
        weights = [rng.gauss(0, 0.02 + 0.03 * progress) for _ in range(4000)]
        return {"params/attn.qkv.weight": weights}

    rng = np.random.default_rng([seed, epoch, round(gain * 1000)])
    weights = rng.normal(0, 0.02 + 0.03 * progress, 20000)
    weights += rng.laplace(0, 0.01 * progress, 20000)
    grads = rng.standard_t(8, 20000) * 0.01 * (0.15 + 0.85 * math.exp(-epoch / 20))
    split = (1.5 + 60 * gain) * progress
    correct = rng.random(5000) < 0.62 + gain + 0.18 * progress
    logits = np.where(correct, rng.normal(split, 1.0, 5000), rng.normal(-split * 0.6, 1.0, 5000))
    return {
        "params/attn.qkv.weight": weights,
        "grads/attn.qkv.weight": grads,
        "eval/logit_margin": logits,
    }


def _pr_samples(rng: random.Random, acc: float, hard: float) -> tuple[list[int], list[float]]:
    """Return labels and scores for one class: 10% positives, separated more as `acc` rises."""
    labels = [int(rng.random() < 0.1) for _ in range(1000)]
    gap = (acc - 0.5) * 12 * (1.3 - 0.6 * hard)
    scores = [1 / (1 + math.exp(-(rng.gauss(0, 1) + (gap if y else -gap) / 2 - 1))) for y in labels]
    return labels, scores


def _vit_runs(root: Path, base: float) -> None:
    """Write the `vit-ablations` project: four augmentations times two seeds, with media."""
    gains = {"none": 0.0, "randaug": 0.021, "mixup": 0.015, "cutmix": 0.026}
    ids: dict[str, str] = {}
    # registered once, by hand rather than by a run, as data downloaded elsewhere often is
    images = add_artifact(
        "datasets",
        "imagenet-100",
        _shared_data(
            root, "imagenet-100", {f"train/shard-{i:02d}.tar": f"{i}" * 64 for i in range(4)}
        ),
        type="dataset",
        metadata={"classes": 100, "images": 126689},
        description="ImageNet-100 training split, as downloaded",
        reference=True,
        dir=root,
    )
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
            system_metrics=False,
            capture_console=False,
            _started=started,
        )
        _add_config_file(run, config)
        run.use_artifact(f"datasets/{images.ref}")
        t = started

        for epoch in range(101):
            t = started + epoch * 60
            acc = 0.62 + gains[aug] + 0.18 * (1 - math.exp(-epoch / 25)) + rng.gauss(0, 0.004)
            run.add_scalar(
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

            if epoch % 5 == 0:
                for key, values in _distributions(seed, epoch, gains[aug]).items():
                    run.add_histogram(key, values, step=epoch)

            if epoch % 20 == 0:
                img = _pattern(seed, epoch, aug)

                if img is not None:
                    run.add_image(
                        "samples/augmented", img, step=epoch, caption=f"{aug} epoch {epoch}"
                    )

                emb = _embeddings(seed, epoch, gains[aug])

                if emb is not None:
                    run.add_point_cloud(
                        "eval/embeddings",
                        emb[0],
                        step=epoch,
                        colors=emb[1],
                        axes=("feature 1", "feature 2", "feature 3"),
                        caption=f"{aug} epoch {epoch}, 10 classes",
                    )

                for cls, hard in (("cat", 0.9), ("dog", 0.8), ("ship", 0.3)):
                    labels, scores = _pr_samples(rng, acc, hard)
                    run.add_pr_curve(f"eval/pr/{cls}", labels, scores, step=epoch)

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
        "perf/images_per_sec": 2400 + rng.gauss(0, 40),
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
        "## Embeddings\n\n"
        "Eval features in 3D, one color per class: classes separate as training goes on.\n\n"
        f"![CutMix embeddings at epoch 100](media:{ids['cutmix-s0']}/eval/embeddings@100)\n\n"
        "## Precision and recall\n\n"
        f"![Cat, CutMix at epoch 100](media:{ids['cutmix-s0']}/eval/pr/cat@100)\n\n"
        "## Distributions\n\n"
        "Logit margins split into two modes as the model learns; dashed is epoch 95.\n\n"
        f"![Logit margins, CutMix at epoch 100](media:{ids['cutmix-s0']}/eval/logit_margin@100)\n\n"
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
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{ font: 14px system-ui; margin: 12px; }}
      h3 {{ margin: 0 0 8px; }}
      .bar {{ background: #0072b2; height: 14px; width: {bar}px; border-radius: 3px; }}
    </style>
  </head>
  <body>
    <h3>Eval report: {aug}, epoch {epoch}</h3>
    <div class="bar"></div>
    <p>top-1 accuracy <b>{acc:.3f}</b></p>
    <button onclick="this.textContent = 'scripts run in a sandbox'">click me</button>
  </body>
</html>
"""


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
    ids: dict[str, str] = {}
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
            system_metrics=False,
            capture_console=False,
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
            run.add_scalar(
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
                rows = _eval_rows(model, epoch, left)
                worst = sorted(range(len(rows)), key=lambda j: rows[j]["pesq"])[:3]

                for j in worst:  # attach the enhanced audio of the three worst files
                    gain = 10 ** (-rows[j]["snr_in"] / 40)
                    clip = np.clip(clean + left * gain * noise + artifacts * 6 * blips, -1, 1)
                    rows[j]["enhanced"] = Audio(clip, sample_rate=SPEECH_RATE)

                run.add_table("eval/samples", rows, step=epoch)

        run.finish(_ended=t)
        ids[model] = run.id

    _speech_notes(root / "speech-denoise", ids)


def _speech_notes(project: Path, ids: dict[str, str]) -> None:
    """Add audio notes and a listening report to the `speech-denoise` demo."""
    run_dir = project / "runs" / ids["convtasnet"]
    notes = [
        {"id": "n1", "start": 0.42, "end": 0.78, "text": "residual hiss on the vowel"},
        {"id": "n2", "start": 1.55, "end": 1.9, "text": "tonal blip (musical noise)"},
    ]
    ann = _fs.read_json(run_dir / "annotations.json", {}) or {}
    ann["audio_notes"] = {"audio/enhanced@30": notes}
    _fs.atomic_write_json(run_dir / "annotations.json", ann)
    save_report(
        project,
        "listening-notes",
        "# Listening notes\n\n"
        "Conv-TasNet is cleanest overall; what is left is a little hiss and a few tonal blips.\n\n"
        f"![Conv-TasNet at epoch 30](media:{ids['convtasnet']}/audio/enhanced@30)\n\n"
        "## Per-file scores\n\n"
        "Sorted by PESQ in the viewer, the worst files are babble noise at low input SNR; "
        "colors show the change since the previous eval.\n\n"
        f"![Eval samples at epoch 30](media:{ids['convtasnet']}/eval/samples@30)\n",
    )


_NOISES = ["babble", "cafe", "street", "car", "white"]


def _eval_rows(model: str, epoch: int, left: float) -> list[dict[str, Any]]:
    """Return per-file scores of one eval: 40 test files, the same files at every epoch.

    Babble and low input SNR are harder; a few files get worse at the last eval.
    """
    rows = []

    for j in range(40):
        f = random.Random(f"file{j}")  # the file's own properties, the same for every model
        noise = _NOISES[j % 5]
        snr = round(f.uniform(-5, 10), 1)
        hard = {"babble": 0.5, "cafe": 0.3}.get(noise, 0.1) + (5 - snr) * 0.04 + f.random() * 0.2
        late = -(0.25 + f.random() * 0.3) if f.random() < 0.18 and epoch == 30 else 0.0
        g = random.Random(f"{model}{j}{epoch}")
        p = 1 - left
        rows.append(
            {
                "file": f"p{232 + 25 * (j % 2)}_{100 + 7 * j:03d}",
                "noise": noise,
                "snr_in": snr,
                "pesq": round(
                    max(1.02, 1.35 + (2.4 - hard * 1.4) * p + g.gauss(0, 0.03) + late), 3
                ),
                "si_sdr": round(
                    4 + snr * 0.6 + (13 - hard * 9) * p + g.gauss(0, 0.3) + late * 5, 2
                ),
                "stoi": round(min(0.99, 0.78 + (0.17 - hard * 0.08) * p + late * 0.04), 4),
            }
        )

    return rows


def _rollout(env: str, skill: float, seed: int) -> Any:
    """Return a synthetic `(T, H, W, 3)` rollout clip: a ball and a paddle that tracks it.

    Args:
        env: `"Pong"` or `"Breakout"`; Breakout adds a wall of bricks the ball clears.
        skill: 0 to 1, how closely the paddle follows the ball.
        seed: Seeds the ball's start and the paddle's jitter.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    h, w, frames = 84, 84, 48
    clip = np.zeros((frames, h, w, 3), dtype=np.uint8)
    clip[:] = (24, 26, 48) if env == "Breakout" else (60, 110, 60)
    x, y = float(rng.uniform(10, 70)), 20.0
    vx, vy = 2.2 * rng.choice([-1, 1]), 2.6
    paddle = w / 2
    bricks = rng.random((4, 12)) > 0.85 * skill  # a better policy has cleared more of the wall

    for t in range(frames):
        x, y = x + vx, y + vy

        if x < 2 or x > w - 3:
            vx, x = -vx, min(max(x, 2), w - 3)

        if y < 2:
            vy, y = -vy, 2

        if env == "Breakout" and 8 <= y < 20:
            row, col = int((y - 8) // 3), int(x // 7)

            if bricks[row, col]:
                bricks[row, col], vy = False, abs(vy)

        target = x if rng.random() < 0.3 + 0.7 * skill else paddle + rng.normal(0, 6)
        paddle += float(np.clip(target - paddle, -1 - 3 * skill, 1 + 3 * skill))

        if y > h - 8:
            vy, y = -abs(vy), h - 8

        frame = clip[t]

        if env == "Breakout":
            palette = [(200, 72, 72), (198, 108, 58), (180, 122, 48), (162, 162, 42)]

            for r, c in zip(*np.nonzero(bricks)):
                frame[8 + 3 * r : 10 + 3 * r, 7 * c + 1 : 7 * c + 6] = palette[r]

        else:
            frame[:, w // 2] = (90, 140, 90)

        p = int(np.clip(paddle, 7, w - 8))
        frame[h - 5 : h - 3, p - 7 : p + 7] = (
            (230, 230, 230) if env == "Breakout" else (92, 186, 92)
        )
        frame[int(y) - 1 : int(y) + 2, int(x) - 1 : int(x) + 2] = (240, 240, 240)

    return clip


def _ppo_runs(root: Path, base: float) -> None:
    """Write the `ppo-atari` project: Pong and Breakout, three seeds each, with rollout videos."""

    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None

    for i, (env, seed) in enumerate((e, s) for e in ("Pong", "Breakout") for s in (0, 1, 2)):
        rng = random.Random(f"{env}{seed}")
        started = base - 40 * 3600 + i * 2400
        top = 21 if env == "Pong" else 380
        run = init(
            "ppo-atari",
            name=f"{env.lower()}-s{seed}",
            dir=root,
            capture_env=False,
            system_metrics=False,
            capture_console=False,
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
            run.add_scalar(
                {
                    "charts/episode_return": ret,
                    "losses/value": 0.5 * (1 - frac) + abs(rng.gauss(0, 0.05)),
                    "losses/policy": rng.gauss(-0.01, 0.005),
                    "charts/fps": 4200 + rng.gauss(0, 120),
                },
                step=step,
                time=t,
            )

            if k % 100 == 0 and np is not None:
                clip = _rollout(env, frac, seed * 1000 + k)
                run.add_video("rollout/episode", clip, step=step, fps=15, time=t)

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
        speed: Speed-up factor; at 1.0 an `add_scalar` call happens every 0.05 s.
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
            system_metrics=False,
            capture_console=False,
            heartbeat_interval=3.0,
        )
        step = 0

        while step <= LLM_STEPS and not stop.is_set():
            point = llm_point(step, lr, seed, rng)
            run.add_scalar(point, step=step)

            if step % 500 == 0:
                run.add_scalar({"eval/loss": point["train/loss"] + 0.03}, step=step)

            step += LLM_EVERY
            time.sleep(0.05 / speed)

        run.finish("finished" if step > LLM_STEPS else "killed")
        seed += 1
