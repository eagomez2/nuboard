# Reports

A report is a Markdown document that mixes your own writing with images,
audio, figures and text logged by runs, for a weekly update, a paper draft or
a record of what an ablation showed. Reports are plain files in
`<project>/reports/<name>.md`, so they can be edited by hand, diffed and
committed next to the runs.

## Adding items from the Media page

Every card on the **Media** page has a bookmark button. It asks for a report
name (the last one used is filled in) and a caption, then appends a line such
as

```markdown
![cutmix-s0 at the best val/acc](media:20261016T0815-e8021047/samples/augmented@80)
```

to the end of the report, creating it if needed.

To add several at once, press **Select for report** above the sections, tick
the cards whose shown item you want, and press **Add N to report** in the bar
at the bottom. They are appended in the order you ticked them, each with a
caption naming its key, step and run. **Open report** in the
notice jumps to it. Use **Best scalar** on the Media page first to save the
item at a run's best step.

## Adding charts from the Charts page

The bookmark button above the focused chart on the **Charts** page adds that
chart to a report, as it is shown: the runs, scalar, x axis, grouping,
smoothing, zoom and hidden series. It writes a line such as

```markdown
![val/acc by augmentation](files/findings-1a2b3c4d.png "chart:metric=val%2Facc&runs=...")
```

The image is a PNG snapshot of the chart, saved in
`<project>/reports/files/`, so the report shows the chart in any Markdown
viewer. In NuBoard the title after `chart:` describes the view, and the
chart is drawn live instead: it follows the theme, updates while runs are
running, and **Open in Charts** opens it on the Charts page.

## Adding Sweeps and Timeline plots

The bookmark buttons on the **Sweeps** page (the parallel coordinates and each
scatter), on the **Timeline** and on the Media page's "All runs on one chart"
(PR curves and distributions, with their legend) add a PNG snapshot of the
plot as shown:

```markdown
![lr sweep](files/findings-5e6f7a8b.png "view:sweeps?project=llm-pretrain&metric=train%2Floss")
```

The title after `view:` is the page and its settings; in NuBoard the image
gets an **Open in Sweeps** (or **Open in Timeline**) button that restores
that view.

## Writing

The **Reports** page lists the reports of every project. **New** creates one;
**Write**, **Split** and **Preview** switch between the editor, both side by
side, and the rendered page. Changes are saved a moment after you stop typing
(or with Ctrl+S / ⌘+S). Headings, lists, tables, links, code blocks and
images all work; HTML in the Markdown is sanitized.

An embedded item is rendered in place: images as images, audio with the
waveform player, Plotly, Vega-Lite and Bokeh figures interactively, logged
HTML in a sandbox and text as a block, each with a caption and a link to its
run. The same `media:` lines also work in a run's [notes](viewer.md#run-details-and-compare).

## Sharing

- **.zip** downloads the Markdown with every embedded image and audio
  clip as a file in `files/`, figures and HTML as linked files, chart
  snapshots as images, and logged text inlined, so it reads on GitHub or in any Markdown editor without
  NuBoard. A waveform figure becomes its audio as a `.wav` and its signals as
  a `-signals.csv` next to it, one row per sample.
- **.html** downloads the report as one self-contained HTML file that opens
  offline, with no NuBoard and no CDN: images, audio clips and snapshots are
  inlined, logged text and HTML are included, and Plotly and Vega-Lite
  figures stay interactive because their libraries are embedded in the file
  (once each, only when used; Plotly adds about 5 MB). BokehJS is fetched from
  cdn.bokeh.org once, while exporting, for the figure's exact version and
  embedded too; if it cannot be reached, the figure is left out with a note.
  Before exporting you pick the **Theme** (light, dark, or switchable: it
  follows the reader's system theme and has a button to flip it), edit the
  **footer** (by default "Exported with NuBoard 0.8.2 from …", naming the
  version that exported it; empty removes it), and choose whether the
  NuBoard **logo** is the browser tab icon. When the report has audio you also
  pick the **audio player**: **Waveform** (the default) embeds the viewer's
  waveform and spectrogram player once (about 200 KB), with zoom, loops and
  the notes drawn on their lane, following the page's theme; **Simple** uses
  the browser's own player, with the notes listed below as buttons that play
  their section. Waveform figures (`nb.WaveformFigure`) stay interactive with
  either choice: the same accurate plot as the viewer, with zoom, the values
  under the pointer and the clip's audio, whose playhead shows on the plot.
  They embed their audio and signals, so a long one makes a large file (an
  hour at 16 kHz is about 460 MB with one signal). Figures and charts saved
  from the Charts page follow the theme:
  the charts are drawn live in the file from their data at export time (the
  snapshot is used only if the data cannot be loaded). Sweeps and Timeline
  snapshots are images and keep the colors they were taken with.
- **Print** prints the rendered report, or saves it as a PDF, without the
  viewer's menus.

Rename and delete are in the toolbar. Deleting a report removes only its
Markdown file; the runs are not touched.

The demo (`nuboard demo`) writes a sample report in `vit-ablations`.
