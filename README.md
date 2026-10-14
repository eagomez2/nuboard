<p align="center"><img src="docs/assets/logo.svg" width="72" alt=""></p>

<h1 align="center">nuboard</h1>

<p align="center"><b>A fast, local experiment tracker for ML training.</b><br>
Log from Python with three calls. Every run is a folder. View thousands of runs in your browser.</p>

![Charts page: a learning-rate sweep grouped by lr, mean ± std over three seeds](docs/assets/charts-light.png)

```python
import nuboard as nm

with nm.init("my-project", name="baseline", config={"lr": 3e-4}) as run:
    for step in range(10_000):
        loss = train_step()
        run.log({"train/loss": loss}, step=step)  # ~3 µs, never blocks training
```

```bash
nuboard up experiments        # http://localhost:6070
```

## Why

- **No setup.** No account, no server, no database. `pip install nuboard` adds
  no dependencies to your training environment (standard library only).
- **Folder-contained.** Each run is one folder (`run.json`, an append-only
  binary log, a media pack, a Parquet file at the end). Copy it, rsync it, zip
  it, delete it.
- **Fast.** Logging is a deque append; a background thread writes columnar
  frames. The viewer reads a million points in about a tenth of a second and
  lists thousands of runs instantly.
- **Records what you forget.** Config, git commit and uncommitted diff,
  installed packages, GPUs, command line and rank, automatically.
- **Crash-safe.** A killed process loses at most the last second of data; torn
  writes are ignored; crashes are marked with their traceback.

## Quick start

```bash
pip install "nuboard[viewer]"            # or the wheel next to this repo: pip install "nuboard-0.1.0-py3-none-any.whl[viewer]"
nuboard demo demo-runs --up --open    # 3 projects, ~27 runs, one live run
```

Then try `where tags has "sweep" group by config.optim.lr` in the query bar and
open the Charts page. The [getting started guide](docs/getting-started.md) has
a tour.

## What's in 0.1

| Area | Included |
| --- | --- |
| Python API | `init` (+ resume, fork, ranks), `log`, `log_text`, `log_image`, `log_figure`, `log_html`, `log_artifact`, `use_artifact`, `finish`, context manager |
| Storage | documented [log format](docs/format.md), Parquet compaction with zoom levels, versioned artifacts |
| Analysis | `nm.load("project").scalars("loss", group_by="config.lr")` → Arrow tables |
| Viewer | Runs table with a query language, stars, notes, archive, saved views; run details and config/file diffs; grouped line charts with bands, smoothing, zoom, linked crosshair, inspector and live updates; media with a step slider; light and dark themes |
| CLI | `nuboard up`, `demo`, `ls`, `compact` |

Not yet: multi-GPU rank bands, sweep views, health alerts, artifact lineage
pages, interactive Plotly/Vega/Bokeh rendering, TensorBoard import. See the
[roadmap](docs/roadmap.md).

## Documentation

The docs are a [MkDocs](https://www.mkdocs.org/) site in `docs/`:

```bash
uv run mkdocs serve    # http://localhost:8000
```

- [Getting started](docs/getting-started.md): install, demo, first run, CLI
- [Logging from Python](docs/guide/logging.md)
- [Using the viewer](docs/guide/viewer.md) and the [query language](docs/guide/query.md)
- [Analysis API](docs/guide/analysis.md)
- [Distributed training](docs/guide/distributed.md)
- [File format](docs/format.md), [Architecture](docs/architecture.md), [Development](docs/development.md)

## Development

```bash
uv sync                                              # Python + dev tools
(cd frontend && pnpm install && pnpm build)          # builds the viewer into src/nuboard/static/
uv run pytest && uv run ruff check . && uv run pyright
(cd frontend && pnpm test && pnpm check && pnpm lint && pnpm e2e)
uv build                                             # wheel with the frontend bundled
```

See [Development](docs/development.md) for the repository layout, the rules for
the logging side, and how to rename the project (the name lives in three
places).

## Requirements

Python 3.10+ on Linux, macOS or Windows. The viewer extra adds NumPy, PyArrow,
Starlette and uvicorn. Building the frontend from source needs Node 20+ and
pnpm; installing a wheel does not.
