# Changelog

## 0.4.0

**Audio**

- `run.log_audio(key, audio, step, sample_rate=..., caption=...)` logs a file
  path (WAV, FLAC, MP3, Ogg/Opus, M4A, WebM), encoded bytes, or a NumPy/torch
  array. Arrays are written as 16-bit WAV with the standard library; sample
  rate, channels and duration are stored with each clip.
- The Media page plays audio with a **waveform** player (waveform and
  spectrogram, zoom, minimap, selection and loop, speed, full screen; the
  players of a key follow each other and only one plays at a time), ported
  from audioviewer and built on wavesurfer.js, or with the browser's
  **simple** player.
- Audio is served with HTTP Range support, so players can seek in long clips.
- The demo has a fourth project, `speech-denoise`: three models whose
  enhanced output gets cleaner over epochs, next to the noisy input and the
  clean target.

**API**

- The documented import is now `import nuboard as nb` (it was `nm`). Nothing
  in the package changes; only the examples, docs and tests use the new alias.

## 0.3.1

- **Compare** takes up to eight runs (it was limited to two). All settings
  shows a column per run and highlights rows where any run differs; file tabs
  diff any two of the compared runs.
- The run details and compare panel now open above the runs table and scroll
  into view, instead of appearing below a long table where they were easy to
  miss.

## 0.3.0

**Charts**

- **X axis by any metric**: plot every chart against another metric, such as
  `train/tokens` or `epoch`, from the new **x by metric** menu
  (`x=metric:<name>` in the URL). Points are matched by step, with the x metric
  interpolated where it was logged at other steps. Zoom maps back to a step
  range when the x metric only grows, so finer data still loads on zoom.

**Media**

- **Interactive figures**: Plotly, Vega-Lite (Altair) and Bokeh figures render
  interactively on the Media page, each in a sandboxed iframe that follows the
  theme. Plotly and Vega are bundled and load on demand; Bokeh loads BokehJS
  for the figure's exact version from `cdn.bokeh.org`.
- `log_figure` accepts Plotly figure dicts (`{"data": [...], "layout": ...}`)
  without Plotly installed.

**Other**

- The demo logs a Vega-Lite per-class accuracy chart and a Plotly confusion
  matrix in the ViT ablations.
- Built assets are served with `Access-Control-Allow-Origin: *` so the
  sandboxed figure frame can load them.

## 0.2.0

**New pages**

- **Sweeps**: parallel coordinates over the parameters that vary between
  runs, with brushing on every axis, log axes for wide numeric ranges, a scatter
  per parameter, a best-runs table and a rank correlation per parameter.
- **Timeline**: every run as a bar over wall-clock time, one row per run or
  packed to show concurrency, colored by status, project or group, with
  crash, alert and artifact markers and drag-to-zoom.
- **Artifacts**: every artifact version with files, hashes and metadata, the
  runs that produced and used it, and a lineage graph.

**Runs table**

- Health alert badges next to run names.
- **Columns** menu: add any metric, config key or custom field as a column.
- Editable **custom fields**, stored in `annotations.json` and usable in
  queries (`verdict = keep`) and as sweep parameters.
- **Collections**: named sets of runs in `<project>/collections/`, listed in
  the workspace and queryable with `collections has "name"`.

**Health alerts**

- Non-finite values, loss and gradient spikes, and throughput drops are
  detected per metric and rank, stored in `run.json` at compaction and computed
  live for running runs. They appear in the runs table, under charts (with
  shaded regions) and on the timeline, and through `RunHandle.alerts()`.
- Crashed and killed runs are now compacted too, so their alerts are stored.

**Other**

- New API endpoints: `/api/alerts`, `/api/collections`; `/api/artifacts`
  now returns producers, consumers and sizes.
- Query fields `alerts`, `collections` and `fields.<name>`.
- The demo gained a loss spike, an evaluation run that uses the checkpoint and
  writes a report artifact, two collections and custom fields.
- The frontend approves its build scripts in `pnpm-workspace.yaml`, which
  pnpm 10 and 11 read (pnpm 11 ignores the `pnpm` field in `package.json`).
- The documentation was reorganized into Installation, Quickstart, Guides
  and Reference.

The file format stays at version 1: all changes add keys or files, which older
readers ignore.

## 0.1.0

First version: the log format, Python API, reader, Parquet compaction,
analysis API, SQLite catalog, query language, and the viewer's Runs, Charts
and Media pages.
