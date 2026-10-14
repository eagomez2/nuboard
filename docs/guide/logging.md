# Logging from Python

```python
import nuboard as nb

run = nb.init("project", name="baseline", config=cfg)  # also a context manager
ds = run.use_artifact("dataset:v2")
run.log({"loss": loss, "lr": lr}, step=step)  # non-blocking
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
  `add_text`.
- `step` defaults to one more than the previous call's step. Pass it
  explicitly when you log several dicts per step.
- `time` overrides the timestamp (useful when importing data).
- NaN and ±Inf are stored as they are; the viewer flags them.

`log()` only appends to a deque (a few microseconds for a 50-metric dict). A
background thread wakes every `flush_interval` seconds, encodes the batch into
one columnar frame and appends it to the event log. Call `run.flush()` if you
need everything on disk at a given point (rarely needed).

## Text, images, audio, figures, HTML

| Method | Accepts |
| --- | --- |
| `add_text(key, text, step=None)` | any string |
| `add_image(key, image, step=None, caption=None)` | PNG/JPEG bytes, a file path, a PIL image, or an `HxW`, `HxWxC` or `CxHxW` array or tensor (uint8, or float in [0, 1]) |
| `add_audio(key, audio, step=None, sample_rate=None, caption=None)` | a file path (WAV, FLAC, MP3, Ogg/Opus, M4A, WebM), encoded bytes, or a `(samples,)` or `(channels, samples)` array or tensor with `sample_rate` (float in [-1, 1], or int16) |
| `add_figure(key, fig, step=None)` | Plotly figure or figure dict, Altair chart, Vega-Lite dict, Bokeh figure, matplotlib figure (stored as SVG) |
| `add_html(key, html, step=None)` | an HTML string; rendered in a sandboxed iframe |

Audio arrays are stored as 16-bit PCM WAV, written with the standard
library's `wave` module, so logging audio needs nothing beyond NumPy for the
array itself. Files and bytes are stored as they are: log a FLAC or Opus file
when size matters (16 kHz mono WAV is 32 KB per second). The sample rate,
channel count and duration are recorded with each clip.

```python
run.add_audio("eval/enhanced", model(noisy)[0], step=epoch, sample_rate=16_000)
run.add_audio("eval/input", "data/noisy/p232_001.flac", step=0, caption="p232_001")
```

Plotly, Vega-Lite and Bokeh figures stay interactive in the viewer. None of
these libraries is needed by nuboard itself: a figure is serialized with its
own library, and plain dicts work without any of them, so a Vega-Lite spec
(a dict with a `$schema`) or a Plotly figure dict (`{"data": [...],
"layout": {...}}`, as `fig.to_dict()` returns) can be logged directly:

```python
run.add_figure(
    "eval/per_class",
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"values": [{"cls": "cat", "acc": 0.71}, {"cls": "dog", "acc": 0.74}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "cls", "type": "nominal"},
            "y": {"field": "acc", "type": "quantitative"},
        },
    },
    step=step,
)
```

`step` defaults to the last step passed to `log`. Arrays are copied on the
calling thread and PNG-encoded on the background thread; figures are
serialized on the calling thread (they are mutable). Media bytes go to
`media.r<rank>.pack`, indexed by frames in the event log.

## Artifacts

```python
art = run.add_artifact("model", "ckpt/", type="checkpoint", metadata={"step": 1000})
art.ref  # "model:v3"
ds = run.use_artifact("dataset:v2")  # or "dataset", "dataset:latest"
ds.files  # Path to the files
ds.manifest  # sha256 and size per file, type, metadata, producing run
```

Artifacts live in `<project>/artifacts/<name>/v<N>/`; versions are numbered
automatically and created atomically. `add_artifact` copies the files on the
calling thread, so avoid calling it inside a hot loop with large checkpoints.
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
run = nb.init("project", run_id="20261013-0720_baseline_x5bq2k", resume="must")
run = nb.init("project", run_id=my_id, resume="auto")  # create it if missing

# start a new run whose history is a copy of another run's up to step 5000
run = nb.init("project", name="lower-lr", fork_from=("20261013-0720_baseline_x5bq2k", 5000))
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
