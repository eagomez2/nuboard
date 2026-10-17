# Artifacts and lineage

Artifacts are versioned datasets, tokenizers, checkpoints and evaluation
reports. Each version records the run that produced it, and each run records
the versions it used, so for any result you can trace the model and the data
behind it.

## Organizing them

A layout that scales to many projects sharing the same data:

- **A `datasets` project** holds your datasets as *references*: NuBoard
  records where the files are and a fingerprint of each one, and copies
  nothing. The data stays on your storage.
- **Each training project** uses them by name, `"datasets/<name>:v<N>"`, and
  saves its checkpoints and reports as its own artifacts.
- **One name per kind of thing** (`fineweb-edu`, `tokenizer`, `model`), with
  new versions piling up under it. Put what describes a version (rows, step,
  score) in `metadata`, not in the name.

```text
experiments/
  datasets/artifacts/            only manifests: where the data is, and its fingerprint
    fineweb-edu/v1/manifest.json     → /data/fineweb-edu/2026-09
    fineweb-edu/v2/manifest.json     → /data/fineweb-edu/2026-10
    imagenet-100/v1/manifest.json    → /data/imagenet-100
  llm-pretrain/
    runs/…                       each run lists datasets/fineweb-edu:v2 as an input
    artifacts/model/v1/          checkpoints are copied: files/model.safetensors
  vit-ablations/
    runs/…                       each run lists datasets/imagenet-100:v1 as an input
```

## Registering data

Data that no script produced, such as a download or a folder prepared by
hand, is registered without a run:

```python
import nuboard as nb

nb.add_artifact("datasets", "imagenet-100", "/data/imagenet-100", type="dataset",
                metadata={"classes": 100}, reference=True)
```

Data that a script prepares is registered from that script's run, which then
shows as its producer:

```python
with nb.init("llm-pretrain", name="prepare-data", tags=["data"]) as run:
    ...  # write /data/fineweb-edu/2026-10
    run.add_artifact("datasets/fineweb-edu", "/data/fineweb-edu/2026-10",
                     type="dataset", metadata={"tokens": "12B"}, reference=True)
```

A reference stores each file's size and modification time, which takes a
moment even for terabytes. Add `checksum=True` to also hash every file, which
reads all of the data once.

## Using them

```python
with nb.init("llm-pretrain", name="lr1e-3-s1") as run:
    data = run.use_artifact("datasets/fineweb-edu:v2")  # or ":latest"
    train(MyDataset(data.files / "train"))
    run.add_artifact("model", "ckpt/final.safetensors", type="checkpoint",
                     metadata={"step": 25000})
```

`use_artifact` returns an `Artifact` whose `files` is a path; NuBoard does not
open or unpickle anything, so you load the data with your own code.
Before returning, it compares the files with the manifest by size and
size, and warns about any that are missing or changed since the version was
registered. Inside the run's own project, the project can be left
out: `run.use_artifact("model:v1")`.

To find a version without recording it, such as in a notebook, use
`nb.get_artifact("datasets/fineweb-edu:v2")`.

## Data on several machines

When the data has a copy on each machine, such as on a laptop for evaluation
and on a cluster for training, set `NUBOARD_DATA_DIR` on each one to the
folder that holds the datasets there:

```bash
export NUBOARD_DATA_DIR=~/data          # laptop
export NUBOARD_DATA_DIR=/scratch/data   # cluster
```

A reference to a path inside that folder is stored relative to it, as
`${NUBOARD_DATA_DIR}/fineweb-edu/2026-10`, and `artifact.files` points at the
copy of the machine that runs the script. Registered once, the same
`datasets/fineweb-edu:v2` works on both. Any other environment variable
works too when written in the path:

```python
nb.add_artifact("datasets", "imagenet-100", "${IMAGENET}/train", reference=True)
```

The copies are compared by size only, since copying gives files new
modification times. If a variable is not set where the artifact is used,
`use_artifact` warns and names it.

## Copies or references

| | Copy (default) | Reference (`reference=True`) |
| --- | --- | --- |
| Where the files are | `<project>/artifacts/<name>/v<N>/files/` | where they were |
| Disk | a second copy | nothing beyond the manifest |
| If the source is deleted or changed | the version is unaffected | `use_artifact` warns |
| Fingerprint | SHA-256 | size and modification time, SHA-256 with `checksum=True` |
| On another machine | the same files | that machine's copy, through `$NUBOARD_DATA_DIR` |
| Good for | checkpoints, reports, small datasets | datasets on shared storage |

## The Artifacts page

![Artifacts page with a lineage graph](../assets/artifacts-light.png){ .nb-shot }

- **List**: every artifact, newest version first, with its project, type and
  age. With a project selected, it shows that project's artifacts and those
  its runs used from other projects.
- **Version**: type, whether it is a copy or a reference, creation time,
  size, file count, how many runs used it, and the `use_artifact` line to copy
  into a script.
- **Lineage**: upstream on the left, downstream on the right. For
  `fineweb-edu:v2` in the demo that is the run that prepared it, the twelve
  training runs that used it, the checkpoint one of them saved, and the
  evaluation that loaded the checkpoint. Click an artifact to move the graph to
  it, or a run to open it.
- **Produced by / Used by**, **Metadata** and **Files** (path, size, hash),
  plus where the files are on disk. A version added with `nb.add_artifact`
  shows "Logged outside a run".

The Timeline page marks each artifact version as a diamond on the run that
produced it.
