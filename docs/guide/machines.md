# Working on several machines

A project logged on two machines, such as `project_a` on a laptop and
`project_a` on a GPU box, ends up as two folders. Copy the other machine's
folder over (or mount it), then merge it into yours:

```console
$ rsync -a gpu-box:experiments/ ~/gpu-runs/
$ nuboard merge ~/gpu-runs ~/experiments
```

`nuboard merge SRC DEST` brings into `DEST` everything of `SRC` that `DEST`
lacks. Projects are matched by their path, so `SRC/project_a` goes into
`DEST/project_a`: give two roots, or two project folders. It never overwrites
or deletes anything, and it does not need the network.

## The plan comes first

Before writing anything, `merge` shows every action and asks:

```console
$ nuboard merge ~/gpu-runs ~/experiments
Merging /home/me/gpu-runs into /home/me/experiments

project_a
  runs         + 18 to copy                         lr1e-3-s4, lr3e-4-s1, lr3e-4-s2, ... (list with -v)
               ! 20261030T0707-3011203a (lr1e-3)    same id, different files: skipped
               = 12 nothing to do                   ...
  artifacts    ! fineweb-edu:v3                     copied as v4 (DEST has a different v3); copied runs repointed
  collections  ~ collections/best.json              3 run ids added
  reports      + reports/ablations.md               new
               ! reports/notes.md                   both differ: SRC's saved as notes-from-gpu-runs.md

Total: 18 run(s), 1 artifact version(s) and 2 file(s) to write.
1 conflict(s) skipped and 2 renamed or renumbered item(s) need your attention (see ! above).
Nothing has been written yet. Apply this merge? [y/N]
```

`+` is copied, `~` updated or combined, `=` nothing to do, and `!` needs a
look: a conflict that is skipped, or something copied under a new name or
number.

| Option | |
| --- | --- |
| `-v`, `--verbose` | List every run and file instead of counting them. |
| `--dry-run` | Show the plan and exit. The exit code is 1 when there are conflicts. |
| `-y`, `--yes` | Apply without asking. Without a terminal, `merge` refuses unless this is given. |
| `--json` | Print the plan as JSON. |
| `--project NAME` | Only this project (its path inside SRC). |
| `--include-running` | Also copy runs that are still logging in SRC. |

What is applied is exactly the plan you saw: if either folder changes before
you answer (a run finishes, a report is edited), nothing is written and you are
asked to run it again. Running the same merge twice shows nothing to do the
second time.

## What happens to each kind of file

| What | Rule |
| --- | --- |
| Runs | Copied when DEST has no run with that id. Identical runs are skipped. When the same run differs, the later copy wins if one side only has more (more files, longer logs, a newer heartbeat); DEST's older copy is then kept in `<project>/.merge-replaced/`. Otherwise it is a conflict and skipped. Runs still logging are skipped unless `--include-running`. |
| Run notes, tags, stars | For a run on both sides: tags joined, starred, archived and reviewed if either is, the newer notes, DEST's property values first. |
| Artifacts | A version with the same files as one in DEST is skipped. A version whose number is free is copied as it is. A version whose number DEST uses for different files gets the next free number, and the runs copied by the merge are pointed at it. Unlinked versions stay behind. |
| Collections | Their run ids are joined. |
| Reports, views | Copied when missing. When both differ, DEST's stays and SRC's is copied next to it as `<name>-from-<SRC folder>`. Report files are named by their content, so they copy freely. |
| `sweeps.json` | Hide rules that only exclude are combined; otherwise DEST's are kept. |
| `fields.json` | Properties DEST lacks are added; one defined differently on each side keeps DEST's definition. |

Each run and artifact version is copied to `<project>/.merge-tmp/` and then
moved into place, so a viewer open on DEST never shows a half-copied run.
