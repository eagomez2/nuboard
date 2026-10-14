---
hide:
  - navigation
  - toc
---

<div class="nb-hero" markdown>

![nuboard](assets/logo.svg){ .nb-logo }

# Experiment tracking that lives in a folder

`nuboard` logs your training runs with three Python calls, keeps every run as
a plain folder on disk, and opens thousands of them in a fast viewer that runs
on your own machine. There is no account to create, no server to keep running
and no database to back up.

[Quickstart](quickstart.md){ .md-button .md-button--primary }
[Guides](guide/logging.md){ .md-button }

</div>

```python
import nuboard as nm

with nm.init("llm-pretrain", name="baseline", config={"lr": 3e-4}) as run:
    for step in range(10_000):
        loss = train_step()
        run.log({"train/loss": loss}, step=step)  # a few µs, never blocks training
```

```console
$ nuboard up experiments
nuboard serving /home/me/experiments (28 runs) at http://localhost:6070/  (Ctrl+C to stop)
```

![The Charts page: a learning-rate sweep grouped by lr, with mean ± std bands over three seeds and health alerts below](assets/charts-light.png#only-light){ .nb-shot }
![The Charts page: a learning-rate sweep grouped by lr, with mean ± std bands over three seeds and health alerts below](assets/charts-dark.png#only-dark){ .nb-shot }

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } __Three calls to log__

    ---

    `init`, `log`, `finish`. Config, git commit and diff, installed packages,
    GPUs, command line and rank are recorded for you. The logging side uses
    only the Python standard library.

-   :material-folder-outline:{ .lg .middle } __One folder per run__

    ---

    A run is a folder you can copy, rsync, zip or delete. Stars, notes and
    custom fields live next to the data in `annotations.json`, so they move
    with it.

-   :material-chart-bell-curve-cumulative:{ .lg .middle } __Grouped charts__

    ---

    One line per learning rate with mean ± std bands over seeds, smoothing,
    zoom that loads finer data, a linked crosshair and live updates while
    runs train.

-   :material-tune-variant:{ .lg .middle } __Sweeps__

    ---

    Parallel coordinates with brushing, objective-vs-parameter scatters and
    a rank correlation per parameter show which settings matter.

-   :material-alert-outline:{ .lg .middle } __Health alerts__

    ---

    NaN and Inf values, loss and gradient spikes and throughput drops are
    found per run and rank and shown in the runs table and under charts.

-   :material-graph-outline:{ .lg .middle } __Artifacts and lineage__

    ---

    Versioned datasets and checkpoints with a lineage graph: which run
    produced a version, and which runs used it.

</div>

## About nuboard

nuboard is a local alternative to TensorBoard and hosted experiment trackers
for people who train models on their own machines or clusters. Each run writes
an append-only binary log from a background thread, so a crash loses at most
the last second of data. When a run finishes, the log is compacted into a
Parquet file with precomputed zoom levels, and the run's health alerts are
recorded next to it.

`nuboard up` points the viewer at any folder: a single run, a project, or a
tree of many projects. It finds every run, keeps a small SQLite cache of their
metadata outside the folder, and filters them with a short query language such
as `where tags has "sweep" and train/loss.min < 2.4 group by config.optim.lr`.
Every view is a URL, and views and collections can be saved into the project
folder and committed to git.

## Guides

- [Installation](installation.md) covers the wheel, building from source and
  the optional viewer dependencies.
- [Quickstart](quickstart.md) runs the demo and logs a first run.
- [Logging from Python](guide/logging.md), [Using the viewer](guide/viewer.md),
  [Sweeps](guide/sweeps.md), [Health alerts](guide/alerts.md) and
  [Artifacts](guide/artifacts.md) explain each part in depth.
- The [Reference](reference/query.md) documents the query language, the
  [file format](reference/format.md) and the [architecture](reference/architecture.md).
