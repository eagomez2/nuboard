# `add_artifact` and `use_artifact`

## `add_artifact`

```python
run.add_artifact(name, path, *, type=None, metadata=None) -> Artifact
```

Copies a file or folder into a new version of an artifact, in
`<project>/artifacts/<name>/v<N>/`, and records this run as its producer.
Versions are numbered automatically and created atomically.

**Parameters**

- **name** (*str*): the artifact's name, such as `"model"`.
- **path** (*str or Path*): the file or folder to copy.
- **type** (*str*, optional): a free-form type, such as `"checkpoint"` or
  `"dataset"`.
- **metadata** (*dict*, optional): extra data for the manifest, such as the
  step or a score.

**Returns** an `Artifact` with `ref` (such as `"model:v3"`), `files` (the
folder holding the copy) and `manifest` (a sha256 and size per file, the type,
the metadata and the producing run).

The copy happens on the calling thread, so avoid it inside a hot loop with
large checkpoints.


## `use_artifact`

```python
run.use_artifact(ref) -> Artifact
```

Finds an artifact version and records it as an input of this run, so the
[Artifacts page](../guide/artifacts.md) can show which runs used which data.

- **ref** (*str*): `"name"` or `"name:latest"` for the newest version, or
  `"name:v2"` for a given one.

```python
import nuboard as nb

with nb.init("api-tour", name="artifacts") as run:
    with open("labels.txt", "w") as f:
        f.write("cat\ndog\n")

    v = run.add_artifact("labels", "labels.txt", type="dataset", metadata={"classes": 2})
    print(v.ref)  # labels:v1, then labels:v2, ...
    print(run.use_artifact("labels:latest").files)
```
