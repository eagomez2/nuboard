# Getting started

## Install

nuboard needs Python 3.10 or newer on Linux, macOS or Windows.

```bash
pip install nuboard            # logging only: standard library, no dependencies
pip install "nuboard[viewer]"  # + the viewer and analysis API (NumPy, PyArrow, Starlette, uvicorn)
```

!!! note "Installing this first version"
    0.1 is not on PyPI yet. Install the wheel that ships next to the source zip,
    or install from the source folder:

    ```bash
    pip install "nuboard-0.1.0-py3-none-any.whl[viewer]"   # no Node needed
    # or, from the unzipped repository (builds the frontend, needs Node 20+ and pnpm):
    pip install ".[viewer]"
    ```

    For development use `uv sync` instead; see [Development](development.md).

## Run the demo

The demo writes three projects (an LLM learning-rate sweep with three seeds and
one diverging run, a ViT augmentation ablation with images and HTML reports,
and PPO on Atari), about 27 runs in total, then serves them while a live run
keeps logging:

```bash
nuboard demo demo-runs --up --open
```

Open <http://localhost:6070> if no browser tab appears. Things to try:

1. **Runs page.** Type `where status = crashed` in the query bar, or
   `train/loss.min < 2.35`. Click a run name to see its settings, files and
   the crash traceback. Select two runs and press **Compare** to diff their
   `config.json`, `requirements.txt` and command line.
2. **Charts.** Type `where tags has "sweep" group by config.optim.lr` and open
   the Charts page: one line per learning rate with a mean ± std band over
   three seeds. Drag on a chart to zoom (the server sends finer data), double-click
   to reset, move the smoothing slider, switch the x-axis to wall time.
3. **Live.** Run `where tags has "live"` on the Charts page and watch the
   running run update every couple of seconds.
4. **Media.** Select the `vit-ablations` project, select a few runs and press
   **Media**: augmented images and HTML reports with a step slider.

Without `--up`, the demo only writes the folder; view it later with
`nuboard up demo-runs`.

## Log your first run

```python
import nuboard as nm

config = {"lr": 3e-4, "batch_size": 64}
with nm.init("my-project", name="baseline", config=config) as run:
    for step in range(1000):
        loss = train_step()  # your code
        run.log({"train/loss": loss, "lr": config["lr"]}, step=step)
```

Runs go to `./experiments/<project>/runs/<run id>/` unless you pass `dir=` or
set `NUBOARD_DIR`. Then:

```bash
nuboard up experiments
```

See `examples/` in the repository: `quickstart.py` and
`train_numpy.py` (a small NumPy training loop with a learning-rate sweep).

## Command line

| Command | What it does |
| --- | --- |
| `nuboard up [DIR] [--port 6070] [--host 127.0.0.1] [--open]` | Start the viewer on any folder: one run, one project, or a tree of projects. |
| `nuboard demo [DIR] [--up] [--open]` | Write the demo workspace (default `demo-runs/`). |
| `nuboard ls [DIR] [-q QUERY]` | List runs, filtered with the [query language](guide/query.md). |
| `nuboard compact DIR [--force]` | Write `data.parquet` for finished runs that lack it. |
| `nuboard version` | Print the version. |

`python -m nuboard …` works too. The server binds to `127.0.0.1` by default
and only answers requests addressed to localhost. To view runs on a remote
machine, forward the port: `ssh -L 6070:localhost:6070 gpu-box`, then run
`nuboard up` there.
