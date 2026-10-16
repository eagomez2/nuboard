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
  **Add to collection…**, open them in **Media**, **Compare** up to eight of them, or
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

Custom fields are your own columns: a verdict, an owner, a score.

1. Open **Columns**, type a name under **Custom fields** and press **+** (or
   Enter). The column appears next to **Run**, marked ✎. Fields that already
   have values on some run are listed there to show or hide.
2. Click a cell in that column to edit it: Enter saves, Esc cancels, and an
   empty value removes the field from that run.
3. To set the same value on many runs, select them and press **Set field…**.

Numbers and `true`/`false` are stored as such, so queries like `score > 3`
and `verdict = keep` work. Fields can also be used as sweep parameters. From
Python, read them as `run.fields` and write them with
`run.set_field("verdict", "keep")` in the [analysis API](analysis.md).

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

Click a run name to open its details above the table: every setting (config,
git commit, host, Python, GPUs, world size, fork origin, artifacts used and
produced, last value of every metric) and the run's files. A crashed
run shows its traceback.

For a single run there are two more tabs:

- **Notes**: Markdown notes for the run, with a preview. Notes can use
  headings, lists, tables, links and code, and embed any logged item with
  the same `![caption](media:<run id>/<key>@<step>)` line as a
  [report](reports.md). The runs table shows the first line; a note of more
  than one line opens here when clicked.
- **Properties**: typed properties of the run. **Add property** defines one for
  the whole project, with a type: text, number (with an optional unit),
  choice, tags, bool, date or link. Choices and tags offer the values used
  before, and new values are added to the list. Values are saved per run as
  custom fields, so they show up as columns and work in queries
  (`verdict = "keep"`, `topics has "augmentation"`). Definitions are kept in
  `<project>/fields.json`.

With two to eight runs selected, **Compare** shows the same tabs side by side:
**All settings** has a column per run and highlights rows where any run
differs. There is a tab for each file the runs saved (such as
`requirements.txt`, `git.patch`, `command.txt` and any file added with
[`add_file`](logging.md#config-files)); it shows a line diff between two of the
runs. With more than two, pick which two from the **diff … against …** menus. **only changes** hides
identical rows and lines.

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
- **Legend chips**: hover to highlight a series, click to hide it, and
  double-click (or Alt-click) to show only that series; soloing it again shows
  them all. **All** and **None** before the chips show or hide every series, so
  you can start from None and click the few you want. Each series has a color
  and a marker shape, so series stay distinguishable without color.
- **X axis**: step, wall time, relative time since the run started, or active
  time (relative time with pauses longer than five minutes removed). The
  **x by metric** menu plots against any other metric instead, such as
  `train/tokens` or `epoch`; counter-like metrics are listed first. The x
  metric is matched to each point by step (interpolated when the two were
  logged at different steps), and zooming works as usual when the x metric
  only grows. The choice is kept in the URL as `x=metric:<name>`.
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
- **Full screen**: the corner button above the focused chart (or Esc to
  leave) fills the screen with the chart and the inspector.
- **Add to a report**: the bookmark button above the focused chart saves it
  into a [report](reports.md), as it is shown: runs, grouping, smoothing,
  zoom and hidden series. The report draws it live and keeps a PNG copy for
  exports.
- **All metrics**: a small chart per metric, grouped by prefix (`train/`,
  `eval/`, `sys/`…). Small charts load as you scroll. Click a title to bring
  the metric into focus. **Grid** sets the charts per row (fit to width, or 1
  to 6) and the rows per section (1 to 6, or all); a section with more charts
  gets a pager. Both are remembered and kept in the URL (`ccols`, `crows`).
- A run that logged NaN gets a dashed marker at the first NaN with a
  `NaN · run` label.
- **Live**: while runs are running, the server pushes updates over
  Server-Sent Events and the charts refresh about every two seconds.

- **Alerts strip**: under the focused chart, the
  [health alerts](alerts.md) of the runs in view. Click one to jump to it;
  spikes and drops are shaded on the chart.

## Sweeps page

Parallel coordinates over the parameters that vary between runs, with brushing
on every axis, a grid of scatters (one per parameter) and a best-runs table.
The main chart can go full screen, and any plot can be added to a report. See
[Sweeps](sweeps.md).

## Timeline page

![Timeline page](../assets/timeline-light.png){ .nb-shot }

Every run as a bar from start to end, grouped by project, colored by status,
project or group. **Packed** puts runs that never overlap on the same row, so
the chart shows how many ran at once; the summary line gives the peak and the
total run time. Crashed runs end in ✕, runs with alerts have a dot, and
diamonds mark artifact versions a run produced. Drag to zoom into a time
range, double-click to reset, click a bar to open the run. The corner button
shows the timeline full screen (Esc leaves), and the bookmark button adds it
to a [report](reports.md) as a snapshot.

## Artifacts page

Every artifact version with its files, metadata and a lineage graph of the
runs that produced and used it. See [Artifacts and lineage](artifacts.md).

## Reports page

Lists the Markdown reports of every project, with an editor and a live
preview side by side. See [Reports](reports.md).

## Media page

Shows images, audio, figures, HTML and text logged with `add_image`,
`add_audio`, `add_figure`, `add_html` and `add_text`, for the selected runs (or
the query result, up to 48 runs). Each key is a collapsible section with a card
per run; every card has its own step slider, as in TensorBoard, so one run can
be scrolled through its steps while the others stay put.

- **Runs**: a chip per run, as in the Charts legend. Click one to hide or
  show it, double-click (or Alt-click) to show only that run, and **All** or
  **None** to show or hide every run.
- **Kinds**: the chips below (Images, Audio, Figures, HTML, Text) show or
  hide a kind of media; double-click one to show only that kind. The number
  on each chip counts its keys.
- **Filter keys**: a regular expression on the keys, such as `^eval/` or
  `confusion|per_class`.
- **by key / by run**: a section per key with a card per run (default), or a
  section per run with a card per key.
- **Step**: **latest** shows each run's last item; **pick step** moves every
  card to the item at or before one step; **best metric** moves each run to
  the item closest to the step where a metric of your choice was lowest or
  highest (for example the best `val/acc`). Moving a card's own slider
  overrides the page-wide step for that card only.
- **Grid**: **columns** sets the cards per row (fit to width, or 1 to 8) and
  **rows** how many rows each section shows per page (1 to 6, or all); a
  section with more cards gets a pager. Both are remembered.
- **Expand all** and **Collapse all** fold the sections; with many keys only
  the first three start open. **show runs without the key** adds an empty
  card for runs that never logged it.

Each card can open its item large, download it, or **add it to a report**
(the bookmark button). **Select for report** adds a checkbox to every card
so several items go into a report at once; see [Reports](reports.md). The whole view is kept in
the URL (`mkinds`, `mfind`, `mby`, `mmode`, `mstep`, `mmetric`, `mdir`,
`mcols`, `mrows`), so a shared link shows the same grid.

Logged HTML runs in a sandboxed iframe (`sandbox="allow-scripts"`, no
same-origin access) and is served with a matching `Content-Security-Policy`.
**output / code** above it switches to the HTML source, with line numbers.
Matplotlib figures are stored as SVG and shown as images. Plotly, Vega-Lite
and Bokeh figures are interactive (hover, zoom, pan, export), each in its own
sandboxed iframe, and follow the light or dark theme. Every figure also has a
**download spec** link for the raw JSON.

| Library | Rendered with | Network |
| --- | --- | --- |
| Plotly | plotly.js 4, bundled with the viewer | none |
| Altair / Vega-Lite | Vega 6, Vega-Lite 6 and vega-embed, bundled | none |
| Bokeh | BokehJS from `cdn.bokeh.org`, for the exact version that wrote the figure | needed when viewing |

The bundled renderers load only when a figure of that kind is on screen.
BokehJS has to match the Python Bokeh version, so it cannot be bundled; when
the CDN is unreachable the figure shows a message and the spec stays
downloadable.


### Audio

Audio has two players, switched with **player** above the grid (the choice is
remembered):

- **waveform** (default): waveform and spectrogram of every channel, with a
  minimap, time ruler, zoom (buttons, slider, `+`/`-`, or Ctrl + wheel),
  drag-to-select with loop (`L`) and zoom-to-selection (`Z`), playback speed,
  and full screen (`F`). The spectrogram is computed in the browser (Hann
  window of 1024 samples, levels in dB relative to a full-scale sine on a
  fixed scale, so clips can be compared by eye). The players of one key
  follow each other's zoom, scroll, cursor and selection, and starting one
  pauses the others, so you can listen to the same passage across runs.
  Space plays and pauses; arrow keys seek. Next to the player switch,
  **colors** picks the spectrogram colormap (theme, viridis, magma or gray),
  **frequency** its scale (linear, log or mel), **window** the FFT size (256
  to 4096 samples; the hop is a quarter of it), and **spectrogram** hides it
  to show only waveforms. The choices are remembered in the browser and kept
  in the URL (`cmap`, `fscale`, `fft`, `spec`), so a shared link shows the
  same view.
- **simple**: the browser's own audio controls, as in TensorBoard.

Each clip shows its caption, duration, sample rate and channels, and a
download link. The waveform player is a port of the player in
audioviewer, built on
[wavesurfer.js](https://wavesurfer.xyz) (BSD-3), bundled with the viewer
so it works offline.
