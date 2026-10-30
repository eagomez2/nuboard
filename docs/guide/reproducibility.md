# Reproducibility

Every run records what you need to get back to the code and environment that
produced it: the git commit and any uncommitted changes, the installed
packages, the command line and the machine. This page says what is recorded,
how to replay a run from it, and what it does not cover.

Nothing here needs setting up: `init` records it unless you pass
`capture_env=False`. Recording is best effort. If something cannot be read (no
git, a folder that is not a repository, unreadable package metadata), that part
is left out, with a warning when it is unexpected, and the run starts anyway.

## What is recorded

| What | Where | Notes |
| --- | --- | --- |
| Commit, branch, remote | `run.json` → `git` | The remote URL is stored without any user name, password or token. |
| Uncommitted changes | `files/git.patch` | `git diff HEAD` of tracked files; written only when there are changes. |
| Whether the commit is pushed | `run.json` → `git.pushed` | `false` means no remote-tracking branch contains it. |
| Untracked files | `run.json` → `git.untracked` | How many, never their names or contents. |
| Where the repository was found | `run.json` → `git.source` | `code_dir`, `script` or `cwd`; see below. |
| Installed packages | `files/requirements.txt` | `pip freeze` format; packages installed from git keep their commit. |
| Command line | `files/command.txt` | The Python executable and `sys.argv`, shell-quoted. |
| Machine | `run.json` → `env` | Host, platform, Python version and executable, working directory, GPUs (model, memory, driver), `CUDA_VISIBLE_DEVICES`. |
| Config | `run.json` → `config` | Whatever you passed to `init(config=...)`. |
| Data | `run.json` → `inputs` | Artifact versions used with `use_artifact`, with file hashes. |

All of it is shown in the viewer: open a run and look at **All settings**. A run
whose commit is not on any remote, or that had untracked files, has those
rows highlighted.

## Replaying a run

From the run's folder (`<project>/runs/<run id>/`):

```bash
git clone <git.remote> code && cd code
git checkout <git.commit>
git apply ../files/git.patch                      # only if the file exists
python -m venv .venv && . .venv/bin/activate
pip install -r ../files/requirements.txt
cat ../files/command.txt                          # then run it with this venv's python
```

`command.txt` starts with the Python executable of the machine that ran it;
replace it with `python` from the new environment.

Use the same Python version as `env.python`, and check `env.gpus` and
`env.platform` if the numbers must match exactly. Pin the data with the
artifact versions listed in `inputs`.

## Which repository is recorded

The repository of your training code is looked for in this order, and the
first folder inside a git repository wins:

1. `code_dir`, if you pass it to `init`.
2. The folder of the script that started the process (`python ~/proj/train.py`
   records `~/proj` wherever you run it from).
3. The working directory.

`git.source` says which one was used. When the script's folder and the
working directory are in two different repositories, the script's is recorded
and a warning says so.

Pass `code_dir` when the script is not your code, because the script's folder
then tells nothing about it:

- in a notebook (the "script" is the Jupyter kernel);
- with `python -m some_package` of an installed package, or a command installed
  by pip;
- when a launcher (SLURM, a shell script, Docker, Hydra's `hydra.job.chdir`)
  starts the process somewhere else and the entry point lives outside your
  repository.

```python
run = nb.init("llm", config=cfg, code_dir="~/src/my-trainer")
```

## What is not covered

Some things are deliberately not recorded, because they could hold secrets or
be very large, and others cannot be:

- **Untracked files.** Files you never `git add`ed are not in `git.patch`; only
  their number is recorded. Commit, or at least add, the files a run depends on.
- **Binary changes.** `git.patch` is a text diff; changed binary files show only
  as "Binary files differ".
- **Unpushed commits.** If `git.pushed` is `false`, the commit exists only on
  the machine that ran it. Push it before you rely on the run.
- **Environment variables.** Never recorded: they often hold API keys and
  tokens. Put settings that matter into `config`.
- **Random seeds.** Recorded only if they are in `config`.
- **Data.** Recorded only for artifacts used with `use_artifact`; any other file
  your script reads is unknown to the run.
- **System libraries.** The CUDA toolkit, cuDNN, conda packages and OS packages
  are not listed; only Python packages are. The GPU driver version is.
- **Local installs.** A package installed from a local folder or with
  `pip install -e` is listed as `name==version` with an
  `# editable/local install` comment; its path and state are not recorded.
  Install it from git (`pip install git+https://...`) to keep its commit.

Pass `capture_env=False` to record none of the above, for example when the
runs are shared and the machine details should stay private. The config and
metrics are still recorded.
