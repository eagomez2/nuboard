# nuboard

**A fast, local experiment tracker for ML training.** Log from Python with
three calls, keep every run as a self-contained folder, and look at thousands
of runs in a browser viewer that ships inside the wheel.

![Charts page, grouped by learning rate](assets/charts-light.png)

- **Easy from Python.** `init`, `log`, `finish`. No configuration, no account,
  no server. Config, git commit and diff, installed packages, GPUs, command line
  and rank are recorded automatically.
- **Folder-contained.** Every run is one folder you can copy, rsync, zip or
  delete. No database server; the viewer's catalog is a disposable cache.
- **Never slows training.** `log()` appends to an in-memory queue (a few µs
  for a 50-metric dict); a background thread writes compact binary frames.
  The logging side uses only the Python standard library.
- **Fast viewer.** `nuboard up <dir>` opens any folder of projects. Runs
  table with a query language, grouped line charts with mean ± std bands,
  smoothing, zoom, linked crosshair, live updates, config diffs, and media.

## Where to go next

| I want to… | Read |
| --- | --- |
| install it and see the demo | [Getting started](getting-started.md) |
| log from my training script | [Logging from Python](guide/logging.md) |
| find, compare and plot runs | [Using the viewer](guide/viewer.md) and [Query language](guide/query.md) |
| load runs into pandas/Arrow | [Analysis API](guide/analysis.md) |
| use it with torchrun / SLURM | [Distributed training](guide/distributed.md) |
| know exactly what is on disk | [File format](format.md) |
| understand or change the code | [Architecture](architecture.md) and [Development](development.md) |
| see what is not built yet | [Roadmap](roadmap.md) |

## Status

Version 0.1 is a first working version: the log format, Python API, reader,
Parquet compaction, analysis API, catalog and the viewer's Runs, Charts and
Media pages are implemented and tested. Sweep views, health alerts, artifact
lineage pages and TensorBoard import are on the [roadmap](roadmap.md).
