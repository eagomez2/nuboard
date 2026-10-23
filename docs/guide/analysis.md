# Analysis API

The analysis API returns Apache Arrow tables, which convert to pandas or
Polars in one call. It needs the viewer extra (`pip install "nuboard[viewer]"`).

```python
import nuboard as nb

project = nb.load("llm-pretrain")  # a project name (under $NUBOARD_DIR / ./experiments)
project = nb.load("~/exp/llm-pretrain")  # or any folder path
project = nb.load("llm-pretrain", dir="~/exp")

runs = project.runs('where tags has "sweep" and status = finished')
for r in runs:
    print(r.id, r.config["optim"]["lr"], r.summary["train/loss"]["min"])

# properties, collections and health alerts set in the viewer
for r in project.runs('collections has "shortlist"'):
    print(r.name, r.fields.get("verdict"), r.collections, [a["message"] for a in r.alerts()])

# a table logged with add_table, one dict per row (the last step, or step=...)
worst = sorted(project.runs()[0].table("eval/samples"), key=lambda r: r["pesq"])[:5]

# notes added to audio in the viewer, by "<media key>@<step>"
print(project.runs()[0].audio_notes.get("eval/enhanced@30", []))

# write a property value (None removes it); a running viewer picks it up
project.runs("where config.optim.lr = 1e-3")[0].set_field("verdict", "keep")

# one scalar across runs, long format: run_id, name, step, time, value, config.optim.lr
table = project.scalars("train/loss", group_by="config.optim.lr", query="where tags has sweep")
df = table.to_pandas()
df.groupby(["config.optim.lr", "step"]).value.mean().unstack(0).plot()

# one row per run: id, name, status, flattened config, last value of every scalar
summary = project.summary().to_pandas()

# all scalars of one run
run = project.run("20261013T0720-755037e9")
run.scalars()  # columns key, step, time, value
run.scalars("train/loss")
```

Collections can be edited from Python too:

```python
from nuboard.collection import list_collections, save_collection

save_collection("experiments/llm-pretrain", "shortlist", add=[r.id for r in runs[:3]])
list_collections("experiments/llm-pretrain")  # [{"name": "shortlist", "runs": [...], ...}]
```

## Lower-level reader

`nuboard.reader.RunReader` reads one run folder directly and is what the
server uses:

```python
from nuboard.reader import RunReader

r = RunReader("experiments/llm-pretrain/runs/20261013T0720-755037e9")
r.scalar_names()  # rank 0 by default
steps, times, values = r.scalars("train/loss")
r.scalars("grad_norm", rank=3)  # another rank
r.texts("samples/gen")  # TextEntry(key, step, time, text)
for m in r.media("samples/recon"):
    png = r.read_media(m)
r.refresh()  # read bytes appended since the last call (live runs)
```

It uses `data.parquet` when it covers every byte of the logs, and otherwise
decodes the event logs incrementally with `np.frombuffer`.
