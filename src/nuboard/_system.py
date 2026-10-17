"""System scalars: CPU, memory and GPU use, sampled by a background thread.

Everything here is optional and best effort: a source that is missing (no
`/proc`, no `psutil`, no `nvidia-smi`, torch not imported) is skipped, and a
source that fails is dropped for the rest of the run. NuBoard never imports
torch; the CUDA and MPS memory of PyTorch's allocator are read only when the
training script has imported torch itself.

Scalars are logged under `system/`:

- `cpu`: `system/cpu/percent` (the whole machine, Linux or psutil) and
  `system/cpu/process_percent` (this process, in percent of one core).
- `memory`: `system/memory/percent`, `system/memory/used_gb` (the machine,
  Linux or psutil) and `system/memory/process_gb` (this process's RSS).
- `gpu`: per GPU `i` from `nvidia-smi`, `system/gpu{i}/util`,
  `system/gpu{i}/memory_gb`, `system/gpu{i}/memory_percent`,
  `system/gpu{i}/temp_c` and `system/gpu{i}/power_w`; and, from PyTorch,
  `system/torch/cuda_allocated_gb`, `system/torch/cuda_peak_gb`,
  `system/torch/mps_allocated_gb` and `system/torch/mps_driver_gb`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

GROUPS = ("cpu", "memory", "gpu")
_GB = 1024**3
_NVSMI_FIELDS = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def parse_groups(value: bool | str | Iterable[str] | None) -> tuple[str, ...]:
    """Return the groups to sample for `nb.init`'s `system_metrics` argument.

    Args:
        value: True for every group, False or None for none, or group names
            out of `"cpu"`, `"memory"` and `"gpu"`.

    Returns:
        The chosen groups, in the order of `GROUPS`.

    Raises:
        ValueError: If a name is not a known group.
    """

    if value is True:
        return GROUPS

    if not value:
        return ()

    names = {value} if isinstance(value, str) else set(value)
    unknown = names - set(GROUPS)

    if unknown:
        raise ValueError(f"unknown system_metrics groups {sorted(unknown)}; use {list(GROUPS)}")

    return tuple(g for g in GROUPS if g in names)


def _psutil() -> Any:
    """Return the psutil module if it is installed, else None."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None

    return psutil


class _CpuTimes:
    """Machine-wide CPU use from `/proc/stat`, as a percent since the last call."""

    def __init__(self) -> None:
        self.last = self._read()

    @staticmethod
    def _read() -> tuple[int, int] | None:
        """Return `(busy, total)` jiffies, or None without `/proc/stat`."""

        try:
            with open("/proc/stat", encoding="ascii") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
        except (OSError, ValueError):
            return None

        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)  # idle + iowait
        return sum(parts) - idle, sum(parts)

    def percent(self) -> float | None:
        """Return the busy percent since the previous call."""
        now = self._read()

        if now is None or self.last is None:
            return None

        busy, total = now[0] - self.last[0], now[1] - self.last[1]
        self.last = now
        return 100.0 * busy / total if total > 0 else None


def _meminfo() -> tuple[float, float] | None:
    """Return the machine's `(used_gb, percent)` from `/proc/meminfo`."""

    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            info = {line.split(":")[0]: int(line.split()[1]) for line in f if line.strip()}
    except (OSError, ValueError, IndexError):
        return None

    total, avail = info.get("MemTotal"), info.get("MemAvailable")

    if not total or avail is None:
        return None

    return (total - avail) * 1024 / _GB, 100.0 * (total - avail) / total


def _process_rss() -> float | None:
    """Return this process's resident memory in GB, from `/proc/self/statm`."""

    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            pages = int(f.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None

    return pages * os.sysconf("SC_PAGE_SIZE") / _GB


def nvidia_smi(exe: str = "nvidia-smi") -> dict[str, float]:
    """Return per-GPU utilization, memory, temperature and power from `nvidia-smi`.

    Args:
        exe: The `nvidia-smi` executable.

    Returns:
        Scalars named `gpu{i}/<field>`; fields `nvidia-smi` reports as `[N/A]`
        are left out.

    Raises:
        OSError: If `nvidia-smi` cannot run.
        subprocess.SubprocessError: If it fails or times out.
    """
    out = subprocess.run(
        [exe, f"--query-gpu={_NVSMI_FIELDS}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout
    values: dict[str, float] = {}

    for i, line in enumerate(out.strip().splitlines()):
        cells = [c.strip() for c in line.split(",")]

        def num(j: int, cells: list[str] = cells) -> float | None:
            """Return cell `j` as a float, or None when missing or not a number."""

            try:
                return float(cells[j])
            except (IndexError, ValueError):
                return None

        util, used, total, temp, power = (num(j) for j in range(5))
        row = {
            "util": util,
            "memory_gb": used / 1024 if used is not None else None,  # MiB
            "memory_percent": 100 * used / total if used is not None and total else None,
            "temp_c": temp,
            "power_w": power,
        }
        values.update({f"gpu{i}/{k}": v for k, v in row.items() if v is not None})

    return values


def torch_memory() -> dict[str, float]:
    """Return PyTorch allocator memory for CUDA and MPS, if torch is already imported.

    CUDA is read only once the script has initialized it, so sampling never
    creates a CUDA context. The values are those of this process's current
    device.
    """
    torch = sys.modules.get("torch")
    values: dict[str, float] = {}

    if torch is None:
        return values

    cuda = getattr(torch, "cuda", None)

    if cuda is not None and cuda.is_available() and cuda.is_initialized():
        values["torch/cuda_allocated_gb"] = cuda.memory_allocated() / _GB
        values["torch/cuda_peak_gb"] = cuda.max_memory_allocated() / _GB

    mps = getattr(torch, "mps", None)
    backend = getattr(getattr(torch, "backends", None), "mps", None)

    if mps is not None and backend is not None and backend.is_available():
        values["torch/mps_allocated_gb"] = mps.current_allocated_memory() / _GB
        values["torch/mps_driver_gb"] = mps.driver_allocated_memory() / _GB

    return values


class Sampler:
    """Collect the system scalars of the chosen groups.

    Args:
        groups: Groups out of `GROUPS`.
    """

    def __init__(self, groups: Iterable[str]) -> None:
        self.groups = set(groups)
        self.psutil = _psutil()
        self.cpu = _CpuTimes()
        self.proc_cpu = (time.process_time(), time.monotonic())
        self.smi = shutil.which("nvidia-smi") if "gpu" in self.groups else None
        self.broken: set[str] = set()  # sources that failed once and are skipped from then on

        if self.psutil is not None and self.cpu.last is None:
            self.psutil.cpu_percent(None)  # the first call starts psutil's own interval

    def _try(self, name: str, fn: Callable[[], dict[str, float]], out: dict[str, float]) -> None:
        """Add `fn()`'s scalars to `out`, dropping the source `name` if it raises."""

        if name in self.broken:
            return

        try:
            out.update(fn())
        except Exception:
            self.broken.add(name)

    def _cpu(self) -> dict[str, float]:
        """Return the CPU scalars."""
        out: dict[str, float] = {}
        machine = self.cpu.percent()

        if machine is None and self.psutil is not None:
            machine = float(self.psutil.cpu_percent(None))

        if machine is not None:
            out["cpu/percent"] = machine

        cpu, wall = time.process_time(), time.monotonic()
        last_cpu, last_wall = self.proc_cpu
        self.proc_cpu = (cpu, wall)

        if wall > last_wall:
            out["cpu/process_percent"] = 100.0 * (cpu - last_cpu) / (wall - last_wall)

        return out

    def _memory(self) -> dict[str, float]:
        """Return the memory scalars."""
        out: dict[str, float] = {}
        machine = _meminfo()
        rss = _process_rss()

        if self.psutil is not None:
            if machine is None:
                vm = self.psutil.virtual_memory()
                machine = (vm.total - vm.available) / _GB, float(vm.percent)

            if rss is None:
                rss = self.psutil.Process().memory_info().rss / _GB

        if machine is not None:
            out["memory/used_gb"], out["memory/percent"] = machine

        if rss is not None:
            out["memory/process_gb"] = rss

        return out

    def sample(self) -> dict[str, float]:
        """Return one sample of every chosen group, names without the `system/` prefix."""
        out: dict[str, float] = {}

        if "cpu" in self.groups:
            self._try("cpu", self._cpu, out)

        if "memory" in self.groups:
            self._try("memory", self._memory, out)

        if "gpu" in self.groups:
            if self.smi:
                self._try("nvidia-smi", lambda: nvidia_smi(self.smi or ""), out)

            self._try("torch", torch_memory, out)

        return out


class SystemMonitor:
    """A daemon thread that logs a `Sampler`'s scalars every `interval` seconds.

    Args:
        groups: Groups out of `GROUPS`.
        interval: Seconds between samples.
        emit: Called with each sample, already prefixed with `system/`.
    """

    def __init__(
        self, groups: Iterable[str], interval: float, emit: Callable[[dict[str, float]], None]
    ) -> None:
        self.sampler = Sampler(groups)
        self.interval = max(0.1, float(interval))
        self.emit = emit
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="nuboard-system", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        """Sample until stopped; the first sample comes one interval after the start."""

        while not self._stop.wait(self.interval):
            values = self.sampler.sample()

            if values:
                self.emit({f"system/{k}": v for k, v in values.items()})

    def stop(self) -> None:
        """Stop the thread and wait for it to end."""
        self._stop.set()

        if self._thread is not threading.current_thread():
            self._thread.join(timeout=15)
