"""The smallest useful example: log a fake training curve.

python examples/quickstart.py
nuboard up experiments
"""

import math
import random

import nuboard as nb

config = {"lr": 3e-4, "batch_size": 64, "model": {"layers": 4, "width": 256}}

with nb.init("quickstart", name="baseline", config=config, tags=["example"]) as run:
    for step in range(2000):
        loss = 2.0 * math.exp(-step / 400) + 0.3 + random.gauss(0, 0.03)
        run.add_scalar({"train/loss": loss, "train/lr": config["lr"]}, step=step)

        if step % 200 == 0:
            run.add_scalar({"eval/loss": loss + 0.05}, step=step)
            run.add_text("samples/text", f"step {step}: the loss is {loss:.3f}", step=step)

print(f"Logged to {run.path}")
