# Importing from TensorBoard

`nuboard import-tensorboard` turns existing TensorBoard logs into NuBoard runs,
so old experiments sit next to new ones in the same viewer and analysis API.

```bash
nuboard import-tensorboard runs/ -p mnist   # the folder you pass to tensorboard --logdir
nuboard up                                  # view them (./experiments by default)
```

```text
imported  baseline/train: 3000 scalars, 12 media, 4 hparams, skipped 40 histograms
imported  baseline/validation: 300 scalars, 0 media
imported  lr3e-4/train: 3000 scalars, 12 media, 4 hparams, skipped 40 histograms
3 run(s) imported into experiments/mnist. View them with: nuboard up experiments
```

It needs neither TensorFlow nor TensorBoard: the event files are decoded with
the standard library, so the command works with a plain `pip install nuboard`.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `LOGDIR` | | the TensorBoard log folder, or a single run folder |
| `-p`, `--project` | the name of `LOGDIR` | project to import into |
| `--dir` | `$NUBOARD_DIR` or `./experiments` | root folder for projects, as in `nb.init` |
| `--tag` | `tensorboard` | tag for the imported runs; repeat it for several |

## What is imported

| TensorBoard | NuBoard |
| --- | --- |
| each folder with `events.out.tfevents.*` files | one run, named after its path under `LOGDIR`, finished at its last event |
| the folder's parent path (`baseline` in `baseline/train`) | the run's group, so `group by group` puts train and validation together |
| scalars (`add_scalar`, `tf.summary.scalar`) | scalars, with the original steps and wall times |
| images | PNG or JPEG images; several images in one summary become `tag/0`, `tag/1`, ... |
| audio | audio clips, playable in the waveform player |
| text | text entries |
| PR curves (`add_pr_curve`, `pr_curve`) | PR curves, with the original counts per threshold |
| hyperparameters (`add_hparams`, `hp.hparams`) | the run's config, so they appear in the table, sweeps and queries |
| histograms, graphs, embeddings, other plugins | skipped, and counted in the output |

Runs keep their original start and end times, so the Timeline page shows when
they actually ran. Each run's notes say which folder it came from.

Writer-specific details:

- **TensorFlow 2 / Keras**: `logs/fit/<run>/train` and `.../validation` become
  two runs in the group `fit/<run>`. Integer scalars (such as a step counter
  logged as `int64`) are imported as numbers.
- **PyTorch `SummaryWriter`**: `add_hparams` writes to a timestamped
  sub-folder; it is folded into its run, so the run gets the hyperparameters
  and the `hparam/...` metrics. `add_scalars("loss", {...})` writes one
  sub-folder per key, as TensorBoard shows them, and each becomes a run.
- **tensorboardX** and **TensorFlow 1**: scalars, images and audio are read
  from the classic summary fields.

## Importing again

Run ids are derived from the source folder and its first event, so importing
the same `LOGDIR` again skips runs that were already imported and adds any new
ones. To re-import a run, delete its folder under `<project>/runs/` first.

A log that ends in a half-written record (a training job that was killed) is
imported up to the last complete event.

## From Python

```python
from nuboard.tensorboard import import_logdir

for result in import_logdir("runs/", "mnist", dir="experiments"):
    print(result.name, result.run_id, result.scalars, result.media, dict(result.ignored))
```

`nuboard.tensorboard.read_events(path)` yields the decoded events of a single
file, if you need to read TensorBoard data without importing it.
