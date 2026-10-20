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

### From the command line

`nuboard artifact add` registers a version without writing Python. Give
everything as flags, as in a script or a cluster job:

```bash
nuboard artifact add datasets/fineweb-edu ~/data/fineweb-edu/2026-10 --ref \
    --type dataset --description "FineWeb-Edu, Oct 2026 snapshot, deduplicated" \
    --meta tokens=12B --meta dedup=true --meta rows=1200000
```

Or run `nuboard artifact add` alone (or with some of the flags) in a
terminal, and it asks for the rest one field at a time. Every answer is
checked as soon as you enter it, so a mistake is caught on the spot and asked
again:

```text
$ nuboard artifact add
Project/name (such as datasets/fineweb-edu): fineweb-edu
  ✗ give the project too, as in datasets/fineweb-edu
Project/name (such as datasets/fineweb-edu): datasets/fineweb-edu
  ✓ will be fineweb-edu:v3
Path (the file or folder; ~ and $VARS work): ~/data/fineweb-edu/2026-10
  ✓ 1,204 files, 812 GB
Store (copy, or reference to leave the files where they are) [copy]: reference
Type (dataset | model | checkpoint | report | other): dataset
Description (what this version is): FineWeb-Edu, Oct 2026 snapshot, deduplicated
Hash every file? (y reads all the data once; n is quick) [n]:
Metadata (optional)
  key=value adds or replaces · 2 key=value edits line 2 · -2 deletes line 2 · key:int=5 sets the type · < back · Enter when done
metadata> tokens=12B
  1  tokens = "12B"  (text)
metadata> rows=1200000
  1  tokens = "12B"  (text)
  2  rows = 1200000  (int)
metadata>

Review
  1  name         datasets/fineweb-edu  (new version v3)
  2  path         ~/data/fineweb-edu/2026-10  (1,204 files, 812 GB)
  3  store        reference
  4  type         dataset
  5  description  FineWeb-Edu, Oct 2026 snapshot, deduplicated
  6  checksum     no
  7  metadata     tokens="12B" (text), rows=1200000 (int)
Write it? y = write · 1-7 = change · < back · q = quit: y
Added datasets/fineweb-edu:v3 (reference, 1,204 files, 812 GB)
Use it with: run.use_artifact("datasets/fineweb-edu:v3")
```

- **`<`** goes back one field; earlier answers are kept as the defaults.
- **Metadata** values are typed as you enter them: whole numbers are ints,
  other numbers floats, `true` and `false` booleans, and the rest text.
  `key:str=0001`, `key:int=…`, `key:float=…`, `key:bool=…` and `key:json=[…]`
  set the type yourself.
- **The review** lists everything; enter a field's number to change it.
  Nothing is written until you answer `y`, and `q` or Ctrl-C leaves without
  writing.

Required are the name, the path, `--ref` or `--copy`, the type (`dataset`,
`model`, `checkpoint`, `report` or `other`) and the description. Without a
terminal, or with `--no-input`, a missing value is an error rather than a
question, and every invalid flag is reported at once. `--meta-file meta.json`
reads metadata from a JSON object, `--checksum` hashes referenced files, and
`--dry-run` checks everything without writing.

`nuboard artifact ls [PROJECT]` lists the versions, and
`nuboard artifact show datasets/fineweb-edu:v3` prints one, with who added
it, and checks that its files are still there and unchanged.

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

### Adding and unlinking versions in the viewer

The Artifacts page is read-only unless the viewer was started with
`nuboard up --edit-artifacts`. With it:

- **New version** opens a form that adds a version as a reference, like
  `nuboard artifact add --ref`. Pick the project, type a new or existing
  name, and give the path of a file or folder: absolute, starting with `~` or
  an environment variable such as `$NUBOARD_DATA_DIR/fineweb-edu`, or relative
  to the served folder. The form checks the path as you type and shows what
  it resolved to, with the file count and size. Add a type, a description,
  metadata (text, number, yes/no or JSON) and, if you want, SHA-256 checksums,
  then review and add. Nothing is copied, and the viewer cannot upload files;
  use `nuboard artifact add --copy` or `nb.add_artifact` for a copy.
- **Unlink version** (or **Unlink all versions**) asks for confirmation, then
  moves the version folder to `artifacts/.unlinked/` in the project. No files
  are deleted, and a referenced dataset is never touched. The version leaves
  the list and `use_artifact`, and runs that used or produced it show it as
  "(unlinked)". Its number is not reused.
- **Show unlinked** lists unlinked versions; **Restore** puts one back.

Deleting data is left to you: remove a folder under `artifacts/.unlinked/`
yourself when you no longer need it.
