# Development

## Repository layout

```text
src/nuboard/            Python package (the name lives here and in pyproject.toml)
  __init__.py           init, load, Run, Artifact
  _meta.py              NAME, FORMAT_VERSION, defaults
  run.py _writer.py     logging API and background writer (stdlib only)
  _format.py            event-log frames (stdlib only)
  _env.py _media.py     environment capture, image/figure encoding (stdlib only)
  artifacts.py          versioned artifacts (stdlib only)
  reader.py series.py   NumPy reader, downsampling, aggregation
  compact.py alerts.py  Parquet compaction (PyArrow), health checks (NumPy)
  catalog.py query.py   run discovery, SQLite cache, query language
  collection.py         collections of runs (stdlib only)
  tensorboard.py        TensorBoard event-file import (stdlib only)
  merge.py remove.py    nuboard merge and nuboard rm
  analysis.py           nb.load(...) → Arrow tables
  server/               Starlette app and data access
  static/               built frontend (generated, not in git)
  cli.py demo.py        command line and demo data
frontend/               Svelte 5 + TypeScript + Vite + Tailwind v4 + uPlot
tests/                  pytest (tests/data: TensorBoard logs from real writers)
benchmarks/bench.py     performance checks
scripts/blank_lines.py  blank-line-around-blocks formatter (see Code style)
docs/                   this site (mkdocs)
examples/               runnable examples
hatch_build.py          wheel build hook that builds and bundles the frontend
```

## Setup

You need [uv](https://docs.astral.sh/uv/) or pip, and for the frontend Node
20+ with [pnpm](https://pnpm.io/). The commands below use uv; with pip, run
`pip install -e . --group dev` (pip 25.1 or newer) in a virtual environment
instead of `uv sync`, and drop `uv run` from the other commands.

```bash
uv sync                        # Python deps + dev tools into .venv
cd frontend && pnpm install && pnpm build && cd ..   # builds into src/nuboard/static/
uv run nuboard demo demo-runs --up
```

For frontend work, run the API and Vite's dev server side by side; Vite
proxies `/api` to port 6070:

```bash
uv run nuboard up demo-runs           # terminal 1 (port 6070)
cd frontend && pnpm dev                  # terminal 2, open http://localhost:5173
```

## Code style

- [PEP 8](https://peps.python.org/pep-0008/), formatted by `ruff format` with
  100-character lines.
- Google-style docstrings (`Args:`, `Returns:`, `Raises:`, `Yields:`) on every
  module, class and function, checked by ruff's `pydocstyle` rules. Constructor
  arguments are documented on the class. Inline code uses single backticks.
- A blank line separates every `if`, `for`, `while`, `with`, `try` and `match`
  block from the statements before and after it:

    ```python
    if config is None:
        return {}

    if isinstance(config, Mapping):
        return dict(config)

    to_dict = getattr(config, "to_dict", None)
    ```

  `python scripts/blank_lines.py src tests` adds the missing ones, and
  `tests/test_style.py` fails if any are missing.

## Checks

```bash
uv run pytest                   # Python tests (crash safety, resume, format, server, …)
uv run ruff check . && uv run ruff format --check .
python scripts/blank_lines.py --check src tests scripts examples benchmarks
uv run pyright
uv run python benchmarks/bench.py

cd frontend
pnpm test                       # Vitest unit tests
pnpm check                      # svelte-check (TypeScript)
pnpm lint                       # ESLint
pnpm exec playwright install chromium   # once
pnpm e2e                        # Playwright: starts `nuboard demo --up` on port 6071
```

## Building a wheel

```bash
uv build                        # runs hatch_build.py: pnpm install + pnpm build if static/ is missing
```

The wheel contains the built frontend, so users never need Node. Set
`SKIP_FRONTEND_BUILD=1` to build without it (the viewer then shows a "frontend
not built" page).

## Releasing

1. Set the version in `pyproject.toml` and `frontend/package.json`, the
   `nuboard X.Y.Z` lines of `docs/installation.md` and a `## X.Y.Z` section
   in `docs/changelog.md`; `tests/test_release.py` checks that they agree.
   Then run `uv lock`.
2. Merge into `main`, then build and upload from a clean checkout of it:

    === "uv"

        ```bash
        rm -rf dist src/nuboard/static   # no stale viewer build in the package
        uv build                         # builds the viewer too (Node 20+ and pnpm)
        uv publish                       # token from UV_PUBLISH_TOKEN or --token
        ```

    === "pip"

        ```bash
        rm -rf dist src/nuboard/static
        python -m build
        twine upload dist/*
        ```

    Use a PyPI API token scoped to the `nuboard` project, and keep it out of
    the repository. To try a release first, upload to TestPyPI with
    `uv publish --publish-url https://test.pypi.org/legacy/` (or
    `twine upload -r testpypi dist/*`).
3. Optionally, publish a GitHub release tagged `vX.Y.Z` with the changelog
   section as its notes.

## Docs

```bash
uv run mkdocs serve             # http://localhost:8000
uv run mkdocs build             # static site in site/
```

The **Docs** workflow builds the site on every push to `main` and publishes it
to <https://eagomez2.github.io/nuboard/>. It needs **Settings → Pages →
Source: GitHub Actions** set once in the repository.

Keep [`docs/format.md`](format.md) in sync with every change to what is
written to disk.

## Rules for the logging side

- Standard library only. Anything that needs NumPy or PyArrow belongs to the
  reader, compaction, analysis or server modules and is imported lazily from
  `run.py`.
- Never raise from the writer thread into training: failures are warned once.
- Never add a lock to the write path or a database next to the runs.

Flag any change that adds a logging-side dependency or a server to deployment.

## Renaming

The name exists in exactly three places:

1. `pyproject.toml`: `name`, the `[project.scripts]` entry, and
   `packages = ["src/nuboard"]`;
2. the package folder `src/nuboard/`;
3. `frontend/src/lib/brand.ts` (and `frontend/package.json`'s `name`, which
   is cosmetic).

Everything else derives from `NAME` (`nuboard._meta.NAME = __name__.split(".")[0]`):
the environment variable prefix (`NUBOARD_DIR`), the cache folder, CLI help,
the page title. Docs and README mention the name in prose and need a
search-and-replace. The on-disk format does not contain the name (the log
magic is `RUNLOG`), so existing runs stay readable after a rename.
