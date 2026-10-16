# Roadmap

What is built, measured against the project brief, and what comes next. See
the [changelog](changelog.md) for what each version added.

## Done

- **0.1**: log format, Python API (init with config, git, packages, GPUs,
  command line and rank; log, media, artifacts, resume, fork, rank-0-only
  logging), Parquet compaction with zoom levels, Arrow analysis API, SQLite
  catalog, query language, CLI, and the Runs, Charts and Media pages.
- **0.2**: health alerts, Sweeps, Timeline and Artifacts pages, custom fields,
  a column chooser and collections.
- **0.3**: charts against any metric (tokens, epochs) and interactive Plotly,
  Vega-Lite and Bokeh figures; compare up to eight runs.
- **0.4**: audio logging with a waveform and spectrogram player.
- **0.5**: `add_*` naming, Google-style docstrings, MIT license.
- **0.6**: TensorBoard import.
- **0.7**: Media page rebuilt (kinds, grid, best-metric step), Markdown
  reports, run notes and typed properties.
- **0.8**: HTML export of reports, full screen and report snapshots for
  Sweeps and Timeline, run chips on the Media page.

## Next

1. **Multi-GPU view**: rank-0 line with min/mean/max bands across ranks,
   expandable per rank; per-node system metrics via NVML from `LOCAL_RANK 0`.
   Alerts already record their rank.
2. **Media**: three.js point clouds, side-by-side text diffs across steps,
   notes on audio selections (the player supports them; NuBoard does not
   store them yet).
3. **Sweeps**: averaging over seeds, distribution heatmaps, WebGL rendering
   for thousands of runs.
4. **Alerts**: user-defined rules (per metric thresholds) and notifications.
5. ~~**TensorBoard import**~~: done in 0.6 (`nuboard import-tensorboard`). Next:
   histograms, once NuBoard can show distributions.
6. Charts: Web Workers for decoding and smoothing, WebGL for very large
   scatters.
7. Runs table: TanStack Virtual, Bits UI menus and comboboxes (0.2 uses
   native controls and `prompt()` for collection names).
8. Packaging: publish to PyPI, CI on Linux/macOS/Windows.

## Known limitations

- Only one rank is plotted at a time (rank 0).
- Bokeh figures need `cdn.bokeh.org` when viewed; Plotly and Vega-Lite work
  offline.
- Smoothing is applied to the downsampled series the server sends (about
  one to two points per pixel), not to every raw point.
- The run list sends the whole filtered list to the browser; at tens of
  thousands of runs this should become paged.
- Runs on Windows are covered by design (no colons, atomic replace with
  retries, case-collision check) but were only tested on Linux so far.
