"""A real (tiny) training loop: softmax regression on synthetic data in NumPy.

Runs a small learning-rate sweep with two seeds each, so the viewer has
something to group: open it with ``nuboard up experiments`` and type
``where project = numpy-sweep group by config.lr`` in the query bar.

    pip install "nuboard[viewer]"   # NumPy comes with the viewer extra
    python examples/train_numpy.py
"""

from __future__ import annotations

import numpy as np

import nuboard as nm


def make_data(rng: np.random.Generator, n: int = 4000, d: int = 20, k: int = 5):
    centers = rng.normal(0, 2.0, (k, d))
    y = rng.integers(0, k, n)
    x = centers[y] + rng.normal(0, 3.0, (n, d))
    return x[: n * 3 // 4], y[: n * 3 // 4], x[n * 3 // 4 :], y[n * 3 // 4 :]


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def train(lr: float, seed: int, epochs: int = 30, batch: int = 64) -> None:
    rng = np.random.default_rng(seed)
    xtr, ytr, xva, yva = make_data(np.random.default_rng(0))
    k = int(ytr.max()) + 1
    w = rng.normal(0, 0.01, (xtr.shape[1], k))
    config = {
        "lr": lr,
        "seed": seed,
        "epochs": epochs,
        "batch": batch,
        "model": "softmax-regression",
    }
    with nm.init(
        "numpy-sweep", name=f"lr{lr:g}-s{seed}", config=config, tags=["example", "sweep"]
    ) as run:
        step = 0
        for epoch in range(epochs):
            order = rng.permutation(len(xtr))
            for i in range(0, len(order), batch):
                idx = order[i : i + batch]
                p = softmax(xtr[idx] @ w)
                loss = -np.log(p[np.arange(len(idx)), ytr[idx]] + 1e-12).mean()
                p[np.arange(len(idx)), ytr[idx]] -= 1
                grad = xtr[idx].T @ p / len(idx)
                w -= lr * grad
                run.log({"train/loss": loss, "train/grad_norm": np.linalg.norm(grad)}, step=step)
                step += 1
            pv = softmax(xva @ w)
            run.log(
                {
                    "val/loss": -np.log(pv[np.arange(len(yva)), yva] + 1e-12).mean(),
                    "val/acc": (pv.argmax(1) == yva).mean(),
                    "epoch": epoch,
                },
                step=step,
            )
            # A tiny image: the weight matrix, scaled to [0, 1].
            if epoch % 10 == 0 or epoch == epochs - 1:
                img = (w - w.min()) / (np.ptp(w) + 1e-12)
                run.log_image("weights", np.kron(img, np.ones((8, 8))), step=step)


if __name__ == "__main__":
    for lr in (0.003, 0.01, 0.03):
        for seed in (0, 1):
            train(lr, seed)
    print("Done. View with: nuboard up experiments")
