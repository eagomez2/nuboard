# `add_file`

```python
run.add_file(path, name=None) -> Path | None
```

Copies a file or folder into the run's `files/` folder. Use it for config
files in whatever format they come in (YAML, TOML, Hydra's `.hydra/` folder),
or any other file worth keeping with the run.

**Parameters**

- **path** (*str or Path*): the file or folder. A folder is copied
  recursively.
- **name** (*str*, optional): where to put it inside `files/`, such as
  `"cfg/train.yaml"`. Subfolders are created. Defaults to the base name of
  `path`.

**Returns** the destination path, or None on ranks other than 0, which do
not copy.

**In the viewer** the run details list every file in `files/`, and Compare
shows a diff of each file between runs.

```python
run.add_file("config.yaml")
run.add_file(".hydra", "hydra")
```
