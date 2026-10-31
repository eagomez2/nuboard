# Benchmarks

How much does logging cost your training, compared with TensorBoard? These
charts compare nuboard with the two usual ways of writing TensorBoard logs from
PyTorch: [tensorboardX](https://github.com/lanpa/tensorboardX) and PyTorch's own
`torch.utils.tensorboard`. Lower is better everywhere. Hover a bar for its
exact value and how many times nuboard's it is; the log scale makes nuboard's
bars visible next to the others.

## During training

What matters most is the time spent **on the training thread**, since that
time is taken directly from your steps. nuboard's `add_scalar` only puts the
values in a queue; a background thread converts and writes them. TensorBoard
writers build a protobuf event for every scalar in the calling thread.

<div class="nb-bench" data-case="scalars_us" data-title="Logging 50 scalars, time on the training thread" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

The same effect in a training loop: each step does 1 ms of Python work (which
competes for the GIL with any writer thread) and logs 50 scalars.

<div class="nb-bench" data-case="slowdown_pct" data-title="Throughput lost: 1 ms steps, 50 scalars per step" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

Images are copied on the training thread and encoded to PNG in the background
(the encoding still takes CPU time, just not in your loop):

<div class="nb-bench" data-case="image_ms" data-title="Logging a 256×256 image, time on the training thread" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

## Writing and reading a million points

Logging 1M scalar points (100k steps of 10 metrics) and closing the writer, so
everything is on disk:

<div class="nb-bench" data-case="write_1m_s" data-title="Writing 1M points until they are on disk" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

Reading them all back: nuboard's `RunReader` decodes its columnar log with
NumPy; TensorBoard's `EventAccumulator` parses one protobuf event per point.

<div class="nb-bench" data-case="read_1m_s" data-title="Reading 1M points back" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

<div class="nb-bench" data-case="disk_1m_mb" data-title="Size of 1M points on disk" data-src="../assets/benchmarks/vs_tensorboard.json"></div>

## Where nuboard costs time

The numbers above are the common case. Know these too:

- **`finish()` compacts the run into Parquet** in a single-process run. It
  takes about 2 s per million points and holds them in memory while it works
  (20M points: about 30 s and 2.4 GB). Pass `nb.init(..., compact=False)` to
  skip it; the viewer reads the event log directly. Multi-GPU runs never
  compact at `finish()`.
- **Very fast steps with many metrics.** The writer thread holds the GIL for
  about 0.8 µs per point it writes. That is invisible at normal step times, but
  logging 50 metrics every 100 µs step costs about 40% of the throughput.
  TensorBoard writers are slower still in that case.
- **`init` records git and the installed packages** (about 0.1 s in a small
  repository, up to several seconds in a huge one or with many editable
  installs). Pass `capture_env=False` to skip it.

## Reproduce

```bash
uv run --with tensorboardX --with tensorboard --with torch \
    python benchmarks/vs_tensorboard.py
```

Each case runs in its own process, and the short ones are repeated three times
(the median is kept). The results above were measured with nuboard 0.20.1,
tensorboardX 2.6.5, PyTorch 2.15.0 and tensorboard 2.21.0 on Python 3.13, on a
4-core Linux machine. The script writes the raw numbers to
`docs/assets/benchmarks/vs_tensorboard.json`, which these charts read, so a
new run updates the page. Expect other machines to differ in
absolute terms, not in the ratios.
