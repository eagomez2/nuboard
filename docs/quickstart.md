---
hide:
  - navigation
---

# Quickstart

## Run the demo

The demo writes four projects with 31 runs and serves them while a live run
keeps logging:

- **llm-pretrain**: a learning-rate sweep with three seeds per rate, one run
  that diverges to NaN, one with a loss spike and one with a throughput drop,
  a dataset and checkpoint lineage, two collections and a few properties.
- **vit-ablations**: an augmentation ablation with images and HTML reports.
- **ppo-atari**: PPO on two Atari games.

```bash
nuboard demo demo-runs --up --open
```

Open <http://localhost:6070> if no browser tab appears. Without `--up` the
demo only writes the folder; view it later with `nuboard up demo-runs`.

## Take the tour

1. **Runs.** Pick `llm-pretrain` in the workspace list. Runs with a warning
   badge have health alerts; hover the badge to read them. Type
   `where status = crashed` in the query bar, then clear it and try
   `train/loss.min < 2.3`. Open **Columns** and tick the `verdict`
   property; click a cell to edit it. Select a few runs and press **Tags…**
   to tag them.
2. **Collections.** Click **shortlist** under the project. Select a few more
   runs and press **Add to collection…**.
3. **Charts.** Type `where tags has "sweep" group by config.optim.lr` and open
   Charts: one line per learning rate with a mean ± std band over three seeds.
   The alerts under the chart jump to the spike or drop they describe. Drag to
   zoom, double-click to reset.
4. **Sweeps.** Open Sweeps with the query cleared. Drag along the `optim.lr`
   axis to keep a range of runs and read the best runs below.
5. **Timeline.** See when each run ran, switch to **packed** to see how many
   ran at once, and color by **group**.
6. **Artifacts.** `fineweb-edu:v2` shows its lineage: the run that prepared
   it, the twelve runs that trained on it, the checkpoint one of them saved and
   the evaluation that used the checkpoint.
7. **Live.** Run `where tags has "live"` on Charts and watch the running run
   update every couple of seconds.

## Log your first run

```python
import nuboard as nb

config = {"lr": 3e-4, "batch_size": 64}
with nb.init("my-project", name="baseline", config=config) as run:
    for step in range(1000):
        loss = train_step()  # your code
        run.add_scalar({"train/loss": loss, "lr": config["lr"]}, step=step)
```

Runs go to `./experiments/<project>/runs/<run id>/` unless you pass `dir=` or
set `NUBOARD_DIR`. Then:

```bash
nuboard up experiments
```

The repository's `examples/` folder has `quickstart.py` and `train_numpy.py`,
a small NumPy training loop with a learning-rate sweep, and `get_started.py`, the
script of [Get started](get-started.md).

## Command line

| Command | What it does |
| --- | --- |
| `nuboard up [DIR] [--port 6070] [--host 127.0.0.1] [--open]` | Start the viewer on any folder: one run, one project, or a tree of projects. |
| `nuboard demo [DIR] [--up] [--open]` | Write the demo workspace (default `demo-runs/`). |
| `nuboard ls [DIR] [-q QUERY]` | List runs, filtered with the [query language](reference/query.md). |
| `nuboard compact DIR [--force]` | Write `data.parquet` and health alerts for ended runs that lack them. |
| `nuboard version` | Print the version. |

`python -m nuboard …` works too. The server binds to `127.0.0.1` by default
and only answers requests addressed to localhost. To view runs on a remote
machine, forward the port with `ssh -L 6070:localhost:6070 gpu-box` and run
`nuboard up` there.
