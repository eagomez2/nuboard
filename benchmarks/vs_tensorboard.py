r"""Compare nuboard with TensorBoard writers on the costs that matter during training.

    uv run --with tensorboardX --with tensorboard --with torch \\
        python benchmarks/vs_tensorboard.py

Writers compared: nuboard, tensorboardX and PyTorch's `torch.utils.tensorboard`
(each one that is installed). Every case runs in a fresh subprocess, so one
writer's background threads never slow another down, and each case is repeated
and its median kept. Results go to `docs/assets/benchmarks/vs_tensorboard.json`,
which the charts of the docs' Benchmarks page read directly.

Cases:

- `scalars_us`: training-thread time to log 50 scalars at one step.
- `slowdown_pct`: throughput lost by a training loop whose steps are 1 ms of
  Python work (so it competes for the GIL with any writer thread) when it logs
  50 scalars every step.
- `image_ms`: training-thread time to log one 256x256 RGB uint8 image.
- `write_1m_s`: time to log 1M scalar points (100k steps x 10 metrics) and close
  the writer, so everything is on disk.
- `read_1m_s`: time to read those 1M points back (nuboard's `RunReader` on the
  event log; TensorBoard's `EventAccumulator` keeping every point).
- `disk_1m_mb`: size on disk of those 1M points.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUT = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "assets"
    / "benchmarks"
    / "vs_tensorboard.json"
)
WRITERS = ("nuboard", "tensorboardX", "torch")
CASES = ("scalars_us", "slowdown_pct", "image_ms", "write_1m_s", "read_1m_s", "disk_1m_mb")
REPEAT = {"scalars_us": 3, "slowdown_pct": 3, "image_ms": 3}
SCALARS = {f"train/m{i:02d}": float(i) for i in range(50)}


# -- writers: one small adapter per library ----------------------------------------
class Adapter:
    """Open a writer in `root` and log through one interface."""

    def __init__(self, writer: str, root: Path) -> None:
        self.kind = writer

        if writer == "nuboard":
            import nuboard as nb

            self.run = nb.init(
                "bench",
                dir=root,
                capture_env=False,
                compact=False,
                system_metrics=False,
                capture_console=False,
            )
            self.path = self.run.path
        else:
            if writer == "tensorboardX":
                from tensorboardX import SummaryWriter
            else:
                from torch.utils.tensorboard import SummaryWriter

            self.path = root / "tb"
            self.w = SummaryWriter(str(self.path))

    def scalars(self, data: dict[str, float], step: int) -> None:
        """Log `data` at `step`, one call per scalar for TensorBoard."""

        if self.kind == "nuboard":
            self.run.add_scalar(data, step=step)
        else:
            for k, v in data.items():  # TensorBoard logs one scalar per call
                self.w.add_scalar(k, v, step)

    def image(self, img, step: int) -> None:  # type: ignore[no-untyped-def]
        """Log an HxWxC uint8 image at `step`."""

        if self.kind == "nuboard":
            self.run.add_image("img", img, step=step)
        else:
            self.w.add_image("img", img, step, dataformats="HWC")

    def close(self) -> None:
        """Flush and close the writer."""

        if self.kind == "nuboard":
            self.run.finish()
        else:
            self.w.close()


def _busy(seconds: float) -> None:
    """Stand-in for a training step: Python work that holds the GIL."""
    end = time.perf_counter() + seconds

    while time.perf_counter() < end:
        pass


# -- cases --------------------------------------------------------------------------
def case_scalars_us(writer: str, root: Path) -> float:
    """Microseconds on the training thread to log 50 scalars."""
    a = Adapter(writer, root)
    n = 20_000 if writer == "nuboard" else 1_000

    for s in range(100):  # warm up
        a.scalars(SCALARS, s)

    t0 = time.perf_counter()

    for s in range(100, 100 + n):
        a.scalars(SCALARS, s)

    dt = (time.perf_counter() - t0) / n
    a.close()
    return dt * 1e6


def case_slowdown_pct(writer: str, root: Path) -> float:
    """Percent of throughput lost by a 1 ms-step loop that logs 50 scalars per step."""
    n, step = 2_000, 1e-3

    def loop(log) -> float:  # type: ignore[no-untyped-def]
        t0 = time.perf_counter()

        for s in range(n):
            _busy(step)
            log(s)

        return time.perf_counter() - t0

    base = loop(lambda s: None)
    a = Adapter(writer, root)
    with_log = loop(lambda s: a.scalars(SCALARS, s))
    a.close()
    return max(0.0, (1 - base / with_log) * 100)


def case_image_ms(writer: str, root: Path) -> float:
    """Milliseconds on the training thread to log a 256x256 RGB image."""
    import numpy as np

    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    a = Adapter(writer, root)
    n = 100
    t0 = time.perf_counter()

    for s in range(n):
        a.image(img, s)

    dt = (time.perf_counter() - t0) / n
    a.close()
    return dt * 1e3


def case_write_1m(writer: str, root: Path) -> dict[str, float]:
    """Write 1M points, then read them back; times in seconds and size in MB."""
    a = Adapter(writer, root)
    t0 = time.perf_counter()

    for s in range(100_000):
        a.scalars({f"m{i}": s * 0.5 + i for i in range(10)}, s)

    a.close()
    write = time.perf_counter() - t0
    size = sum(p.stat().st_size for p in Path(a.path).rglob("*") if p.is_file())
    t0 = time.perf_counter()

    if writer == "nuboard":
        from nuboard.reader import RunReader

        reader = RunReader(a.path)
        reader.refresh()
        total = sum(len(v[0]) for v in reader.all_scalars().values())
    else:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

        acc = EventAccumulator(str(a.path), size_guidance={"scalars": 0})
        acc.Reload()
        total = sum(len(acc.Scalars(t)) for t in acc.Tags()["scalars"])

    read = time.perf_counter() - t0
    assert total == 1_000_000, total
    return {"write_1m_s": write, "read_1m_s": read, "disk_1m_mb": size / 1e6}


def _one(writer: str, case: str) -> None:
    """Run one case in this process and print its result as JSON."""
    root = Path(tempfile.mkdtemp())

    try:
        if case == "write_1m":
            print(json.dumps(case_write_1m(writer, root)))
        else:
            print(json.dumps({case: globals()[f"case_{case}"](writer, root)}))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _available(writer: str) -> bool:
    mod = {"nuboard": "nuboard", "tensorboardX": "tensorboardX", "torch": "torch"}[writer]
    code = f"import {mod}" + ("; import torch.utils.tensorboard" if writer == "torch" else "")
    return subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


def _versions() -> dict[str, str]:
    from importlib import metadata

    out = {"python": platform.python_version(), "platform": platform.platform()}

    for name in ("nuboard", "tensorboardX", "torch", "tensorboard", "numpy"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass

    return out


def main() -> None:
    """Run every case for every installed writer and save the results."""

    if len(sys.argv) == 3:  # a child process
        _one(sys.argv[1], sys.argv[2])
        return

    writers = [w for w in WRITERS if _available(w)]
    results: dict[str, dict[str, float]] = {w: {} for w in writers}

    for writer in writers:
        for case in ("scalars_us", "slowdown_pct", "image_ms", "write_1m"):
            runs = []

            for _ in range(REPEAT.get(case, 1)):
                out = subprocess.run(
                    [sys.executable, __file__, writer, case],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                runs.append(json.loads(out.stdout.strip().splitlines()[-1]))

            for key in runs[0]:
                results[writer][key] = statistics.median(r[key] for r in runs)

            print(writer, case, {k: round(v, 3) for k, v in results[writer].items()}, flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"machine": {**_versions(), "cpus": os.cpu_count()}, "results": results}, indent=2
        )
        + "\n"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
