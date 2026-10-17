# Runs

A run is one execution of your training script. `nb.init` opens it and returns
a `Run`, and everything you log goes through that object. The run's metrics,
media, config and environment end up in one folder.

## `nb.init`

```python
nb.init(
    project=None,
    *,
    name=None,
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
) -> Run
```

Starts a run, or resumes one, in `<dir>/<project>/runs/<run_id>/`. The run is
also a context manager: leaving the `with` block finishes it, and an exception
marks it crashed.

**Parameters**

- **project** (*str*, optional): the project folder. A `/` nests projects,
  as in `"team/llm"`. Defaults to `"default"`.
- **name** (*str*, optional): a short name for the run, shown in the viewer and
  used in the run id. Defaults to `"run"`.
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
  Defaults to `<YYYYMMDD-HHMM>_<name>_<6 random characters>`.
- **resume** (*"must" or "auto"*, optional): what to do when `run_id` already
  exists. See [Resume and fork](#resume-and-fork).
- **fork_from** (*(run_id, step)*, optional): start from a copy of another
  run's history up to `step`.
- **all_ranks** (*bool*): log on every rank, not only rank 0.
- **capture_env** (*bool*): record git, installed packages and GPUs.
- **compact** (*bool*): write `data.parquet` at finish, when PyArrow is
  installed, so the viewer opens the run faster.
- **flush_interval** (*float*): seconds between background writes.
- **heartbeat_interval** (*float*): seconds between liveness updates. A run
  whose heartbeat is two minutes old shows as **lost**.

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

**Example**

```python
import nuboard as nb
from dataclasses import dataclass


@dataclass
class Config:
    lr: float = 3e-4
    batch_size: int = 64
    layers: int = 4


with nb.init("api-tour", name="init", config=Config(), tags=["docs"]) as run:
    print(run.id)  # e.g. 20261017-0930_init_k3x9q2
    print(run.path)  # experiments/api-tour/runs/20261017-0930_init_k3x9q2
```

## `run.log`

```python
run.log(data, step=None, *, time=None, all_ranks=None)
```

Logs a dict of numbers at one step. This is TensorBoard's `add_scalar` and
`add_scalars` in one call.

**Parameters**

- **data** (*dict*): metric names mapped to numbers. Nested dicts are
  flattened with `/`, so `{"train": {"loss": 0.4}}` logs `train/loss`. Values
  can be Python numbers, bools, NumPy scalars or 0-d tensors. They are
  converted to float on the background thread, so passing a CUDA tensor does
  not sync on the calling thread. Strings are skipped with a one-time warning;
  use [`add_text`](media.md#add_text) for those.
- **step** (*int*, optional): the training step. Defaults to one more than
  the previous call's step. Pass it explicitly when you log several dicts for
  the same step, such as train and eval metrics.
- **time** (*float*, optional): a Unix timestamp. Defaults to now.
- **all_ranks** (*bool*, optional): log from this rank even if it is not rank
  0, overriding `nb.init`'s setting for this call.

**Stored as** one columnar frame per flush in the event log: a step, a time
and a float64 per metric. A 50-metric dict costs a few microseconds to log and
about 8 bytes per value on disk.

**In the viewer** each key is a line chart on the Charts page, with one line
per run, grouped in sections by the key's prefix. NaN and infinite values are
stored as they are and flagged on the chart and by the
[health alerts](../guide/alerts.md).

**Example**

```python
import math

import nuboard as nb

run = nb.init("api-tour", name="scalars")

for step in range(500):
    lr = 1e-3 * min(1, step / 50) * 0.5 * (1 + math.cos(math.pi * step / 500))
    loss = 2.2 * math.exp(-step / 120) + 0.25 + 0.04 * math.sin(step / 7)
    run.log({"train": {"loss": loss, "lr": lr}}, step=step)

    if step % 50 == 0:
        run.log({"eval/loss": loss + 0.08, "eval/acc": 1 - loss / 3}, step=step)

run.finish()
```

**Expected result**

![Charts for train/loss, train/lr, eval/loss and eval/acc](../assets/api/scalars.png)

## `run.summary`

A dict of the run's metrics so far. Each one maps to `last`, `step`, `min`,
`max`, `count` and `nonfinite`. It is empty until something has been logged.

```python
run.summary["train/loss"]["min"]
```

## `run.add_file`

```python
run.add_file(path, name=None) -> Path | None
```

Copies a file or folder into the run's `files/` folder. Use it for config
files in whatever format they come in (YAML, TOML, Hydra's `.hydra/` folder),
or any other file worth keeping with the run.

**Parameters**

- **path** (*str or Path*): the file or folder. A folder is copied
  recursively.
- **name** (*str*, optional): where to put it inside `files/`, such as
  `"cfg/train.yaml"`. Subfolders are created. Defaults to the base name of
  `path`.

**Returns** the destination path, or None on ranks other than 0, which do
not copy.

**In the viewer** the run details list every file in `files/`, and Compare
shows a diff of each file between runs.

```python
run.add_file("config.yaml")
run.add_file(".hydra", "hydra")
```

## `run.add_artifact`

```python
run.add_artifact(name, path, *, type=None, metadata=None) -> Artifact
```

Copies a file or folder into a new version of an artifact, in
`<project>/artifacts/<name>/v<N>/`, and records this run as its producer.
Versions are numbered automatically and created atomically.

**Parameters**

- **name** (*str*): the artifact's name, such as `"model"`.
- **path** (*str or Path*): the file or folder to copy.
- **type** (*str*, optional): a free-form type, such as `"checkpoint"` or
  `"dataset"`.
- **metadata** (*dict*, optional): extra data for the manifest, such as the
  step or a score.

**Returns** an `Artifact` with `ref` (such as `"model:v3"`), `files` (the
folder holding the copy) and `manifest` (a sha256 and size per file, the type,
the metadata and the producing run).

The copy happens on the calling thread, so avoid it inside a hot loop with
large checkpoints.

## `run.use_artifact`

```python
run.use_artifact(ref) -> Artifact
```

Finds an artifact version and records it as an input of this run, so the
[Artifacts page](../guide/artifacts.md) can show which runs used which data.

- **ref** (*str*): `"name"` or `"name:latest"` for the newest version, or
  `"name:v2"` for a given one.

```python
import nuboard as nb

with nb.init("api-tour", name="artifacts") as run:
    with open("labels.txt", "w") as f:
        f.write("cat\ndog\n")

    v = run.add_artifact("labels", "labels.txt", type="dataset", metadata={"classes": 2})
    print(v.ref)  # labels:v1, then labels:v2, ...
    print(run.use_artifact("labels:latest").files)
```

## `run.flush`

```python
run.flush()
```

Waits until everything logged so far is on disk. You rarely need it: the
background thread writes every `flush_interval` seconds, and `finish` flushes.

## `run.finish`

```python
run.finish(status="finished", *, exit_code=0, error=None)
```

Flushes, writes an end frame, records the status, exit code and end time in
`run.json`, and compacts the logs into `data.parquet` when PyArrow is
installed. It is safe to call twice.

- It is called at interpreter exit, and when a `with` block ends.
- An uncaught exception marks the run `crashed` and stores the traceback as
  `exit.error`. `KeyboardInterrupt` marks it `killed`.
- If the process is killed outright (SIGKILL, the OOM killer), everything
  flushed so far stays readable. The run keeps the status `running`, and the
  viewer shows it as **lost** once its heartbeat is two minutes old.

## Resume and fork

```python
# continue a run, such as after a restart from a checkpoint
run = nb.init("api-tour", run_id="20261017-0930_init_k3x9q2", resume="must")
run = nb.init("api-tour", run_id=my_id, resume="auto")  # create it if missing

# a new run whose history is a copy of another run's, up to step 5000
run = nb.init("api-tour", name="lower-lr", fork_from=("20261017-0930_init_k3x9q2", 5000))
```

- **resume="must"** continues the run and fails if it does not exist.
  **resume="auto"** creates it when it is missing, which suits jobs that may
  be preempted.
- A resumed run writes a new session file, `events.r0.s1.log`, next to the
  earlier ones. When you restart from a checkpoint at step 5000, the points the
  earlier session logged at step 5000 or later are hidden in favor of the new
  ones, metric by metric.
- A fork copies the parent's points up to the fork step into the new run's
  folder, so the new folder never refers to anything outside it. The viewer
  shows the fork's parent in the run details.

## Environment variables

| Variable | Effect |
| --- | --- |
| `NUBOARD_DIR` | The default root folder for `nb.init`, `nuboard up` and `nuboard ls`. |
| `NUBOARD_CACHE_DIR` | Where the viewer keeps its catalog cache. |
| `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, `SLURM_*`, `OMPI_COMM_WORLD_*` | Rank detection; see [Distributed training](../guide/distributed.md). |
