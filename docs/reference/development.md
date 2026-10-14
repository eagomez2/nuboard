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
  analysis.py           nb.load(...) → Arrow tables
  server/               Starlette app and data access
  static/               built frontend (generated, not in git)
  cli.py demo.py        command line and demo data
frontend/               Svelte 5 + TypeScript + Vite + Tailwind v4 + uPlot
tests/                  pytest
benchmarks/bench.py     performance checks
scripts/blank_lines.py  blank-line-around-blocks formatter (see Code style)
docs/                   this site (mkdocs)
examples/               runnable examples
hatch_build.py          wheel build hook that builds and bundles the frontend
```

## Setup

You need [uv](https://docs.astral.sh/uv/), and for the frontend Node 20+ with
[pnpm](https://pnpm.io/).

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

## Docs

```bash
uv run mkdocs serve             # http://localhost:8000
uv run mkdocs build             # static site in site/
```

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
