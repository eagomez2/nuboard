# Roadmap

What 0.1 covers, measured against the project brief, and what comes next.

## Done in 0.1

- Log format (frames, CRC, torn-frame tolerance, incremental reads),
  documented in [File format](format.md).
- Python API: `init` (config, git commit and diff, packages, GPUs, command line,
  rank), `log`, `log_text`, `log_image`, `log_figure`, `log_html`,
  `log_artifact`, `use_artifact`, `finish`, context manager, crash and exit
  handling, resume (`must`/`auto`, later session wins), fork, rank-0-only
  logging with `all_ranks`.
- Compaction to Parquet with zoom levels and a row-group map.
- Analysis API returning Arrow tables (`nm.load(...).scalars(..., group_by=...)`).
- SQLite catalog cache, query language, `nuboard up | demo | ls | compact`.
- Viewer: Runs table (query, filter, sort, star, archive, review, notes,
  saved views), run details and two-run compare with config/file diffs,
  Charts (grouping with bands, x-axis choice, debiased EMA with raw, robust y,
  log y, linked crosshair, inspector, zoom with finer data, NaN markers, live
  updates over SSE), Media (images, SVG figures, sandboxed HTML, text with a
  step slider). Light and dark themes.

## Next

1. **Multi-GPU view**: rank-0 line with min/mean/max bands across ranks,
   expandable per rank; per-node system metrics via NVML from `LOCAL_RANK 0`.
2. **Media**: interactive Plotly / Vega-Lite / Bokeh renderers (lazy-loaded),
   three.js point clouds, side-by-side text diffs across steps, audio.
3. **Sweep views**: parallel coordinates, final metric vs hyperparameter,
   distribution heatmaps (regl/WebGL).
4. **Health alerts**: NaN/Inf, loss and grad-norm spikes, throughput drops,
   with run and rank, plus the alerts strip under charts.
5. **Artifact lineage pages**, a timeline view, collections.
6. **TensorBoard import** (tfevents → run folders).
7. Charts: x-axis by any metric (e.g. tokens), Web Workers for decoding and
   smoothing, WebGL for very large scatters.
8. Runs table: editable custom fields, column chooser, TanStack Virtual,
   Bits UI menus and comboboxes (0.1 uses native controls).
9. Packaging: publish to PyPI, CI on Linux/macOS/Windows.

## Known limitations

- Only one rank is plotted at a time (rank 0).
- Smoothing is applied to the downsampled series the server sends (about
  one to two points per pixel), not to every raw point.
- The run list sends the whole filtered list to the browser; at tens of
  thousands of runs this should become paged.
- Runs on Windows are covered by design (no colons, atomic replace with
  retries, case-collision check) but were only tested on Linux so far.
