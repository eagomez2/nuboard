---
hide:
  - navigation
---

# Installation

NuBoard needs **Python 3.10 or newer** on Linux, macOS or Windows. It comes in
two parts, so a training environment only gets what it needs:

| Install | Adds | Use it for |
| --- | --- | --- |
| `nuboard` | nothing (standard library only) | logging from training scripts |
| `nuboard[viewer]` | NumPy, PyArrow, Starlette, uvicorn | `nuboard up`, compaction, the analysis API |

## From the wheel

The `nuboard` package is not on PyPI yet. Each release ships a wheel with the viewer already
built inside it, so installing it needs no Node.js:

=== "uv"

    ```bash
    uv tool install "nuboard-0.15.8-py3-none-any.whl[viewer]"  # the nuboard command
    uv pip install nuboard-0.15.8-py3-none-any.whl             # logging only
    ```

=== "pip"

    ```bash
    pip install "nuboard-0.15.8-py3-none-any.whl[viewer]"
    pip install nuboard-0.15.8-py3-none-any.whl                 # logging only
    ```

To try it without installing anything, run the demo straight from the wheel:

```bash
uv run --with "nuboard-0.15.8-py3-none-any.whl[viewer]" nuboard demo demo-runs --up --open
```

## From source

Building from the repository also builds the viewer, which needs
**Node.js 20 or newer** and **pnpm**.

```bash
uv sync                                          # Python, the viewer extra and dev tools
(cd frontend && pnpm install && pnpm build)      # writes src/nuboard/static/
uv run nuboard demo demo-runs --up --open
```

`uv build` produces a wheel and runs the frontend build for you when
`src/nuboard/static/` is missing.

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
nuboard 0.15.8
$ python -c "import nuboard; print(nuboard.__version__)"
0.15.8
```

Next, the [Quickstart](quickstart.md) runs the demo and logs a first run.
