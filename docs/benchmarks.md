# Benchmarks

How much does logging cost your training, compared with TensorBoard? These
charts compare nuboard with the two usual ways of writing TensorBoard logs from
PyTorch: [tensorboardX](https://github.com/lanpa/tensorboardX) and PyTorch's own
`torch.utils.tensorboard`. Lower is better everywhere.

## During training

What matters most is the time spent **on the training thread**, since that
time is taken directly from your steps. nuboard's `add_scalar` only puts the
values in a queue; a background thread converts and writes them. TensorBoard
writers build a protobuf event for every scalar in the calling thread.

![Logging 50 scalars](assets/benchmarks/scalars_us-light.svg#only-light)
![Logging 50 scalars](assets/benchmarks/scalars_us-dark.svg#only-dark)

The same effect in a training loop: each step does 1 ms of Python work (which
competes for the GIL with any writer thread) and logs 50 scalars.

![Training slowdown](assets/benchmarks/slowdown_pct-light.svg#only-light)
![Training slowdown](assets/benchmarks/slowdown_pct-dark.svg#only-dark)

Images are copied on the training thread and encoded to PNG in the background
(the encoding still takes CPU time, just not in your loop):

![Logging an image](assets/benchmarks/image_ms-light.svg#only-light)
![Logging an image](assets/benchmarks/image_ms-dark.svg#only-dark)

## Writing and reading a million points

Logging 1M scalar points (100k steps of 10 metrics) and closing the writer, so
everything is on disk:

![Writing 1M points](assets/benchmarks/write_1m_s-light.svg#only-light)
![Writing 1M points](assets/benchmarks/write_1m_s-dark.svg#only-dark)

Reading them all back: nuboard's `RunReader` decodes its columnar log with
NumPy; TensorBoard's `EventAccumulator` parses one protobuf event per point.

![Reading 1M points](assets/benchmarks/read_1m_s-light.svg#only-light)
![Reading 1M points](assets/benchmarks/read_1m_s-dark.svg#only-dark)

![1M points on disk](assets/benchmarks/disk_1m_mb-light.svg#only-light)
![1M points on disk](assets/benchmarks/disk_1m_mb-dark.svg#only-dark)

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
uv run --with tensorboardX --with tensorboard --with torch --with matplotlib \
    python benchmarks/vs_tensorboard.py
uv run --with matplotlib python benchmarks/plot_vs_tensorboard.py
```

Each case runs in its own process, and the short ones are repeated three times
(the median is kept). The results above were measured with nuboard 0.20.1,
tensorboardX 2.6.5, PyTorch 2.15.0 and tensorboard 2.21.0 on Python 3.13, on a
4-core Linux machine; the raw numbers are in
`benchmarks/results/vs_tensorboard.json`. Expect other machines to differ in
absolute terms, not in the ratios.
