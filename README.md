<p align="center"><img src="https://raw.githubusercontent.com/eagomez2/nuboard/main/docs/assets/logo.svg" width="72" alt=""></p>

<h1 align="center">NuBoard</h1>

<p align="center"><b>Experiment tracking that lives in a folder.</b><br>
Log from Python with three calls. Every run is a folder. View thousands of runs in your browser.</p>

![Charts page: a learning-rate sweep grouped by lr, mean ± std over three seeds](https://raw.githubusercontent.com/eagomez2/nuboard/main/docs/assets/charts-light.png)

```python
import nuboard as nb

with nb.init("my-project", run_name="baseline", config={"lr": 3e-4}) as run:
    for step in range(10_000):
        loss = train_step()
        run.add_scalar({"train/loss": loss}, step=step)  # ~3 µs, never blocks training
```

```bash
nuboard up experiments        # http://localhost:6070
```

## Why

- **No setup.** No account, no server, no database. `pip install nuboard` gives
  you logging and the viewer; logging uses only the standard library, so it
  adds nothing to the import time of a training script.
- **Folder-contained.** Each run is one folder (`run.json`, an append-only
  binary log, a media pack, a Parquet file at the end). Copy it, rsync it, zip
  it, delete it.
- **Fast.** Logging is a deque append; a background thread writes columnar
  frames. The viewer reads a million points in about a tenth of a second and
  lists thousands of runs instantly.
- **Records what you forget.** Config, git commit and uncommitted diff,
  installed packages, GPUs, command line, rank, console output and CPU, memory
  and GPU use, automatically.
- **Crash-safe.** A killed process loses at most the last second of data; torn
  writes are ignored; crashes are marked with their traceback.

## Quick start

```bash
pip install nuboard                   # or: uv pip install nuboard
nuboard demo demo-runs --up --open    # 4 projects, 31 runs, one live run
```

Then try `where tags has "sweep" group by config.optim.lr` in the query bar and
open the Charts page. The [quickstart](https://eagomez2.github.io/nuboard/quickstart/) has a tour, and
[installation](https://eagomez2.github.io/nuboard/installation/) covers building from source.

## What's in 0.13

| Area | Included |
| --- | --- |
| Python API | `init` (+ resume, fork, ranks), `add_scalar`, `add_file`, `add_text`, `add_image`, `add_audio`, `add_video`, `add_figure`, `add_pr_curve`, `add_histogram`, `add_table`, `add_point_cloud`, `add_html`, `add_artifact` (copies or references), `use_artifact` (across projects), `nb.add_artifact`, `nb.get_artifact`, `finish`, context manager; system scalars (CPU, memory, GPU) and console capture |
| Storage | documented [log format](https://eagomez2.github.io/nuboard/reference/format/), Parquet compaction with zoom levels, versioned artifacts, collections |
| Analysis | `nb.load("project").scalars("loss", group_by="config.lr")` returns Arrow tables; properties, collections and alerts per run |
| Runs | query language, stars, Markdown notes, archive, typed properties, tag editing, column chooser, collections, saved views, run details and config/file diffs |
| Charts | grouped lines with bands, smoothing, zoom, linked crosshair, inspector, live updates, alerts strip, x axis by any scalar (tokens, epochs), solo or show all series |
| Media | images, video, audio (waveform + spectrogram player with notes, or the browser's player), per-example tables compared across steps, PR curves, distributions over steps, point clouds with axes, text, HTML, interactive Plotly, Vega-Lite and Bokeh figures, and waveforms with signals over them (accurate at every zoom); filter by kind, a step slider per card, best-scalar step, configurable grid |
| Reports | Markdown reports that embed logged items, live charts and plot snapshots; export as HTML or a zip, print to PDF |
| Sweeps | parallel coordinates with brushing, scatter per parameter, rank correlation, best runs |
| Timeline | runs over wall-clock time, packed concurrency view, crash, alert and artifact markers |
| Artifacts | versions, files, metadata and a lineage graph |
| Health alerts | NaN/Inf, loss and gradient spikes, throughput drops, per scalar and rank |
| CLI | `nuboard up`, `demo`, `ls`, `rm`, `compact`, `merge`, `artifact add`/`ls`/`show`, `import-tensorboard` (TensorBoard logs to runs); see the [command line reference](https://eagomez2.github.io/nuboard/reference/cli/) |

See the [changelog](https://eagomez2.github.io/nuboard/changelog/) and the
[known limitations](https://eagomez2.github.io/nuboard/reference/limitations/).

## Documentation

The docs are a [MkDocs](https://www.mkdocs.org/) site in `docs/`:

```bash
uv run mkdocs serve    # http://localhost:8000
```

- [Installation](https://eagomez2.github.io/nuboard/installation/) and [Quickstart](https://eagomez2.github.io/nuboard/quickstart/)
- [Logging from Python](https://eagomez2.github.io/nuboard/guide/logging/), [Using the viewer](https://eagomez2.github.io/nuboard/guide/viewer/),
  [Sweeps](https://eagomez2.github.io/nuboard/guide/sweeps/), [Health alerts](https://eagomez2.github.io/nuboard/guide/alerts/),
  [Artifacts and lineage](https://eagomez2.github.io/nuboard/guide/artifacts/), [Analysis API](https://eagomez2.github.io/nuboard/guide/analysis/),
  [Distributed training](https://eagomez2.github.io/nuboard/guide/distributed/),
  [Importing from TensorBoard](https://eagomez2.github.io/nuboard/guide/tensorboard/)
- Reference: [query language](https://eagomez2.github.io/nuboard/reference/query/), [file format](https://eagomez2.github.io/nuboard/reference/format/),
  [architecture](https://eagomez2.github.io/nuboard/reference/architecture/), [development](https://eagomez2.github.io/nuboard/reference/development/)

## Development

```bash
uv sync                                              # Python + dev tools
(cd frontend && pnpm install && pnpm build)          # builds the viewer into src/nuboard/static/
uv run pytest && uv run ruff check . && uv run pyright
(cd frontend && pnpm test && pnpm check && pnpm lint && pnpm e2e)
uv build                                             # wheel with the frontend bundled
```

See [Development](https://eagomez2.github.io/nuboard/reference/development/) for the repository layout, the rules for
the logging side, and how to rename the project (the name lives in three
places).

## License

NuBoard is released under the [MIT License](https://github.com/eagomez2/nuboard/blob/main/LICENSE).

## Requirements

Python 3.10+ on Linux, macOS or Windows. It installs NumPy, PyArrow, Starlette and
uvicorn for the viewer; logging uses only the standard library. Building the
frontend from source needs Node 20+ and pnpm (`brew install pnpm` on macOS);
installing from PyPI does not.
