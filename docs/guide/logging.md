# Logging from Python

```python
import nuboard as nm

run = nm.init("project", name="baseline", config=cfg)  # also a context manager
ds = run.use_artifact("dataset:v2")
run.log({"loss": loss, "lr": lr}, step=step)  # non-blocking
run.log_image("samples/recon", img, step=step)
run.log_text("samples/gen", text, step=step)
run.log_figure("eval/confusion", fig, step=step)  # Plotly, Altair/Vega-Lite, Bokeh, matplotlib
run.log_html("eval/graph", html, step=step)
run.log_artifact("model", "ckpt/", type="checkpoint", metadata={"step": step})
run.finish()  # also on exit and on crash
```

## `nm.init`

```python
nm.init(
    project=None,           # folder name (may be nested: "team/llm"); default "default"
    *,
    name=None,              # short run name, part of the run id
    config=None,            # dict, dataclass, argparse.Namespace, OmegaConf, or obj.to_dict()
    dir=None,               # root folder; default $NUBOARD_DIR or ./experiments
    tags=None, notes=None, group=None,
    run_id=None, resume=None,   # resume="must" | "auto"
    fork_from=None,         # (run_id, step)
    all_ranks=False,        # log on every rank, not only rank 0
    capture_env=True,       # git, pip freeze, GPUs, command line
    compact=True,           # write data.parquet at finish if PyArrow is installed
    flush_interval=1.0,     # seconds between background writes
    heartbeat_interval=10.0,
)
```

`init` creates `<dir>/<project>/runs/<YYYYMMDD-HHMM>_<name>_<rand>/` and
records:

- the config (`run.json` and `files/config.json`),
- git commit, branch, remote and dirty flag, plus `git diff HEAD` as
  `files/git.patch` (skipped outside a repository),
- installed packages as `files/requirements.txt` (read from package metadata,
  no subprocess),
- the command line (`files/command.txt`), host, Python, platform and GPUs
  (via `nvidia-smi` if present),
- rank and world size (see [Distributed training](distributed.md)).

Pass `capture_env=False` to skip git, packages and GPUs.

## `run.log`

```python
run.log(data, step=None, *, time=None, all_ranks=None)
```

- `data` is a dict of numbers. Nested dicts are flattened with `/`
  (`{"train": {"loss": 1}}` logs `train/loss`). Values may be Python numbers,
  bools, NumPy scalars or 0-d tensors; conversion to float happens on the
  background thread. Strings are skipped with a one-time warning; use
  `log_text`.
- `step` defaults to one more than the previous call's step. Pass it
  explicitly when you log several dicts per step.
- `time` overrides the timestamp (useful when importing data).
- NaN and ±Inf are stored as they are; the viewer flags them.

`log()` only appends to a deque (a few microseconds for a 50-metric dict). A
background thread wakes every `flush_interval` seconds, encodes the batch into
one columnar frame and appends it to the event log. Call `run.flush()` if you
need everything on disk at a given point (rarely needed).

## Text, images, figures, HTML

| Method | Accepts |
| --- | --- |
| `log_text(key, text, step=None)` | any string |
| `log_image(key, image, step=None, caption=None)` | PNG/JPEG bytes, a file path, a PIL image, or an `HxW`, `HxWxC` or `CxHxW` array or tensor (uint8, or float in [0, 1]) |
| `log_figure(key, fig, step=None)` | Plotly figure, Altair chart, Vega-Lite dict, Bokeh figure, matplotlib figure (stored as SVG) |
| `log_html(key, html, step=None)` | an HTML string; rendered in a sandboxed iframe |

`step` defaults to the last step passed to `log`. Arrays are copied on the
calling thread and PNG-encoded on the background thread; figures are
serialized on the calling thread (they are mutable). Media bytes go to
`media.r<rank>.pack`, indexed by frames in the event log.

## Artifacts

```python
art = run.log_artifact("model", "ckpt/", type="checkpoint", metadata={"step": 1000})
art.ref  # "model:v3"
ds = run.use_artifact("dataset:v2")  # or "dataset", "dataset:latest"
ds.files  # Path to the files
ds.manifest  # sha256 and size per file, type, metadata, producing run
```

Artifacts live in `<project>/artifacts/<name>/v<N>/`; versions are numbered
automatically and created atomically. `log_artifact` copies the files on the
calling thread, so avoid calling it inside a hot loop with large checkpoints.

## Finishing, crashes and exit

- `run.finish()` flushes, writes an end frame, fsyncs, sets `status` to
  `finished` and (with PyArrow installed) compacts the logs to
  `data.parquet`. It is idempotent.
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
run = nm.init("project", run_id="20261013-0720_baseline_x5bq2k", resume="must")
run = nm.init("project", run_id=my_id, resume="auto")  # create it if missing

# start a new run whose history is a copy of another run's up to step 5000
run = nm.init("project", name="lower-lr", fork_from=("20261013-0720_baseline_x5bq2k", 5000))
```

A resumed run writes `events.r0.s1.log`, `s2`, … next to the earlier
sessions. If you restart from a checkpoint at step 5000, points the old session
logged at step ≥ 5000 are hidden in favour of the new session's points (per
metric). A fork copies the parent's points up to the fork step into the new
run's folder, so the new folder still never refers to anything outside it.

## Environment variables

| Variable | Effect |
| --- | --- |
| `NUBOARD_DIR` | Default root folder for `init`, `serve` and `ls`. |
| `NUBOARD_CACHE_DIR` | Where the viewer keeps its catalog cache. |
| `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, `SLURM_*`, `OMPI_COMM_WORLD_*` | Rank detection (see [Distributed training](distributed.md)). |
