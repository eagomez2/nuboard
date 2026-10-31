"""System scalars and console capture."""

from __future__ import annotations

import os
import stat
import sys
import time
import types

import pytest

import nuboard as nb
from nuboard import _env, _system
from nuboard.reader import RunReader


def test_groups_are_parsed_and_checked():
    assert _system.parse_groups(True) == ("cpu", "memory", "gpu")
    assert _system.parse_groups(False) == ()
    assert _system.parse_groups(["gpu", "cpu"]) == ("cpu", "gpu")
    assert _system.parse_groups("memory") == ("memory",)

    with pytest.raises(ValueError, match="unknown system_metrics"):
        nb.init("p", capture_env=False, system_metrics=["disk"])


def test_system_scalars_follow_the_training_step(tmp_path):
    run = nb.init("p", capture_env=False, system_metrics=["memory"], system_interval=0.05)
    run.add_scalar("loss", 1.0, step=7)
    deadline = time.monotonic() + 5

    while time.monotonic() < deadline and not run._writer.queue:  # type: ignore[union-attr]
        time.sleep(0.02)

    time.sleep(0.2)
    run.add_scalar("loss", 0.5)  # system samples do not move the step counter
    run.finish()
    r = RunReader(run.path)
    assert r.scalars("loss")[0].tolist() == [7, 8]
    names = [n for n in r.scalar_names() if n.startswith("system/")]

    if sys.platform.startswith("linux"):
        assert {"system/memory/process_gb", "system/memory/used_gb"} <= set(names)
        assert not any(n.startswith("system/cpu") for n in names)
        steps, _, values = r.scalars("system/memory/process_gb")
        assert set(steps.tolist()) <= {7, 8} and 0 < values.min() < 1000


def test_system_metrics_off_logs_nothing():
    run = nb.init("p", capture_env=False, system_metrics=False, system_interval=0.05)
    run.add_scalar("loss", 1.0)
    time.sleep(0.2)
    run.finish()
    assert RunReader(run.path).scalar_names() == ["loss"]
    assert run._system is None


def test_nvidia_smi_output_is_parsed(tmp_path):
    exe = tmp_path / "nvidia-smi"
    exe.write_text(
        "#!/bin/sh\necho 'GPU-aa, 97, 40960, 81920, 64, 412.5'\n"
        "echo 'GPU-bb, 0, 512, 81920, 31, [N/A]'\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    if os.name == "nt":  # pragma: no cover
        pytest.skip("needs a shell script")

    values = _system.nvidia_smi(str(exe))
    assert values["gpu0/util"] == 97 and values["gpu0/memory_gb"] == 40
    assert values["gpu0/memory_percent"] == 50 and values["gpu0/power_w"] == 412.5
    assert values["gpu1/temp_c"] == 31 and "gpu1/power_w" not in values

    only = _system.nvidia_smi(str(exe), {"GPU-bb": 0})  # e.g. CUDA_VISIBLE_DEVICES=1
    assert only == {
        "gpu0/util": 0,
        "gpu0/memory_gb": 0.5,
        "gpu0/memory_percent": 0.625,
        "gpu0/temp_c": 31,
    }


def test_cuda_visible_devices_are_read_like_cuda():
    gpus = [(0, "GPU-aa11"), (1, "GPU-bb22"), (2, "GPU-cc33"), (3, "GPU-cd44")]
    order = _env.cuda_order
    assert order(gpus, None) == gpus
    assert order(gpus, "2") == [(2, "GPU-cc33")]
    assert order(gpus, "3, 1") == [(3, "GPU-cd44"), (1, "GPU-bb22")]
    assert order(gpus, "GPU-bb,GPU-cd") == [(1, "GPU-bb22"), (3, "GPU-cd44")]
    assert order(gpus, "0,7,1") == [(0, "GPU-aa11")]  # an unknown GPU ends the list
    assert order(gpus, "GPU-c") == []  # an ambiguous prefix names no GPU
    assert order(gpus, "1,1") == [(1, "GPU-bb22")]
    assert order(gpus, "") == [] and order(gpus, "-1") == []


def _fake_gpus(monkeypatch, n):
    """Make `_env.gpus` report `n` visible GPUs with UUIDs `GPU-0`, `GPU-1`, ..."""
    visible = [{"device": f"cuda:{i}", "uuid": f"GPU-{i}"} for i in range(n)]
    monkeypatch.setattr(_env, "gpus", lambda: visible)


class _Device:
    """Stands in for `torch.device`, whose `str()` is the device name."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


def test_gpus_pick_devices_by_name(monkeypatch):
    _fake_gpus(monkeypatch, 4)
    assert _system.choose_gpus() == _system.choose_gpus("all")
    assert _system.choose_gpus("all").cuda == {"GPU-0": 0, "GPU-1": 1, "GPU-2": 2, "GPU-3": 3}

    one = _system.choose_gpus(["cuda:1"])
    assert one == _system.GpuChoice({"GPU-1": 1}, torch_cuda=True, mps=False)
    assert _system.choose_gpus(_Device("cuda:2")).cuda == {"GPU-2": 2}
    assert _system.choose_gpus(["CUDA", _Device("cuda:3")]).cuda == {"GPU-0": 0, "GPU-3": 3}

    monkeypatch.setattr(sys, "platform", "darwin")
    assert _system.choose_gpus("mps") == _system.GpuChoice({}, torch_cuda=False, mps=True)


def test_gpus_that_cannot_be_tracked_raise(monkeypatch):
    _fake_gpus(monkeypatch, 1)
    monkeypatch.setattr(sys, "platform", "linux")

    for bad, message in [
        ("cuda:1", "1 CUDA GPUs"),
        (["cuda:0", "tpu"], "'tpu'"),
        ("cpu", "'cpu'"),
        ("gpu0", "'gpu0'"),
        ([], "system_devices is empty"),
        ("mps", "only available on macOS"),
    ]:
        with pytest.raises(ValueError, match=message):
            _system.choose_gpus(bad)

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "3")

    with pytest.raises(ValueError, match="CUDA_VISIBLE_DEVICES='3'"):
        nb.init("p", capture_env=False, system_devices=["cuda:2"])

    # system_devices is not checked when the gpu group is off
    nb.init("p", capture_env=False, system_metrics=["cpu"], system_devices="cuda:2").finish()


def test_the_sampler_reads_only_the_chosen_gpus(monkeypatch):
    seen = []
    monkeypatch.setattr(_system, "nvidia_smi", lambda exe, devices: seen.append(devices) or {})
    monkeypatch.setattr(_system, "torch_memory", lambda cuda, mps: seen.append((cuda, mps)) or {})
    sampler = _system.Sampler(["gpu"], _system.GpuChoice({"GPU-2": 0}, torch_cuda=True, mps=False))
    sampler.smi = "nvidia-smi"
    sampler.sample()
    assert seen == [{"GPU-2": 0}, (True, False)]

    seen.clear()
    sampler.gpus = _system.GpuChoice({}, torch_cuda=False, mps=True)
    sampler.sample()
    assert seen == [(False, True)]  # nvidia-smi is not run when no CUDA GPU is chosen


def test_environment_lists_the_visible_gpus(tmp_path, monkeypatch):
    if os.name == "nt":  # pragma: no cover
        pytest.skip("needs a shell script")

    exe = tmp_path / "nvidia-smi"
    exe.write_text(
        "#!/bin/sh\n"
        "echo '0, GPU-aa, NVIDIA A100, 81920 MiB, 550.54'\n"
        "echo '1, GPU-bb, NVIDIA A100, 81920 MiB, 550.54'\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert [g["uuid"] for g in _env.gpus()] == ["GPU-aa", "GPU-bb"]

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    assert _env.gpus() == [
        {
            "device": "cuda:0",
            "index": 1,
            "uuid": "GPU-bb",
            "name": "NVIDIA A100",
            "memory": "81920 MiB",
            "driver": "550.54",
        }
    ]


def test_torch_memory_needs_torch_imported_and_cuda_initialized(monkeypatch):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert _system.torch_memory() == {}

    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        is_initialized=lambda: False,
        memory_allocated=lambda: 2 * 1024**3,
        max_memory_allocated=lambda: 3 * 1024**3,
    )
    mps = types.SimpleNamespace(
        current_allocated_memory=lambda: 1024**3, driver_allocated_memory=lambda: 2 * 1024**3
    )
    backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    fake = types.SimpleNamespace(cuda=cuda, mps=mps, backends=backends)
    monkeypatch.setitem(sys.modules, "torch", fake)
    assert _system.torch_memory() == {"torch/mps_allocated_gb": 1, "torch/mps_driver_gb": 2}

    cuda.is_initialized = lambda: True
    backends.mps.is_available = lambda: False
    assert _system.torch_memory() == {"torch/cuda_allocated_gb": 2, "torch/cuda_peak_gb": 3}


def test_a_failing_source_is_dropped(monkeypatch):
    sampler = _system.Sampler(["gpu"], _system.GpuChoice({"GPU-0": 0}))
    sampler.smi = "nvidia-smi"
    calls = []

    def broken(exe, devices):
        calls.append(exe)
        raise OSError("gone")

    monkeypatch.setattr(_system, "nvidia_smi", broken)
    sampler.sample()
    sampler.sample()
    assert calls == ["nvidia-smi"] and "nvidia-smi" in sampler.broken


def test_console_output_is_captured_and_streams_restored(capsys):
    out, err = sys.stdout, sys.stderr
    run = nb.init("p", capture_env=False, system_metrics=False)
    run.add_scalar("loss", 1.0)
    print("hello from the script")
    print("a warning", file=sys.stderr)
    run.finish()
    assert (sys.stdout, sys.stderr) == (out, err)
    print("after finish")
    log = (run.path / "files" / "output.log").read_text("utf-8")
    assert log.startswith("[nuboard: session 0, ")
    assert "hello from the script\n" in log and "a warning\n" in log
    assert "after finish" not in log
    assert "hello from the script" in capsys.readouterr().out  # still printed

    again = nb.init("p", run_id=run.id, resume="must", capture_env=False, system_metrics=False)
    print("resumed")
    again.finish()
    log = (run.path / "files" / "output.log").read_text("utf-8")
    assert log.index("hello") < log.index("[nuboard: session 1") < log.index("resumed")


def test_console_capture_can_be_turned_off():
    run = nb.init("p", capture_env=False, system_metrics=False, capture_console=False)
    print("not captured")
    run.finish()
    assert not (run.path / "files" / "output.log").exists()


def test_a_crash_traceback_lands_in_the_console_log(tmp_path):
    import subprocess

    script = (
        "import nuboard as nb\nrun = nb.init('p', capture_env=False)\nprint('training')\n1 / 0\n"
    )
    env = {**os.environ, "NUBOARD_DIR": str(tmp_path)}
    subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, check=False)
    (log,) = tmp_path.glob("p/runs/*/files/output.log")
    text = log.read_text("utf-8")
    assert "training\n" in text and "ZeroDivisionError" in text


def test_a_quiet_script_leaves_no_console_log():
    run = nb.init("p", capture_env=False, system_metrics=False)
    run.finish()
    assert not (run.path / "files" / "output.log").exists()
