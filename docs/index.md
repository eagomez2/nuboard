---
hide:
  - navigation
  - toc
---

<div class="nb-hero" markdown>

![NuBoard](assets/logo.svg){ .nb-logo }

# Experiment tracking that lives in a folder

`nuboard` logs your training runs with three Python calls, keeps every run as
a plain folder on disk, and opens thousands of them in a fast viewer that runs
on your own machine. There is no account to create, no server to keep running
and no database to back up.

[:material-rocket-launch-outline: Quickstart :material-arrow-right:{ .nb-go }](quickstart.md){ .md-button .md-button--primary }
[:material-book-open-variant: Guides](guide/logging.md){ .md-button }

</div>

=== "pip"

    ```bash
    pip install nuboard
    ```

=== "uv"

    ```bash
    uv pip install nuboard   # or: uv add nuboard, in a uv project
    ```

```python
import nuboard as nb

with nb.init("llm-pretrain", run_name="baseline", config={"lr": 3e-4}) as run:
    for step in range(10_000):
        loss = train_step()
        run.add_scalar({"train/loss": loss}, step=step)  # a few µs, never blocks training
```

```console
$ nuboard up experiments
nuboard serving /home/me/experiments (31 runs) at http://localhost:6070/  (Ctrl+C to stop)
```

<div class="nb-features" markdown>

=== ":material-view-dashboard-outline: Overview"

    **All your runs, one fast viewer.** <span>Group a sweep into mean ± std bands, smooth, zoom and catch NaNs and spikes while runs train.</span>
    { .nb-feature-text }

    ![The Charts page: a learning-rate sweep grouped by lr, with mean ± std bands over three seeds and health alerts below](assets/charts-light.png#only-light){ .nb-shot }
    ![The Charts page: a learning-rate sweep grouped by lr, with mean ± std bands over three seeds and health alerts below](assets/charts-dark.png#only-dark){ .nb-shot }

=== ":material-chart-bell-curve: Ranges"

    **Log a range, not just a number.** <span>Give `add_scalar` a `low` and `high` and each run gets its own shaded band, such as ± std over evaluation batches.</span>
    { .nb-feature-text }

    ![eval/loss for four runs, each drawn with a shaded band from its logged low and high values](assets/about/ranges-light.png#only-light){ .nb-shot }
    ![eval/loss for four runs, each drawn with a shaded band from its logged low and high values](assets/about/ranges-dark.png#only-dark){ .nb-shot }

=== ":material-timer-outline: Timing"

    **See where the time goes.** <span>Wrap training and validation in `run.timer`: mean and p95 per step, slow outliers, and which rank everyone waited for.</span>
    { .nb-feature-text }

    ![The Timing tab of a run: each timer with its calls, mean per step, p95 and total, and a per-rank timeline of one step](assets/about/timing-light.png#only-light){ .nb-shot }
    ![The Timing tab of a run: each timer with its calls, mean per step, p95 and total, and a per-rank timeline of one step](assets/about/timing-dark.png#only-dark){ .nb-shot }

=== ":material-waveform: Audio"

    **Audio with its annotations.** <span>Overlay a voice activity probability and label tracks on the waveform, then play, zoom and leave notes on any region.</span>
    { .nb-feature-text }

    ![A waveform figure: a denoised speech clip with its speech probability on top and target, predicted and event tracks below](assets/about/audio-light.png#only-light){ .nb-shot }
    ![A waveform figure: a denoised speech clip with its speech probability on top and target, predicted and event tracks below](assets/about/audio-dark.png#only-dark){ .nb-shot }

=== ":material-chart-timeline: Timeline"

    **What ran before what.** <span>Overlapping runs, crashes and the artifact versions each run produced, on one time axis.</span>
    { .nb-feature-text }

    ![The Timeline page: one bar per run of a project, colored by status, with artifact versions marked as diamonds](assets/about/timeline-light.png#only-light){ .nb-shot }
    ![The Timeline page: one bar per run of a project, colored by status, with artifact versions marked as diamonds](assets/about/timeline-dark.png#only-dark){ .nb-shot }

=== ":material-source-branch: Hypotheses"

    **Keep the why next to the what.** <span>Each card is a question, the runs that tested it and a verdict, linked to the idea that came next.</span>
    { .nb-feature-text }

    ![A hypotheses board: cards with a question, the runs that tested it and a verdict, linked by arrows that say what led to what](assets/about/hypotheses-light.png#only-light){ .nb-shot }
    ![A hypotheses board: cards with a question, the runs that tested it and a verdict, linked by arrows that say what led to what](assets/about/hypotheses-dark.png#only-dark){ .nb-shot }

</div>

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } __Three calls to log__

    ---

    `init`, `add_scalar`, `finish`. Config, git commit and diff, installed packages,
    GPUs, command line and rank are recorded for you. The logging side uses
    only the Python standard library.

-   :material-folder-outline:{ .lg .middle } __One folder per run__

    ---

    A run is a folder you can copy, rsync, zip or delete. Stars, notes, tags and
    properties live next to the data in `annotations.json`, so they move
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

## About NuBoard

NuBoard is a local alternative to TensorBoard and hosted experiment trackers
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

## License

NuBoard is free software under the [MIT License](license.md).

## Guides

- [Installation](installation.md) covers `pip install nuboard` and building
  from source.
- [Quickstart](quickstart.md) runs the demo and logs a first run.
- [Logging from Python](guide/logging.md), [Using the viewer](guide/viewer.md),
  [Sweeps](guide/sweeps.md), [Health alerts](guide/alerts.md) and
  [Artifacts](guide/artifacts.md) explain each part in depth, and
  [Importing from TensorBoard](guide/tensorboard.md) brings old logs in.
- The [Reference](reference/query.md) documents the query language, the
  [file format](reference/format.md) and the [architecture](reference/architecture.md).
