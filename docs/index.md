---
hide:
  - navigation
  - toc
---

<div class="nb-hero" markdown>

![NuBoard](assets/logo.svg){ .nb-logo }

# Experiment tracking that lives in a folder

Log training runs from Python in three calls, keep each run as a plain folder,
and browse thousands of them in a fast viewer on your own machine. No account,
no server, no database.

[:material-rocket-launch-outline: Quickstart :material-arrow-right:{ .nb-go }](quickstart.md){ .md-button .md-button--primary }
[:material-book-open-variant: Guides](guide/logging.md){ .md-button }

<p class="nb-works" markdown>Works with
[:simple-lightning: PyTorch Lightning](guide/integrations.md#pytorch-lightning){ .nb-pill }
[:simple-huggingface: Hugging Face](guide/integrations.md#hugging-face-trainer){ .nb-pill }
[:simple-jupyter: Jupyter](guide/integrations.md#jupyter){ .nb-pill }
[:simple-python: Plain Python, no framework needed](quickstart.md){ .nb-pill }
</p>

</div>

<div class="nb-start" markdown>

=== ":material-language-python: Python"

    ```python
    # pip install nuboard
    import nuboard as nb

    with nb.init("llm-pretrain", run_name="baseline", config={"lr": 3e-4}) as run:
        for step in range(10_000):
            run.add_scalar({"train/loss": train_step()}, step=step)  # a few µs, never blocks

    # then, in a terminal: nuboard up experiments
    ```

=== ":simple-lightning: Lightning"

    ```python
    from nuboard.integrations.lightning import NuBoardLogger

    trainer = L.Trainer(logger=NuBoardLogger("mnist", run_name="baseline"))
    trainer.fit(model, datamodule)  # self.log(...) and the hyperparameters, from rank 0
    ```

=== ":simple-huggingface: Hugging Face"

    ```python
    from nuboard.integrations.huggingface import NuBoardCallback

    trainer = Trainer(model, args, train_dataset=train, eval_dataset=val,
                      callbacks=[NuBoardCallback("glue-mrpc")])
    trainer.train()  # train/loss, eval/loss, ... with the arguments as the config
    ```

=== ":simple-jupyter: Jupyter"

    ```python
    run = nb.init("mnist", config={"lr": 3e-4})
    run           # a summary: status, config, the last value of each scalar
    nb.show(run)  # the viewer in the cell, updating live while it trains
    ```

<p class="nb-start-note" markdown>The integrations add no dependencies. [Frameworks and notebooks :material-arrow-right:](guide/integrations.md)</p>

</div>

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

    **Audio with its annotations.** <span>Overlay a voice activity probability and label tracks on the waveform, play only a frequency band, zoom and leave notes on any region.</span>
    { .nb-feature-text }

    ![A waveform figure: a denoised speech clip with its speech probability on top and target, predicted and event tracks below](assets/about/audio-light.png#only-light){ .nb-shot }
    ![A waveform figure: a denoised speech clip with its speech probability on top and target, predicted and event tracks below](assets/about/audio-dark.png#only-dark){ .nb-shot }

=== ":material-chart-timeline: Timeline"

    **What ran before what.** <span>Overlapping runs, crashes and the artifact versions each run produced, on one time axis.</span>
    { .nb-feature-text }

    ![The Timeline page: one bar per run of a project, colored by status, with artifact versions marked as diamonds](assets/about/timeline-light.png#only-light){ .nb-shot }
    ![The Timeline page: one bar per run of a project, colored by status, with artifact versions marked as diamonds](assets/about/timeline-dark.png#only-dark){ .nb-shot }

=== ":material-flag-outline: Select"

    **Pick the step to ship.** <span>When runs win on different scalars, the shortlist keeps only the steps nothing beats on all of them, and shows what each choice costs.</span>
    { .nb-feature-text }

    ![The Select page: accuracy against calibration error for every run at every step, with the shortlist of steps no other step beats on both](assets/about/select-light.png#only-light){ .nb-shot }
    ![The Select page: accuracy against calibration error for every run at every step, with the shortlist of steps no other step beats on both](assets/about/select-dark.png#only-dark){ .nb-shot }

=== ":material-source-branch: Hypotheses"

    **Keep the why next to the what.** <span>Each card is a question, the runs that tested it and a verdict, linked to the idea that came next.</span>
    { .nb-feature-text }

    ![A hypotheses board: cards with a question, the runs that tested it and a verdict, linked by arrows that say what led to what](assets/about/hypotheses-light.png#only-light){ .nb-shot }
    ![A hypotheses board: cards with a question, the runs that tested it and a verdict, linked by arrows that say what led to what](assets/about/hypotheses-dark.png#only-dark){ .nb-shot }

</div>

<div class="grid cards nb-cards" markdown>

-   :material-language-python: __Three calls to log.__ Config, git diff, packages, GPUs and rank are recorded for you; logging uses only the standard library.
-   :material-folder-outline: __One folder per run.__ Copy, rsync, zip or delete it; notes and tags move with it.
-   :material-chart-bell-curve-cumulative: __Grouped charts.__ Mean ± std bands over seeds, smoothing, zoom that loads finer data, live updates.
-   :material-tune-variant: __Sweeps.__ Parallel coordinates and per-parameter scatters show which settings matter.
-   :material-alert-outline: __Health alerts.__ NaN/Inf, loss and gradient spikes, throughput drops, per run and rank.
-   :material-graph-outline: __Artifacts and lineage.__ Versioned datasets and checkpoints, and which runs made and used them.

</div>

<div class="nb-about" markdown>

A local alternative to TensorBoard and hosted trackers. Runs write an
append-only log from a background thread, so a crash loses at most the last
second, and are compacted to Parquet with zoom levels when they finish.
`nuboard up` opens any folder of runs, filters them with a short
[query language](reference/query.md) and keeps every view in the URL.
Free software under the [MIT License](license.md).

[Installation](installation.md) · [Quickstart](quickstart.md) ·
[Logging from Python](guide/logging.md) ·
[Frameworks and notebooks](guide/integrations.md) ·
[Using the viewer](guide/viewer.md) ·
[Importing from TensorBoard](guide/tensorboard.md) ·
[Reference](reference/query.md)
{ .nb-links }

</div>
