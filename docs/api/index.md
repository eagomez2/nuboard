# Python API

The `nuboard` package is the logger. You open a run with `nb.init`, which
returns a `Run`. You log numbers with `run.log` and media with the `add_*`
methods. Everything is written to one folder per run, which the viewer
(`nuboard up`) reads. The logging side needs only the standard library. NumPy
comes into play only when you pass arrays yourself.

```python
import nuboard as nb

run = nb.init("mnist", name="baseline", config={"lr": 1e-3, "batch_size": 64})

for step in range(1000):
    loss = 1 / (1 + step / 100)
    run.log({"train/loss": loss}, step=step)

run.add_text("notes", "A first run, with a constant learning rate.")
run.finish()
```

```console
$ nuboard up experiments
```

The pages in this section describe each call in detail: what it accepts, what
it stores, and what the viewer does with it.

- [Runs](run.md): `nb.init`, `run.log`, files, artifacts, finishing, resuming
  and forking.
- [Media](media.md): text, images, audio, figures, PR curves,
  distributions, tables, point clouds and HTML.
- [Get started](../get-started.md) puts them together in a small training
  script, step by step.

## Every call at a glance

| Call | Logs | Shown on |
| --- | --- | --- |
| [`nb.init`](run.md#nbinit) | a new run, its config and environment | Runs |
| [`run.log`](run.md#runlog) | numbers, such as losses and learning rates | Charts |
| [`run.add_text`](media.md#add_text) | strings, such as generated samples | Media › Text |
| [`run.add_image`](media.md#add_image) | images from arrays, tensors, PIL or files | Media › Images |
| [`run.add_audio`](media.md#add_audio) | audio from arrays, tensors or files | Media › Audio |
| [`run.add_figure`](media.md#add_figure) | Plotly, Altair/Vega-Lite, Bokeh and matplotlib figures | Media › Figures |
| [`run.add_pr_curve`](media.md#add_pr_curve) | a precision-recall curve | Media › Figures |
| [`run.add_histogram`](media.md#add_histogram) | the distribution of weights, gradients or any values | Media › Figures |
| [`run.add_table`](media.md#add_table) | per-example results, with audio and image cells | Media › Tables |
| [`run.add_point_cloud`](media.md#add_point_cloud) | 3D points, such as a lidar scan or an embedding | Media › Point clouds |
| [`run.add_html`](media.md#add_html) | an HTML document | Media › HTML |
| [`run.add_file`](run.md#runadd_file) | a file or folder, such as a config file | Run details |
| [`run.add_artifact`](run.md#runadd_artifact) | a versioned dataset or checkpoint | Artifacts |
| [`run.use_artifact`](run.md#runuse_artifact) | that the run used an artifact | Artifacts |
| [`run.finish`](run.md#runfinish) | the run's end and status | Runs |

## Conventions

These hold for every call on this page and the next two.

**Keys.** A key names a series, such as `train/loss` or `samples/recon`. The
part before the first `/` groups keys in the viewer: `train/loss` and
`train/acc` are drawn in a `train` section. Any characters work, and metrics
and media can share a prefix.

**Steps.** `run.log` without `step` uses one more than its previous step, as
TensorBoard's global step does. The `add_*` methods without `step` use the step
of the latest `run.log` call, so media logged right after the metrics of a step
lands on that step. Pass `step` explicitly when it matters, such as for an
evaluation every few epochs.

**Time.** Every call takes a keyword-only `time=`, a Unix timestamp, for when
the value was logged. It defaults to now. The TensorBoard importer uses it to
keep the original wall times.

**Arrays and tensors.** Wherever an array is accepted, a PyTorch tensor works
too. It is detached and moved to the CPU. Arrays are copied before the call
returns, so you can reuse the buffer right away. The encoding (PNG, WAV,
binning) happens on a background thread.

**Non-blocking.** No call waits for the disk. Each one appends to a queue
that a background thread writes out every `flush_interval` seconds (one by
default). `run.flush()` waits for everything queued so far.

**Ranks.** In distributed training only rank 0 logs, unless you pass
`all_ranks=True` to `nb.init`, `run.log` or `run.add_text`. Media are always
logged by rank 0 only. See [Distributed training](../guide/distributed.md).

**Where it goes.** A run is the folder
`<dir>/<project>/runs/<YYYYMMDD-HHMM>_<name>_<rand>/`. Numbers and text go to
`events.r0.s0.log`, media bytes to `media.r0.pack`. The
[file format](../reference/format.md) describes both. Copying the folder
copies the run.
