# Logging from Python

This guide is a tour of logging; the [Python API](../api/index.md) describes
every call in detail.

```python
import nuboard as nb

run = nb.init("project", run_name="baseline", config=cfg)  # also a context manager
ds = run.use_artifact("dataset:v2")
run.add_scalar({"loss": loss, "lr": lr}, step=step)  # non-blocking
run.add_image("samples/recon", img, step=step)
run.add_text("samples/gen", text, step=step)
run.add_audio("samples/speech", wav, step=step, sample_rate=16000)
run.add_figure("eval/confusion", fig, step=step)  # Plotly, Altair/Vega-Lite, Bokeh, matplotlib
run.add_html("eval/graph", html, step=step)
run.add_artifact("model", "ckpt/", type="checkpoint", metadata={"step": step})
run.finish()  # also on exit and on crash
```

## `nb.init`

```python
nb.init(
    project=None,           # folder name (may be nested: "team/llm"); default "default"
    *,
    run_name=None,          # label shown in the viewer (not part of the run id)
    config=None,            # dict, dataclass, argparse.Namespace, OmegaConf, or obj.to_dict()
    dir=None,               # root folder; default $NUBOARD_DIR or ./experiments
    tags=None, notes=None, group=None,
    run_id=None, resume=None,   # resume="must" | "auto"
    job=None,               # join run_id as a second job, such as "eval"
    fork_from=None,         # (run_id, step)
    capture_env=True,       # git, pip freeze, GPUs, command line
    code_dir=None,          # folder of the training code, if the script is not
    compact=True,           # write data.parquet at finish if PyArrow is installed
    flush_interval=1.0,     # seconds between background writes
    heartbeat_interval=10.0,
)
```

`init` creates `<dir>/<project>/runs/<YYYYMMDDTHHMM>-<hash>/` (for example
`20261001T1833-48ad8bb2`, with 8 random hex digits) and
records:

- the config (in `run.json`),
- git commit, branch, remote (without credentials), dirty flag, whether the
  commit is pushed and how many untracked files there are, plus
  `git diff HEAD` as `files/git.patch` (skipped outside a repository),
- installed packages as `files/requirements.txt` (read from package metadata,
  no subprocess),
- the command line (`files/command.txt`), host, Python, platform and GPUs
  (via `nvidia-smi` if present),
- rank and world size (see [Distributed training](distributed.md)).

Pass `capture_env=False` to skip git, packages and GPUs. See
[Reproducibility](reproducibility.md) for how to replay a run from these, which
repository is recorded, and what is not covered.

### Config files

The config passed to `init` is stored in `run.json`, whatever it came from. To
also keep the config files themselves, in whatever format they are, attach them
with `add_file`:

```python
run.add_file("config.yaml")  # files/config.yaml
run.add_file("train.toml", "cfg/train.toml")
run.add_file(".hydra", "hydra")  # Hydra's folder, copied recursively
```

`add_file` copies any file or folder into the run's `files/` folder, under its
base name or the relative name you give, and returns the destination path.
Only rank 0 copies. The viewer lists these files in the run details and diffs
them between runs in Compare.

## `run.add_scalar`

```python
run.add_scalar(key, value=None, step=None, *, low=None, high=None, time=None)
```

- `run.add_scalar("train/loss", 0.42)` logs one scalar, and
  `run.add_scalar({"train/loss": 0.42, "train/lr": 3e-4})` several at the same
  step. Nested dicts are flattened with `/` (`{"train": {"loss": 1}}` logs
  `train/loss`). Values may be Python numbers, bools, NumPy scalars or 0-d
  tensors; conversion to float happens on the background thread. Strings are
  skipped with a one-time warning; use `add_text`.
- `step` defaults to one more than the previous call's step. Pass it
  explicitly when you log several times per step.
- `low` and `high` (optional, together) give a range around the value, such
  as mean ± std over an epoch's batches; the chart shades it around the line.
  Leave them out for a plain scalar.
- `time` overrides the timestamp (useful when importing data).
- NaN and ±Inf are stored as they are; the viewer flags them.

`add_scalar()` only appends to a deque (a few microseconds for a 50-scalar
dict). A background thread wakes every `flush_interval` seconds, encodes the
batch into one columnar frame and appends it to the event log. Call
`run.flush()` if you need everything on disk at a given point (rarely needed).
See [`add_scalar`](../api/add_scalar.md) for the full reference.

To compare a scalar against a fixed reference, such as the score of the
unprocessed input, set it once with
[`add_scalar_baseline`](../api/add_scalar_baseline.md):
`run.add_scalar_baseline("val/pesq", 1.31)`. The chart draws it as a dashed
line that a switch turns off.

## Text, images, audio, figures, PR curves, distributions, tables, point clouds, HTML

Each kind of media has its own `add_*` method, described in full, with its
arguments, accepted shapes, storage and an example with the result, in the
[Media](../api/index.md) reference:

| Method | Accepts |
| --- | --- |
| [`add_text`](../api/add_text.md) | any string |
| [`add_image`](../api/add_image.md) | an `HxW`, `HxWxC` or `CxHxW` array or tensor, a PIL image, image bytes or a file |
| [`add_audio`](../api/add_audio.md) | a `(samples,)` or `(channels, samples)` array or tensor with `sample_rate`, audio bytes or a file |
| [`add_figure`](../api/add_figure.md) | a Plotly, Altair/Vega-Lite, Bokeh or matplotlib figure, or a Plotly or Vega-Lite dict |
| [`add_pr_curve`](../api/add_pr_curve.md) | labels and scores in [0, 1] |
| [`add_histogram`](../api/add_histogram.md) | numbers of any shape |
| [`add_table`](../api/add_table.md) | a list of dicts, a dict of columns or a DataFrame, with `nb.Audio` and `nb.Image` cells |
| [`add_point_cloud`](../api/add_point_cloud.md) | an `(N, 3)` array of positions, with optional colors and axes |
| [`add_html`](../api/add_html.md) | an HTML string |

```python
run.add_image("samples/recon", img, step=step)
run.add_audio("eval/enhanced", model(noisy)[0], step=epoch, sample_rate=16_000)
run.add_histogram("grads/encoder.weight", p.grad, step=epoch)
```

`step` defaults to the last step passed to `log`. Arrays are copied on the
calling thread and encoded on the background thread; figures are serialized
on the calling thread (they are mutable). Media bytes go to
`media.r<rank>.pack`, indexed by frames in the event log.

## Artifacts

```python
art = run.add_artifact("model", "ckpt/", type="checkpoint", metadata={"step": 1000})
art.ref  # "model:v3"
ds = run.use_artifact("datasets/fineweb-edu:v2")  # another project's; or "model", "model:latest"
ds.files  # Path to the files
ds.manifest  # size and sha256 (or modification time) per file, type, metadata, producing run
```

Artifacts live in `<project>/artifacts/<name>/v<N>/`; versions are numbered
automatically and created atomically. `add_artifact` copies the files on the
calling thread, so avoid calling it inside a hot loop with large checkpoints.
With `reference=True` it records where the files are instead, for datasets
that stay on shared storage; `nb.add_artifact` does the same without a run.
The viewer's [Artifacts page](artifacts.md) shows every version with the runs
that produced and used it.

## Finishing, crashes and exit

- `run.finish()` flushes, writes an end frame, fsyncs, sets `status` to
  `finished` and (with PyArrow installed) compacts the logs to
  `data.parquet` and records the run's [health alerts](alerts.md).
  It is idempotent. Crashed and killed runs are compacted the same way.
- It is also called at interpreter exit (`atexit`).
- An uncaught exception marks the run `crashed` and stores the traceback in
  `run.json` → `exit.error`; `KeyboardInterrupt` marks it `killed`. The same
  happens when the `with` block exits with an exception.
- If the process is killed outright (`SIGKILL`, OOM killer, node failure),
  everything flushed so far is readable, the run keeps `status: running`, and
  the viewer shows it as **lost** once the heartbeat is two minutes old.

## Resume and fork

```python
# continue the same run (new session file; later session wins on overlapping steps)
run = nb.init("project", run_id="20261013T0720-d9fe0e01", resume="must")
run = nb.init("project", run_id=my_id, resume="auto")  # create it if missing

# start a new run whose history is a copy of another run's up to step 5000
run = nb.init("project", run_name="lower-lr", fork_from=("20261013T0720-d9fe0e01", 5000))
```

A resumed run writes `events.r0.s1.log`, `s2`, … next to the earlier
sessions. If you restart from a checkpoint at step 5000, points the old session
logged at step ≥ 5000 are hidden in favour of the new session's points (per
scalar). A fork copies the parent's points up to the fork step into the new
run's folder, so the new folder still never refers to anything outside it.

To log into a run from a second process while the first is still running, such
as an evaluator that scores checkpoints, use `job=` instead of `resume`. See
[Evaluating while training](jobs.md).

## Environment variables

| Variable | Effect |
| --- | --- |
| `NUBOARD_DIR` | Default root folder for `init`, `serve` and `ls`. |
| `NUBOARD_CACHE_DIR` | Where the viewer keeps its catalog cache. |
| `NUBOARD_DATA_DIR` | This machine's data folder; references to datasets inside it work on every machine that sets it. See [Data on several machines](artifacts.md#data-on-several-machines). |
| `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, `SLURM_*`, `OMPI_COMM_WORLD_*` | Rank detection (see [Distributed training](distributed.md)). |
