# Python API

The `nuboard` package is the logger. You open a run with `nb.init`, which
returns a `Run`. You log scalars with `run.add_scalar` and everything else with
the other `add_*` methods, named as in TensorBoard's `SummaryWriter`.
Everything is written to one folder per run, which the viewer (`nuboard up`)
reads. The logging side needs only the standard library. NumPy comes into play
only when you pass arrays yourself.

```python
import nuboard as nb

run = nb.init("mnist", run_name="baseline", config={"lr": 1e-3, "batch_size": 64})

for step in range(1000):
    loss = 1 / (1 + step / 100)
    run.add_scalar("train/loss", loss, step=step)

run.add_text("notes", "A first run, with a constant learning rate.")
run.finish()
```

```console
$ nuboard up experiments
```

Each method has its own page in this section, listed in the menu. A page gives
the method's signature and parameters, the shapes and types it accepts, what it
stores and how big, what the viewer does with it, and a complete example with a
picture of the result. [Get started](../get-started.md) puts them together in
a small training script, and
[Coming from TensorBoard](tensorboard.md) maps each `SummaryWriter` method to
NuBoard.

## Every method at a glance

| Method | Logs | Shown on |
| --- | --- | --- |
| [`nb.init`](init.md) | a new run, its config and environment | Runs |
| [`add_scalar`](add_scalar.md) | one scalar or several, such as losses and learning rates | Charts |
| [`add_scalar_baseline`](add_scalar_baseline.md) | a reference value for a scalar, such as the score of the unprocessed input | Charts (dashed line) |
| [`add_text`](add_text.md) | strings, such as generated samples | Media › Text |
| [`add_image`](add_image.md) | images from arrays, tensors, PIL or files | Media › Images |
| [`add_audio`](add_audio.md) | audio from arrays, tensors or files | Media › Audio |
| [`add_video`](add_video.md) | video from arrays, tensors or files | Media › Video |
| [`add_figure`](add_figure.md) | Plotly, Altair/Vega-Lite, Bokeh and matplotlib figures, and waveforms with signals (`nb.WaveformFigure`) | Media › Figures |
| [`add_pr_curve`](add_pr_curve.md) | a precision-recall curve | Media › Figures |
| [`add_histogram`](add_histogram.md) | the distribution of weights, gradients or any values | Media › Figures |
| [`add_table`](add_table.md) | per-example results, with audio and image cells | Media › Tables |
| [`add_point_cloud`](add_point_cloud.md) | 3D points, such as a lidar scan or an embedding | Media › Point clouds |
| [`add_html`](add_html.md) | an HTML document | Media › HTML |
| [`add_file`](add_file.md) | a file or folder, such as a config file | Run details |
| `nb.init(system_metrics=...)` | [CPU, memory and GPU use](init.md#system-scalars) as `system/` scalars | Charts |
| `nb.init(capture_console=...)` | [what the script prints](init.md#console-output) | Run details › Console |
| [`add_artifact`, `use_artifact`](add_artifact.md) | versioned datasets and checkpoints, copied or referenced, and which runs used them | Artifacts |
| [`nb.add_artifact`, `nb.get_artifact`](add_artifact.md#nbadd_artifact) | the same without a run, such as a shared dataset | Artifacts |
| [`finish`, `flush`, `summary`](finish.md) | the run's end and status | Runs |

## Conventions

These hold for every method in this section.

**Keys.** A key names a series, such as `train/loss` or `samples/recon`. The
part before the first `/` groups keys in the viewer: `train/loss` and
`train/acc` are drawn in a `train` section. Any characters work, and scalars
and media can share a prefix.

**Steps.** `add_scalar` without `step` uses one more than its previous step,
as TensorBoard's global step does. The other `add_*` methods without `step` use
the step of the latest `add_scalar` call, so media logged right after the
scalars of a step lands on that step. Pass `step` explicitly when it matters,
such as for an evaluation every few epochs.

**Time.** Every method takes a keyword-only `time=`, a Unix timestamp, for
when the value was logged. It defaults to now. The TensorBoard importer uses
it to keep the original wall times.

**Arrays and tensors.** Wherever an array is accepted, a PyTorch tensor works
too, on any device and in any dtype. Before the call returns, a tensor is
detached, moved to the CPU and copied into a NumPy array (`bfloat16` becomes
`float32`), and an array is copied, so you can change or reuse the buffer
right away. The encoding (PNG, WAV, binning) happens on a background thread.
Scalars are the exception: `add_scalar` keeps a 0-d tensor as it is and
reads it on the background thread, so the training loop does not wait for
the GPU.

**Non-blocking.** No call waits for the disk. Each one appends to a queue
that a background thread writes out every `flush_interval` seconds (one by
default). [`flush`](finish.md#flush) waits for everything queued so far.

**Ranks.** In distributed training only rank 0 logs; the calls are no-ops on
other ranks. See [Distributed training](../guide/distributed.md).

**Where it goes.** A run is the folder
`<dir>/<project>/runs/<YYYYMMDDTHHMM>-<hash>/`. Scalars and text go to
`events.r0.s0.log`, media bytes to `media.r0.pack`, indexed by frames in the
event log. The [file format](../reference/format.md) describes both. Copying
the folder copies the run.

**The examples** in this section are complete scripts. Each one writes a run
to the `api-tour` project, which you can open with `nuboard up experiments`.
The pictures under **Expected result** were taken from those runs.
