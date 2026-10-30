# Command line

Every command, with its options and defaults. `python -m nuboard …` works the
same as `nuboard …`, and `nuboard COMMAND -h` prints the options of a command.

Commands that take a folder default to `$NUBOARD_DIR`, or `./experiments` if
it is not set. A folder can be a tree of projects, one project or one run.

| Command | What it does |
| --- | --- |
| [`up`](#up) | start the viewer |
| [`demo`](#demo) | write a demo workspace, optionally with a live run |
| [`ls`](#ls) | list runs, optionally filtered by a query |
| [`rm`](#rm) | delete runs chosen by a query or id |
| [`compact`](#compact) | write `data.parquet` for ended runs |
| [`merge`](#merge) | merge the projects of one folder into another |
| [`import-tensorboard`](#import-tensorboard) | import TensorBoard logs as runs |
| [`artifact`](#artifact) | add, list, show, unlink and restore artifact versions |
| [`version`](#version) | print the version |

## up

```bash
nuboard up [DIR] [options]
```

Start the viewer on `DIR`. If the port is taken, the next free one (up to 19
further) is used.

| Option | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | interface to listen on; off localhost an access token is needed |
| `--port` | `6070` | port to listen on |
| `--open` | | open a browser tab |
| `--token VALUE` | `$NUBOARD_TOKEN`, or random off localhost | access token; the printed link signs a browser in |
| `--no-token` | | serve a non-local `--host` without a token (anyone who reaches it can use it) |
| `--edit-artifacts` | | allow adding artifact versions (references to paths on the server) and unlinking them in the viewer |
| `--read-only-reports` | | refuse every change to reports, uploads included (for a shared server) |
| `--max-image-mb` | `20` | size limit of an image uploaded into a report |
| `--max-text-mb` | `5` | size limit of a text file uploaded into a report |
| `--max-audio-mb` | `50` | size limit of an audio file uploaded into a report |

See [Using the viewer](../guide/viewer.md) and
[Sharing on a network](../guide/viewer.md#sharing-on-a-network).

## demo

```bash
nuboard demo [DIR] [--up] [--port 6070] [--open] [--edit-artifacts]
```

Write the demo workspace to `DIR` (default `demo-runs`). Run again on the same
folder, it opens the demo already there; delete the folder for a fresh one.
`--up` starts the viewer on it with a run that keeps logging, and the other
options are as for `up`.

## ls

```bash
nuboard ls [DIR] [-q QUERY]
```

Print the status, project and id of every run, or of the runs matching
`QUERY` in the [query language](query.md):

```bash
nuboard ls -q 'status = crashed'
nuboard ls experiments/mnist -q 'config.lr < 1e-3 and tags has "baseline"'
```

## rm

```bash
nuboard rm [DIR] (-q QUERY | --run ID_OR_NAME …) [options]
```

Delete runs. Runs are chosen by a query, by id or name (`--run`, repeatable),
or both, in which case a run must match both. With neither, nothing is
deleted, so the command can never delete every run by accident.

The runs are listed first with their sizes, and nothing is deleted until you
confirm:

```text
$ nuboard rm -q 'tags has "debug"'
Deleting runs under /home/me/experiments

  - crashed   mnist                20261030T1015-3f9a0c21  debug-1  (12.4 MB)
  - finished  mnist                20261030T1022-81cc5e07  debug-2  (11.9 MB)
      produced corpus:v3 (the versions are kept)
  ! running   mnist                20261030T1100-a1b2d9f4  skipped (pass --include-running)

Total: 2 run(s), 24.3 MB
This cannot be undone. Delete these runs? [y/N]
```

| Option | Meaning |
| --- | --- |
| `-q`, `--query` | runs to delete, as in `ls` |
| `--run` | a run id or name; repeat for several. Names that match no run are reported |
| `--dry-run` | list the runs and exit |
| `-y`, `--yes` | delete without asking; without it and without a terminal, nothing is deleted |
| `--include-running` | also delete runs that are still logging (skipped by default) |

Artifact versions a deleted run produced are kept. Each run folder is moved
out of `runs/` before it is removed, so a run is never left half deleted.
Exit codes: 0 when done or nothing to delete, 2 on an error or when not
confirmed.

To hide runs without deleting them, select them on the Runs page and press
**Archive**; **Show archived** brings them back.

## compact

```bash
nuboard compact DIR [--force]
```

Write `data.parquet` and health alerts for ended runs that lack them. Runs are
compacted when they finish, so this is for runs that were killed or logged by
an older version. `--force` also compacts runs that look still running.

## merge

```bash
nuboard merge SRC DEST [options]
```

Copy into `DEST` what the projects of `SRC` have and `DEST` lacks: runs,
artifact versions, reports, views, collections and project settings. The full
plan is shown first and nothing is written until you confirm. Nothing is
overwritten or deleted.

| Option | Meaning |
| --- | --- |
| `--project PATH` | only this project (its path inside `SRC`) |
| `--dry-run` | show the plan and exit (exit code 1 if it has conflicts) |
| `-y`, `--yes` | apply without asking |
| `-v`, `--verbose` | list every item instead of counting identical ones |
| `--json` | print the plan as JSON |
| `--include-running` | also copy runs still logging in `SRC` |

See [Working on several machines](../guide/machines.md).

## import-tensorboard

```bash
nuboard import-tensorboard LOGDIR [-p PROJECT] [--dir DIR] [--tag TAG …]
```

Import every folder of TensorBoard event files under `LOGDIR` as a run, into
`PROJECT` (default: the name of `LOGDIR`). `--tag` sets the tags of the
imported runs (default `tensorboard`). Runs imported before are skipped. See
[Importing from TensorBoard](../guide/tensorboard.md).

## artifact

```bash
nuboard artifact add [PROJECT/NAME] [PATH] [options]
nuboard artifact ls [PROJECT] [--unlinked]
nuboard artifact show PROJECT/NAME[:latest|:vN]
nuboard artifact unlink PROJECT/NAME:vN        # or PROJECT/NAME --all
nuboard artifact restore PROJECT/NAME:vN
```

Every `artifact` command takes `--dir DIR`, the root folder for projects.

| Option of `add` | Meaning |
| --- | --- |
| `--ref` | record where the files are |
| `--copy` | store a copy of the files |
| `-t`, `--type` | `dataset`, `model`, `checkpoint`, `report` or `other` |
| `-d`, `--description` | what this version is |
| `-m`, `--meta KEY=VALUE` | metadata; repeat for several; `KEY:int=VALUE` sets the type |
| `--meta-file` | a JSON object of metadata |
| `--checksum` | with `--ref`, also hash every file |
| `--dry-run` | check and show, but write nothing |
| `--no-input` | never ask; missing values are errors |

`add` asks for what is missing when run in a terminal. `unlink` hides a
version without deleting anything and `restore` brings it back. See
[From the command line](../guide/artifacts.md#from-the-command-line).

## version

```bash
nuboard version
```

Print the installed version.
