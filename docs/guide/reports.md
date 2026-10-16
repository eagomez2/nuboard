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
![cutmix-s0 at the best val/acc](media:20261016-0815_cutmix-s0_ab12cd/samples/augmented@80)
```

to the end of the report, creating it if needed. **Open report** in the
notice jumps to it. Use **best metric** on the Media page first to save the
item at a run's best step.

## Adding charts from the Charts page

The bookmark button above the focused chart on the **Charts** page adds that
chart to a report, as it is shown: the runs, metric, x axis, grouping,
smoothing, zoom and hidden series. It writes a line such as

```markdown
![val/acc by augmentation](files/findings-1a2b3c4d.png "chart:metric=val%2Facc&runs=...")
```

The image is a PNG snapshot of the chart, saved in
`<project>/reports/files/`, so the report shows the chart in any Markdown
viewer. In nuboard the title after `chart:` describes the view, and the
chart is drawn live instead: it follows the theme, updates while runs are
running, and **Open in Charts** opens it on the Charts page.

## Writing

The **Reports** page lists the reports of every project. **New** creates one;
**write**, **split** and **preview** switch between the editor, both side by
side, and the rendered page. Changes are saved a moment after you stop typing
(or with Ctrl+S / ⌘+S). Headings, lists, tables, links, code blocks and
images all work; HTML in the Markdown is sanitized.

An embedded item is rendered in place: images as images, audio with the
waveform player, Plotly, Vega-Lite and Bokeh figures interactively, logged
HTML in a sandbox and text as a block, each with a caption and a link to its
run. The same `media:` lines also work in a run's [notes](viewer.md#run-details-and-compare).

## Sharing

- **Export .zip** downloads the Markdown with every embedded image and audio
  clip as a file in `files/`, figures and HTML as linked files, chart
  snapshots as images, and logged text inlined, so it reads on GitHub or in any Markdown editor without
  nuboard.
- **Print** prints the rendered report, or saves it as a PDF, without the
  viewer's menus.

Rename and delete are in the toolbar. Deleting a report removes only its
Markdown file; the runs are not touched.

The demo (`nuboard demo`) writes a sample report in `vit-ablations`.
