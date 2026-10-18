# Artifacts: `add_artifact`, `use_artifact`, `get_artifact`

Artifacts are versioned datasets, checkpoints and reports. A version either
holds a copy of the files or is a **reference** to files that stay where they
are. See [Artifacts and lineage](../guide/artifacts.md) for how to organize
them.

## `add_artifact`

```python
run.add_artifact(name, path, *, type=None, metadata=None, reference=False, checksum=False) -> Artifact
```

Adds a new version of an artifact and records this run as its producer.
Versions are numbered automatically and created atomically.

**Parameters**

- **name** (*str*): the artifact's name, such as `"model"`. A project before
  a `/`, as in `"datasets/fineweb-edu"`, adds the version to that project
  instead of the run's own.
- **path** (*str or Path*): the file or folder to copy, or to reference.
- **type** (*str*, optional): a free-form type, such as `"checkpoint"` or
  `"dataset"`.
- **metadata** (*dict*, optional): extra data for the manifest, such as the
  step or a score.
- **reference** (*bool*): record where `path` is instead of copying it. Each
  file's size and modification time are stored, which takes a moment even
  for terabytes. Use it for data that lives on shared storage. A path inside
  `$NUBOARD_DATA_DIR`, or one written with an environment variable such as
  `"${DATA}/fineweb"`, is stored with the variable and expanded on the
  machine that uses it; see
  [Data on several machines](../guide/artifacts.md#data-on-several-machines).
- **checksum** (*bool*): with `reference`, also hash every file (SHA-256).
  This reads all of the data once. Copies are always hashed.
- **description** (*str*, optional): what this version is, shown on the
  Artifacts page. The manifest also records who created the version, on
  which machine and with which command (`created_by`).

**Returns** an `Artifact` with `ref` (such as `"model:v3"`), `files` (the
folder holding the files), `reference` (the referenced path, or None for a
copy) and `manifest` (a size, and a sha256 or modification time, per file;
the type, the metadata and the producing run).

The copy happens on the calling thread, so avoid it inside a hot loop with
large checkpoints.

## `use_artifact`

```python
run.use_artifact(ref) -> Artifact
```

Finds an artifact version and records it as an input of this run, so the
[Artifacts page](../guide/artifacts.md) can show which runs used which data.

- **ref** (*str*): `"name"` or `"name:latest"` for the newest version, or
  `"name:v2"` for a given one. Put a project first to use another project's
  artifact: `"datasets/fineweb-edu:v2"`. Projects are found in the same root
  folder as the run's project.

The files are checked against the manifest by size, without reading them. A
missing file, a file whose size changed, or an unset variable in a reference
gives a warning naming it, so data that was modified or moved after it was
registered does not go unnoticed.

Load the data from `artifact.files`, a path: NuBoard does not open or
unpickle anything.

```python
data = run.use_artifact("datasets/fineweb-edu:v2")
train_set = MyDataset(data.files / "train")
```

## `nb.add_artifact`

```python
nb.add_artifact(project, name, path, *, type=None, metadata=None,
                reference=False, checksum=False, dir=None) -> Artifact
```

Adds a version without a run, such as a dataset you downloaded or a folder
on shared storage. The version has no producer. The parameters are those of
`run.add_artifact`, plus the **project** to add it to and the root folder
**dir**, as in [`nb.init`](init.md).

## `nb.get_artifact`

```python
nb.get_artifact(ref, *, dir=None) -> Artifact
```

Finds a version without recording anything, such as in a notebook. `ref`
names the project: `"datasets/fineweb-edu:v2"`. Without one, the `"default"`
project is used, as in `nb.init`. Missing or changed files give a warning,
as with `use_artifact`.

## `Artifact.verify`

```python
artifact.verify() -> list[str]
```

Returns one line per file that is missing (`"missing: train.txt"`) or
changed (`"changed: train.txt"`) since the version was made; empty when all
match, or one line naming an environment variable the reference needs that
is not set. It compares sizes only: modification times are recorded, but a
copy of the data on another machine has its own.

**Example**

```python
from pathlib import Path

import nuboard as nb

data = Path("shared/labels")  # on your shared storage, outside the projects
data.mkdir(parents=True, exist_ok=True)
(data / "labels.txt").write_text("cat\ndog\n")

# registered once, without a run; nothing is copied
nb.add_artifact("datasets", "labels", data, type="dataset",
                metadata={"classes": 2}, reference=True)

with nb.init("api-tour", name="artifacts") as run:
    labels = run.use_artifact("datasets/labels:latest")
    print(labels.ref, labels.files)  # labels:v1 /…/shared/labels

    with open("model.bin", "wb") as f:
        f.write(b"weights")

    v = run.add_artifact("model", "model.bin", type="checkpoint", metadata={"step": 100})
    print(v.ref)  # model:v1, then model:v2, ...
```
