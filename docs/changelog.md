# Changelog

## 0.8.3

**Runs**

- Property values must fit their type: a choice is picked from a menu, tags
  are toggled as colored pills, numbers, dates and links are checked, and the
  server and `Run.set_field` refuse values that do not fit. New options are
  added on purpose (**New option…**, **+ option**) instead of by typing.
- Removing a property removes its definition and its values; properties set
  without a definition can be removed too.
- Run tags are colored pills under the run name instead of sitting in the
  config column.

**Media**

- The key filter shows how many keys match and says so when none do.

**Charts**

- **Filter metrics** (regex) above All metrics.
- **Points**: a dot on each curve at the logged point under the cursor.
- "robust y" is now **ignore outliers**, with a tooltip explaining it.

**Other**

- **About** at the bottom of the side bar: version, copyright, license and a
  link to the documentation.

## 0.8.2

- Exported reports show the NuBoard logo only as the browser tab icon; the
  default footer names NuBoard and its version instead.
- The docs say NuBoard for the app and `nuboard` for the package, command
  and import.

## 0.8.1

**Reports**

- **Export as HTML** asks for a theme (light, dark, or switchable with a
  button that follows the reader's system theme), the footer text (by
  default "Exported with NuBoard …") and whether to show the NuBoard logo
  in the footer and as the tab icon.
- Charts saved from the Charts page are drawn live in the exported file
  from their data, so they follow its theme instead of showing a snapshot
  taken in another theme.

**Runs**

- **Add property** picks the type from a menu instead of a text box.

## 0.8.0

**Reports**

- **Export as HTML**: one self-contained file that opens offline, with
  images, audio and snapshots inlined, logged text and HTML included, and
  interactive Plotly and Vega-Lite figures whose libraries are embedded in
  the file (no CDN).
- Sweeps and Timeline plots can be added to reports as snapshots, with an
  **Open in Sweeps** / **Open in Timeline** button that restores the view.

**Sweeps**

- **Grid** for the scatter plots: plots per row and rows per page, with a
  pager.
- **Full screen** for the parallel coordinates; a bookmark button adds it,
  or any scatter, to a report.

**Timeline**

- **Full screen**, and a bookmark button that adds the timeline to a report.

**Media**

- **Select for report**: tick several cards and add their items to a report
  in one go.
- A chip per run with **All** and **None**, as in the Charts legend: click to
  hide a run, double-click or Alt-click to show only that run.
- Logged HTML has **output / code**: the rendered page or its source with
  line numbers.

**Other**

- The browser tab and the header say **NuBoard**.
- Run details tabs are capitalized: **Notes**, **Properties**, **All
  settings**.
- Fixes: embeds of the previous report no longer flash when switching
  reports.

## 0.7.0

**Media page**

- Kind chips show or hide images, audio, figures, HTML and text (double-click
  one to show only that kind), and a regex filter narrows the keys.
- Each key is a collapsible section with a card per run, and each card has its
  own step slider, as in TensorBoard. **by run** turns it around: a section per
  run with a card per key.
- **Step**: latest, one step for every card, or **best metric**, which moves
  each run to its best step for a metric you pick (lowest or highest).
- **Grid**: columns per row (fit, 1 to 8) and rows per page (1 to 6, or all),
  with a pager per section. Up to 48 runs.
- Each item can be opened large, downloaded or added to a report.
- The demo's `vit-ablations` project has more metrics (one per class), typed
  properties, a Markdown note and a sample report with images, a figure and a
  chart.

**Reports**

- New **Reports** page: Markdown reports in `<project>/reports/<name>.md`, with
  a split editor and preview, autosave, rename, delete, print and
  **Export .zip** (the Markdown plus the embedded files).
- `![caption](media:<run id>/<key>@<step>)` embeds a logged image, audio clip,
  figure, HTML page or text. The Media page writes these lines for you.

**Charts page**

- **Grid** for the small charts: charts per row (fit, 1 to 6) and rows per
  section (1 to 6, or all), with a pager per section.
- **Full screen** for the focused chart and its inspector.
- **Add to a report**: saves the focused chart as shown (runs, grouping,
  smoothing, zoom, hidden series). Reports draw it live and keep a PNG
  snapshot for exports and other Markdown viewers.

**Notes and properties**

- Run notes are Markdown, edited with a preview in the run's **Notes** tab, and
  can embed logged items.
- Typed properties (text, number, choice, tags, bool, date, link), defined per
  project in `fields.json` and set in the run's **Properties** tab. They are
  custom fields, so they show up as columns and in queries.

**Config files**

- NuBoard no longer writes `files/config.json`. `run.add_file(path)` copies
  any file or folder (YAML, TOML, Hydra outputs, ...) into the run's `files/`,
  where the viewer shows and diffs it. The config passed to `init` is still in
  `run.json`.

**Fixes**

- Charts kept their first width: a chart drawn before its container was laid
  out (or after a window resize) did not fill it.
- Two runs with the same name no longer break the Charts page; their series
  are labelled with the run id's suffix.
- Long run, metric and key names no longer overflow the Charts inspector, the
  summary cards (Best, Running, ...) and other panels; they are cut with an
  ellipsis and shown in full on hover.

## 0.6.0

**TensorBoard import**

- `nuboard import-tensorboard LOGDIR` imports TensorBoard logs as runs: every folder of
  `events.out.tfevents.*` files under `LOGDIR` becomes a run, named after its
  path, with its parent path as the group. Scalars, images, audio, text and
  HParams hyperparameters (stored as the run's config) are imported with their
  original steps and wall times. Histograms, graphs and other plugins are
  skipped and counted. Logs from TensorFlow 1 and 2, PyTorch's `SummaryWriter`
  and tensorboardX are supported, and importing the same folder again skips
  the runs already imported.
- The event files are decoded with the standard library, so the importer needs
  neither TensorFlow nor TensorBoard, and adds no dependency.
- From Python: `nuboard.tensorboard.import_logdir(logdir, project, dir=..., tags=...)`.
- `add_text`, `add_image`, `add_audio`, `add_figure` and `add_html` take a
  keyword-only `time=` timestamp, like `run.log`.

**Fixes**

- Queries can use the `group` field (`where group = "fit/run1"`,
  `group by group`); before, `group` was only read as the start of `group by`.

## 0.5.0

**Breaking: media methods are now `add_*`**

- `run.log_text`, `log_image`, `log_audio`, `log_figure`, `log_html` and
  `log_artifact` are renamed to `add_text`, `add_image`, `add_audio`,
  `add_figure`, `add_html` and `add_artifact`, with the same arguments.
  `run.log({...})` for scalars keeps its name. The on-disk format does not
  change, so runs logged with older versions open as before.

**Code style**

- Google-style docstrings throughout the package, checked by ruff's
  `pydocstyle` rules. Inline code in docstrings uses single backticks.
- A blank line separates every `if`, `for`, `while`, `with`, `try` and `match`
  block from the statements around it. `scripts/blank_lines.py` applies the
  rule and a test checks it.

**License**

- NuBoard is released under the MIT License (`LICENSE`, linked from the
  README and the docs).

## 0.4.3

- Charts: **All** and **None** buttons next to the legend, and double-click
  (or Alt-click) on a legend chip to solo that series.
- Save current view, Set field…, Add to collection and deleting a collection
  now ask in a dialog that follows the NuBoard theme instead of the browser's
  own prompt.

## 0.4.2

- Custom fields are easier to find and edit: the **+** in **Columns** is
  disabled until a name is typed (before, it silently did nothing), adding a
  field closes the menu to show the new column, and the menu explains how to
  edit cells.
- **Set field…** in the selection bar sets one field on all selected runs.
- `RunHandle.set_field(name, value)` writes a custom field from Python.

## 0.4.1

- Spectrogram options for the waveform player on the Media page: colormap
  (theme, viridis, magma, gray), frequency scale (linear, log, mel), FFT window
  (256 to 4096) and a switch to hide the spectrogram. They are remembered per
  browser and kept in the URL.

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
