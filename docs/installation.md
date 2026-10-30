---
hide:
  - navigation
---

# Installation

NuBoard needs **Python 3.10 or newer** on Linux, macOS or Windows. One install
gives the logging API, the viewer (`nuboard up`) and the analysis API, with
NumPy, PyArrow, Starlette and uvicorn. Logging from a training script uses only
the standard library, so it never imports them.

## From PyPI

The package comes with the viewer already built inside it, so installing it
needs no Node.js:

=== "pip"

    ```bash
    pip install nuboard
    ```

=== "uv"

    ```bash
    uv pip install nuboard     # into the current environment
    uv add nuboard             # or as a dependency of a uv project
    uv tool install nuboard    # or only the nuboard command, in its own environment
    ```

Install it in the environment your training scripts run in, so they can
`import nuboard`.

To try the demo without installing anything into an environment of yours:

=== "pip"

    ```bash
    pipx run nuboard demo demo-runs --up --open
    ```

=== "uv"

    ```bash
    uvx nuboard demo demo-runs --up --open
    ```

To upgrade later:

=== "pip"

    ```bash
    pip install -U nuboard
    ```

=== "uv"

    ```bash
    uv pip install -U nuboard   # uv add nuboard --upgrade-package nuboard, or uv tool upgrade nuboard
    ```

## From source

Building from the repository also builds the viewer, which needs
**Node.js 20 or newer** and **pnpm**.

=== "pip"

    ```bash
    python -m venv .venv && . .venv/bin/activate
    pip install -e . --group dev                     # pip 25.1 or newer; else: pip install -e .
    (cd frontend && pnpm install && pnpm build)      # writes src/nuboard/static/
    nuboard demo demo-runs --up --open
    ```

=== "uv"

    ```bash
    uv sync                                          # Python, its dependencies and dev tools
    (cd frontend && pnpm install && pnpm build)      # writes src/nuboard/static/
    uv run nuboard demo demo-runs --up --open
    ```

`uv build` (or `python -m build`) produces a wheel and runs the frontend build
for you when `src/nuboard/static/` is missing.

??? question "`pnpm: command not found`"

    Install pnpm once. On macOS with Homebrew:

    ```bash
    brew install pnpm        # also: brew install node, if node is missing
    ```

    Elsewhere, `npm install -g pnpm` works, and so does `corepack enable pnpm`
    on Node versions that still ship corepack (Node 25 dropped it).

??? question "`ERR_PNPM_IGNORED_BUILDS` from `pnpm install`"

    pnpm only runs install scripts for packages it is told to trust. The
    repository approves `esbuild` and `@tailwindcss/oxide` in
    `frontend/pnpm-workspace.yaml`, which pnpm 10 and 11 both read. If you
    see this error with an older checkout, run `pnpm approve-builds` once and
    select both packages.

## Check the install

```console
$ nuboard version
nuboard 0.20.0
$ python -c "import nuboard; print(nuboard.__version__)"
0.20.0
```

Next, the [Quickstart](quickstart.md) runs the demo and logs a first run.
