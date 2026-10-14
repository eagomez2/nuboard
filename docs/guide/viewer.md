# Using the viewer

```bash
nuboard up ~/exp          # any folder: one run, one project, or many projects
```

The viewer is a single-page app served by a small local Starlette server. All
data stays on your machine. Every piece of view state (query, page, metric,
x-axis, smoothing, zoom, selection, compared runs) is in the URL, so you can
bookmark a view, send the link to yourself on another machine, or save it as a
view file. Per-viewer preferences (theme, default smoothing) live in your
browser's local storage.

![Runs page](../assets/runs-light.png#only-light){ .nb-shot }
![Runs page](../assets/runs-dark.png#only-dark){ .nb-shot }

## Header

- **Folder chip**: the served folder; click it to go back to all runs.
- **Query bar** (<kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd>): filters,
  groups and orders runs everywhere in the app. See the
  [query language](../reference/query.md).
- **Theme toggle**: light and dark themes; the default follows your system.

## Runs page

- **Workspace** (left): every project found under the folder, with run counts,
  its collections and its saved views. **Save current view…** writes the
  current URL state to `<project>/views/<name>.json`, which you can commit.
- **Table**: status, star, name and folder, the config keys that differ between
  the listed runs, a result column, start time, duration, reviewed mark and
  notes. Pick the result metric in the toolbar and switch between **best**
  (min for losses and errors, max otherwise) and **last**. Click a column
  header to sort. The list is virtualized, so thousands of runs scroll
  smoothly.
- **Filter box**: quick text filter on name, id, project, tags and notes.
- **Selection**: tick runs to **Star**, **Archive**, **Mark reviewed**,
  **Add to collection…**, open them in **Media**, **Compare** two of them, or
  **Plot selected**.
- **Alerts**: a warning badge next to a run name counts its
  [health alerts](alerts.md). Hover it to read them; click it to open the
  run's chart.
- **Columns**: add columns for any metric (last value), any config key, or
  a custom field. The chosen columns are part of the URL.
- **Notes**: click a notes cell to edit it in place.
- Stars, notes, review marks, archive flags and custom fields are written to
  the run's own `annotations.json`, so they move with the run folder.
  Archived runs are hidden unless **show archived** is on.

### Custom fields

Custom fields are your own columns: a verdict, an owner, a score. Open
**Columns**, type a name under **Custom fields** and press **+**; then click a
cell to edit it. Numbers and `true`/`false` are stored as such, so queries
like `score > 3` and `verdict = keep` work; clear a cell to remove the value.
Fields can also be used as sweep parameters. From Python they are
`run.fields` in the [analysis API](analysis.md).

### Collections

A collection is a named, hand-picked set of runs, such as a shortlist or the
runs behind a paper figure. Select runs and press **Add to collection…**;
type an existing name to add to it. Collections are listed under their
project in the workspace; click one to filter to it (the query becomes
`collections has "shortlist"`), or hover it and press × to delete it (the
runs are not touched).

Each collection is a small JSON file, `<project>/collections/<name>.json`,
listing run ids, so it can be committed and survives moving the folder.

### Run details and compare

Click a run name to open its details below the table: every setting (config,
git commit, host, Python, GPUs, world size, fork origin, artifacts used and
produced, last value of every metric) and the files saved by `init`. A crashed
run shows its traceback.

With two runs selected, **Compare** shows the same tabs side by side:
**all settings** highlights rows that differ, and each file tab (`config.json`,
`requirements.txt`, `git.patch`, `command.txt`) shows a line diff. **only
changes** hides identical lines.

## Charts page

![Charts page](../assets/charts-light.png#only-light){ .nb-shot }
![Charts page](../assets/charts-dark.png#only-dark){ .nb-shot }

The Charts page plots the selected runs (from **Plot selected**) or, if none
are selected, every run matching the query.

- **Summary cards**: best value of the focused metric, running runs and last
  heartbeat, runs with NaN/Inf values, and how many runs are shown.
- **Grouping**: `group by config.optim.lr` in the query (or the **group by**
  menu) draws one line per group with a band: mean ± std (default), mean ± sem,
  mean with min–max, or median with min–max (`agg` in the query, or the band
  menu). Runs are interpolated onto a shared x grid on the server before
  aggregating, so runs with different logging steps combine correctly.
  Without grouping, each run is one line (up to 60; group to see more).
- **Legend chips**: hover to highlight a series, click to hide it. Each series
  has a color and a marker shape, so series stay distinguishable without
  color.
- **X axis**: step, wall time, relative time since the run started, or active
  time (relative time with pauses longer than five minutes removed).
- **Smoothing**: debiased exponential moving average (as in TensorBoard). With
  **raw** on, the unsmoothed data is drawn faintly behind the smoothed line.
- **Robust y**: clips the y-axis to the 1st–99th percentile so a single spike
  does not flatten every curve. **Log y** switches to a log scale.
- **Zoom**: drag across a chart to zoom in; the server sends a finer
  resolution for the visible range (from the precomputed zoom levels in
  `data.parquet`, or from the raw log for live runs). Double-click to reset.
- **Inspector**: hover a chart to see every series' value at that step,
  sorted best first, with ± std for grouped series. Click to pin the step.
  Without hovering it shows the latest values.
- **Linked crosshair**: hovering any chart moves the crosshair on all of them.
- **All metrics**: a small chart per metric, grouped by prefix (`train/`,
  `eval/`, `sys/`…). Small charts load as you scroll. Click a title to bring
  the metric into focus.
- A run that logged NaN gets a dashed marker at the first NaN with a
  `NaN · run` label.
- **Live**: while runs are running, the server pushes updates over
  Server-Sent Events and the charts refresh about every two seconds.

- **Alerts strip**: under the focused chart, the
  [health alerts](alerts.md) of the runs in view. Click one to jump to it;
  spikes and drops are shaded on the chart.

## Sweeps page

Parallel coordinates over the parameters that vary between runs, with brushing
on every axis, a scatter per parameter and a best-runs table. See
[Sweeps](sweeps.md).

## Timeline page

![Timeline page](../assets/timeline-light.png){ .nb-shot }

Every run as a bar from start to end, grouped by project, colored by status,
project or group. **Packed** puts runs that never overlap on the same row, so
the chart shows how many ran at once; the summary line gives the peak and the
total run time. Crashed runs end in ✕, runs with alerts have a dot, and
diamonds mark artifact versions a run produced. Drag to zoom into a time
range, double-click to reset, click a bar to open the run.

## Artifacts page

Every artifact version with its files, metadata and a lineage graph of the
runs that produced and used it. See [Artifacts and lineage](artifacts.md).

## Media page

Shows images, figures, HTML and text logged with `log_image`, `log_figure`,
`log_html` and `log_text`, for the selected runs (or the query result, up to
16 runs). Pick a key, then move the step slider; each run shows its latest
item at or before that step, side by side.

Logged HTML runs in a sandboxed iframe (`sandbox="allow-scripts"`, no
same-origin access) and is served with a matching `Content-Security-Policy`.
Matplotlib figures are stored as SVG and shown as images. Plotly, Vega-Lite
and Bokeh specs are stored and downloadable; rendering them interactively is
on the [roadmap](../roadmap.md).
