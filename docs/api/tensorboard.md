# Coming from TensorBoard

The `add_*` names and arguments follow PyTorch's `SummaryWriter`, so most
calls carry over with the writer replaced by the run:

```python
# TensorBoard
writer = SummaryWriter("runs/baseline")
writer.add_scalar("train/loss", loss, step)

# NuBoard
run = nb.init("my-project", run_name="baseline")
run.add_scalar("train/loss", loss, step)
```

| `SummaryWriter` | NuBoard |
| --- | --- |
| `add_scalar(tag, value, step)` | `run.add_scalar(tag, value, step)` |
| `add_scalars(main, {a: x, b: y}, step)` | `run.add_scalar({main: {"a": x, "b": y}}, step)` |
| `add_image(tag, img, step, dataformats=...)` | `run.add_image(tag, img, step)`, with the layout detected |
| `add_images(tag, batch, step)` | `run.add_image(tag, make_grid(batch), step)` |
| `add_figure(tag, fig, step)` | `run.add_figure(tag, fig, step)`, which also takes Plotly, Altair and Bokeh |
| `add_audio(tag, snd, step, sample_rate)` | `run.add_audio(tag, snd, step, sample_rate=...)` |
| `add_text(tag, text, step)` | `run.add_text(tag, text, step)` |
| `add_histogram(tag, values, step, bins)` | `run.add_histogram(tag, values, step, bins=...)`, where `bins` is a count or the edges |
| `add_pr_curve(tag, labels, predictions, step)` | `run.add_pr_curve(tag, labels, predictions, step)` |
| `add_embedding(mat, metadata)` | `run.add_point_cloud(key, pca3, colors=...)`, after reducing to 3D |
| `add_mesh(tag, vertices)` | `run.add_point_cloud(tag, vertices[0])` |
| `add_hparams(hparams, metrics)` | `nb.init(config=hparams)`; every run's config and scalars are compared in the Runs table and on the [Sweeps page](../guide/sweeps.md) |
| `add_graph(model, input)` | not supported |
| `add_video(tag, vid, step, fps)` | `run.add_video(tag, vid, step, fps=fps)`, which also takes video files |

Logs you already have can be read in directly; see
[Importing from TensorBoard](../guide/tensorboard.md).
