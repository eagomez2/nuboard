# `nb.init`

```python
nb.init(
    project=None,
    *,
    run_name=None,
    config=None,
    dir=None,
    tags=None,
    notes=None,
    group=None,
    run_id=None,
    resume=None,
    fork_from=None,
    all_ranks=False,
    capture_env=True,
    compact=True,
    flush_interval=1.0,
    heartbeat_interval=10.0,
    system_metrics=True,
    system_interval=30.0,
    capture_console=True,
) -> Run
```

Starts a run, or resumes one, in `<dir>/<project>/runs/<run_id>/`. The run is
also a context manager: leaving the `with` block finishes it, and an exception
marks it crashed.

**Parameters**

- **project** (*str*, optional): the project folder. A `/` nests projects,
  as in `"team/llm"`. Defaults to `"default"`.
- **run_name** (*str*, optional): a human-readable label for the run, shown in
  the viewer. It is not part of the run id, and many runs can share it.
  Defaults to `"run"`.
- **config** (optional): the hyperparameters. This can be a dict, a dataclass, an
  `argparse.Namespace`, an OmegaConf config, or any object with `to_dict()`.
  Nested values are kept nested, and the viewer flattens them with `.`
  (`model.width`). The config is stored in `run.json`.
- **dir** (*str or Path*, optional): the root folder. Defaults to
  `$NUBOARD_DIR` or `./experiments`.
- **tags** (*list of str*, optional): tags for the Runs table and the
  [query language](../reference/query.md) (`tag:baseline`).
- **notes** (*str*, optional): free text, editable later in the viewer.
- **group** (*str*, optional): a group name for runs that belong together,
  such as the trials of a [sweep](../guide/sweeps.md).
- **run_id** (*str*, optional): the run's id, which is also its folder name.
  Defaults to `<YYYYMMDDTHHMM>-<8 random hex digits>`, such as
  `20261001T1833-48ad8bb2`. You can still pass your own.
- **resume** (*"must" or "auto"*, optional): what to do when `run_id` already
  exists. See [Resume and fork](init.md#resume-and-fork).
- **fork_from** (*(run_id, step)*, optional): start from a copy of another
  run's history up to `step`.
- **all_ranks** (*bool*): log on every rank, not only rank 0.
- **capture_env** (*bool*): record git, installed packages and GPUs.
- **compact** (*bool*): write `data.parquet` at finish, when PyArrow is
  installed, so the viewer opens the run faster.
- **flush_interval** (*float*): seconds between background writes.
- **heartbeat_interval** (*float*): seconds between liveness updates. A run
  whose heartbeat is two minutes old shows as **lost**.
- **system_metrics** (*bool or list of str*): log CPU, memory and GPU use as
  `system/` scalars. True logs all three groups, False none, and a list picks
  groups out of `"cpu"`, `"memory"` and `"gpu"`, such as
  `system_metrics=["gpu"]` to skip CPU and RAM. See
  [System scalars](init.md#system-scalars).
- **system_interval** (*float*): seconds between system samples. Defaults to
  30, which is about 14,000 points per scalar over a 5-day run.
- **capture_console** (*bool*): copy what the script prints to stdout and
  stderr into `files/output.log`, shown as **Console** in the run details. See
  [Console output](init.md#console-output).

**What it records**

- The config, name, tags, notes, group, host, Python version, platform, start
  time and status, in `run.json`.
- The git commit, branch, remote and dirty flag, with `git diff HEAD` as
  `files/git.patch`. This is skipped outside a repository.
- Installed packages as `files/requirements.txt`, read from package metadata
  without running pip.
- The command line as `files/command.txt`, and GPUs via `nvidia-smi` when it
  is present.
- The rank and world size, read from `torchrun`, SLURM or MPI variables.
- CPU, memory and GPU use every 30 seconds, and everything the script prints.
  Both are described below.

**Example**

```python
import nuboard as nb
from dataclasses import dataclass


@dataclass
class Config:
    lr: float = 3e-4
    batch_size: int = 64
    layers: int = 4


with nb.init("api-tour", run_name="init", config=Config(), tags=["docs"]) as run:
    print(run.id)  # e.g. 20261017T0930-c589c96e
    print(run.path)  # experiments/api-tour/runs/20261017T0930-c589c96e
```


## Resume and fork

```python
# continue a run, such as after a restart from a checkpoint
run = nb.init("api-tour", run_id="20261017T0930-c589c96e", resume="must")
run = nb.init("api-tour", run_id=my_id, resume="auto")  # create it if missing

# a new run whose history is a copy of another run's, up to step 5000
run = nb.init("api-tour", run_name="lower-lr", fork_from=("20261017T0930-c589c96e", 5000))
```

- **resume="must"** continues the run and fails if it does not exist.
  **resume="auto"** creates it when it is missing, which suits jobs that may
  be preempted.
- A resumed run writes a new session file, `events.r0.s1.log`, next to the
  earlier ones. When you restart from a checkpoint at step 5000, the points the
  earlier session logged at step 5000 or later are hidden in favor of the new
  ones, scalar by scalar.
- A fork copies the parent's points up to the fork step into the new run's
  folder, so the new folder never refers to anything outside it. The viewer
  shows the fork's parent in the run details.


## System scalars

A background thread samples the machine every `system_interval` seconds and
logs what it finds as scalars under `system/`, at the step of the latest
`add_scalar` call. They are drawn in a **system** section of the Charts page,
against the step or, with the x axis set to wall time, against time. Sampling runs
on its own thread, so the training loop never waits for it, and it imports
nothing the script did not import already.

| Group | Scalars | Source |
| --- | --- | --- |
| `cpu` | `system/cpu/percent` (the whole machine), `system/cpu/process_percent` (this process, 100 is one full core) | `/proc` on Linux, `psutil` elsewhere if it is installed |
| `memory` | `system/memory/used_gb`, `system/memory/percent` (the machine's RAM), `system/memory/process_gb` (this process's resident memory) | `/proc` on Linux, `psutil` elsewhere if it is installed |
| `gpu` | per GPU `i`: `system/gpu{i}/util`, `memory_gb`, `memory_percent`, `temp_c`, `power_w` | `nvidia-smi`, when it is on the `PATH` |
| `gpu` | `system/torch/cuda_allocated_gb`, `system/torch/cuda_peak_gb` | PyTorch's CUDA allocator, once the script has used CUDA |
| `gpu` | `system/torch/mps_allocated_gb`, `system/torch/mps_driver_gb` | PyTorch's MPS allocator on Apple silicon |

What each machine gives:

- **NVIDIA GPUs** give everything in the table. `nvidia-smi` reports every GPU
  of the machine, and PyTorch's allocator only the current device of the
  process that logs.
- **CPU only** gives the `cpu` and `memory` groups. The `gpu` group is skipped
  quietly.
- **Apple silicon (MPS)** gives the `cpu` and `memory` groups when `psutil` is
  installed (`pip install psutil`; NuBoard does not require it), and the MPS
  allocator's memory when the script has imported torch. macOS has no
  per-GPU utilization or temperature to read without administrator rights,
  so there are none.
- **Other GPUs** (AMD, Intel) give the `cpu` and `memory` groups.

PyTorch is never imported by NuBoard: the `system/torch/*` scalars appear only
when your script has imported it, and CUDA is read only after your script has
initialized it, so sampling never creates a CUDA context. A source that fails
once, such as a `nvidia-smi` that hangs, is dropped for the rest of the run.

In distributed training, the process with `LOCAL_RANK` 0 on each machine
samples its machine, so a job on 4 machines logs 4 sets, each in its rank's
event log. The viewer shows rank 0's by default and the others in the rank
picker.

```python
nb.init("llm", system_metrics=False)  # none
nb.init("llm", system_metrics=["gpu"])  # GPU only: skip CPU and RAM
nb.init("llm", system_interval=120)  # one sample every two minutes
```


## Console output

With `capture_console=True`, the default, everything the script writes to
`sys.stdout` and `sys.stderr` is also written to `files/output.log`: prints,
`logging` output, warnings, tqdm progress bars and the traceback of a crash.
The script's own output is unchanged. The viewer shows the log as **Console**
in the run details, from its end, as a terminal would, with progress bars
redrawn on one line and color codes removed.

- The file is created on the first output, so a script that prints nothing
  leaves none. A resumed run appends to it, after a
  `[nuboard: session 1, <time>]` line.
- Only Python-level output is captured. Output that a C extension or a
  subprocess writes directly to the file descriptors, such as NCCL's or
  CUDA's own messages, is not.
- The log stops growing at 64 MB, with a note at its end. The viewer shows its
  last 2 MB.
- In distributed training only rank 0 captures its output, unless
  `all_ranks=True`, in which case rank N writes `files/output.rN.log`.


## Environment variables

| Variable | Effect |
| --- | --- |
| `NUBOARD_DIR` | The default root folder for `nb.init`, `nuboard up` and `nuboard ls`. |
| `NUBOARD_CACHE_DIR` | Where the viewer keeps its catalog cache. |
| `NUBOARD_DATA_DIR` | This machine's data folder; references to datasets inside it work on every machine that sets it. See [Data on several machines](../guide/artifacts.md#data-on-several-machines). |
| `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, `SLURM_*`, `OMPI_COMM_WORLD_*` | Rank detection; see [Distributed training](../guide/distributed.md). |
