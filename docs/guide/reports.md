# Reports

A report is a Markdown document that mixes your own writing with images,
audio, figures and text logged by runs, for a weekly update, a paper draft or
a record of what an ablation showed. Reports are plain files in
`<project>/reports/<name>.md`, so they can be edited by hand, diffed and
committed next to the runs.

## Adding items from the Media page

Every card on the **Media** page has a bookmark button. It asks for a report
and a caption, then appends a line such as

```markdown
![cutmix-s0 at the best val/acc](media:20261016T0815-e8021047/samples/augmented@80)
```

to the end of the report, creating it if needed.

The **Report** field lists the project's reports as soon as it is focused,
most recently updated first, each with its title and file name (the newest
50, then "and N more, type to narrow"); the last one
used is highlighted and taken if you type nothing. Typing narrows the list by
title or file name, ↑/↓ and Enter pick one, and a name that is not in the list
is offered as **New report "name"**. Every bookmark button (Media, Charts,
Sweeps, Timeline) and **Add N to report** use the same field.

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
running, and **Open in Charts** opens it on the Charts page. Hovering it
lists every series' value at that step, best first, as the Inspector does;
a click pins the values.

## Adding the all-runs chart from the Media page

The bookmark button on the Media page's "All runs on one chart" (PR curves
and distributions) adds the chart with every run's item at the step shown:

```markdown
![eval/pr/cat, all runs](files/findings-9c0d1e2f.png "overlay:<run id>/eval/pr/cat@100 <run id>/eval/pr/cat@100")
```

NuBoard draws it live from those items, with the same hover read-outs as on
the Media page and an **Open in Media** button; the PNG, legend included, is
what other Markdown viewers show.

## Adding Sweeps and Timeline plots

The bookmark buttons on the **Sweeps** page (the parallel coordinates and each
scatter) and on the **Timeline** add a snapshot of the plot as shown:

```markdown
![lr sweep](files/findings-5e6f7a8b.png "view:sweeps?project=llm-pretrain&metric=train%2Floss")
```

The title after `view:` is the page and its settings; in NuBoard the image
gets an **Open in Sweeps** (or **Open in Timeline**) button that restores
that view. A Timeline snapshot is an SVG drawing: hovering a bar shows the
run's name, id, status, start, duration and alerts in a card like the
Timeline page's, in NuBoard and in an exported HTML file. In NuBoard, clicking
a bar opens the run.

## Writing

The **Reports** page lists the reports of every project. **New** creates one;
**Write**, **Split** and **Preview** switch between the editor, both side by
side, and the rendered page. A report with text opens in **Preview** and an
empty one in **Split**; once you pick one, it is remembered in this browser.
**Preview** keeps a reading width of about 900 px; **Full width** uses the
whole pane. The button beside **Reports** (or `[`) folds the report list into
a thin bar, also remembered. Changes are saved a moment after you stop typing
(or with Ctrl+S / ⌘+S). Headings, lists, tables, links, code blocks and
images all work; HTML in the Markdown is sanitized.

### Formatting toolbar

The toolbar above the text box writes standard Markdown at the cursor or
around the selection, so the file stays plain Markdown for git, other Markdown
viewers and the exports:

| Button | Writes | Shortcut |
| --- | --- | --- |
| **B**, *I*, U, S | `**bold**`, `_italic_`, `<u>underline</u>`, `~~strikethrough~~` | Ctrl/⌘+B, I, U, Shift+X |
| H1, H2, H3, ¶ | `# `, `## `, `### `, or a plain paragraph | |
| Bulleted list, Numbered list, Checklist, Quote | `- `, `1. `, `- [ ] ` and `> ` on each selected line | |
| `` `c` ``, Code block | inline code and a fenced code block | |
| Link | `[text](https://)`, with the URL selected to type over | Ctrl/⌘+K |
| Horizontal rule, Table | a horizontal rule, and a table of the size you pick | |
| Undo, Redo | undo and redo | Ctrl/⌘+Z, Shift+Z |

Buttons other than the text styles and headings are icons; hover one for its name.

A button shows as pressed when the cursor is inside its formatting, and
pressing it again removes it. Underline has no Markdown syntax, so it is
written as `<u>…</u>`, which the viewer and the HTML export show.

### Inserting images, audio and text files

**Insert** gathers everything a report can hold: **Image**, **Audio**,
**Text file**, **Table**, and shortcuts to the Charts and Media pages for
charts and logged items. **Media item** is grayed out, with "No media logged
in <project> yet", when no run of the report's project logged any media or
text; the run list the viewer already has tells, so opening the menu costs
nothing.

- **Image**: drop, paste (a clipboard screenshot) or choose a PNG, JPEG, GIF
  or WebP file, and add alt text and a caption. It is written as
  `![alt](files/3f2a9c0d1e2b4a5f.png)`, with the caption as an italic line
  below. Dropping or pasting an image straight into the text box does the
  same without the panel.
- **Audio**: drop or choose a WAV, FLAC, MP3, Ogg, M4A or WebM file and add a
  caption. It is written as `[caption](files/3f2a9c0d1e2b4a5f.wav)`, which the
  viewer plays with the waveform player (waveform, spectrogram and zoom) and
  other Markdown viewers show as a link to the file. Dropping an audio file
  straight into the text box does the same without the panel.
- **Text file**: choose or drop a `.txt`, `.md`, `.log`, `.csv`, `.json`,
  `.yaml` or source file, then pick how it goes in. **Inline** pastes its
  content into the report: Markdown as it is, a CSV or TSV as a table (or as
  a code block if you untick **As a table**), anything else as a code block
  under the file's name, with the language taken from its extension.
  **Attached** stores the file and writes
  `[train.log](files/8c1d2e3f4a5b6c7d.log "attachment")`, which the viewer and
  the HTML export show as a collapsible block with the content and a download
  link. Other Markdown viewers show a link to the file.

Uploads are stored in `<project>/reports/files/`, named by a hash of their
content, so the same file uploaded twice is stored once and the project stays
self-contained when it is copied, zipped or committed. The .zip and HTML
exports include them.

The viewer checks every upload on the server: images and audio by their first
bytes (an SVG only if it has no scripts, links or embedded HTML), text by
decoding it as UTF-8 with no NUL bytes. Nothing is converted. An image can be
up to 20 MB, an audio file up to 50 MB and a text file up to 5 MB;
`nuboard up --max-image-mb N --max-audio-mb N --max-text-mb N` changes that. Files are served with a fixed type, `nosniff` and a strict
content security policy, and text files always download, so a renamed HTML
page never runs. Images on other websites (`![x](https://...)`) are not
loaded, since that would tell their host who reads the report and break
offline copies; they show as a link instead. `nuboard up --read-only-reports`
refuses every change to reports, uploads included, for a viewer shared with
others.

An embedded item is rendered in place: images as images, audio with the
waveform player, Plotly, Vega-Lite and Bokeh figures interactively, logged
HTML in a sandbox and text as a block, each with a caption and a link to its
run. The same `media:` lines also work in a run's [notes](viewer.md#run-details-and-compare).

## Sharing

- **.zip** downloads the Markdown with every embedded image and audio
  clip as a file in `files/`, uploaded images and attached files too, figures and HTML as linked files, chart
  snapshots as images, and logged text inlined, so it reads on GitHub or in any Markdown editor without
  NuBoard. A waveform figure becomes its [data bundle](../api/add_figure.md#downloading-the-audio-and-signals),
  a `.zip` with its audio as a `.wav`, one `.npy` per signal and a
  `metadata.json` (sample rate, range, regions, caption, run, key and step).
- **.html** downloads the report as one self-contained HTML file that opens
  offline, with no NuBoard and no CDN: images, audio clips and snapshots are
  inlined, attached files are collapsible blocks with a download link, logged text and HTML are included, and Plotly and Vega-Lite
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
  under the pointer and the clip's audio, whose playhead shows on the plot,
  and the Download menu for the audio (.wav) and the data (.zip).
  They embed their audio and signals, so a long one makes a large file (an
  hour at 16 kHz is about 460 MB with one signal). Figures and charts saved
  from the Charts page follow the theme:
  the charts are drawn live in the file from their data at export time (the
  snapshot is used only if the data cannot be loaded). Hovering a chart lists
  every series' value at that step, and a click pins it; hovering a PR curve
  shows the nearest threshold with its precision, recall and counts, and
  hovering a distribution shows the bin under the pointer for each run.
  Timeline snapshots show a hover card on every bar. Sweeps snapshots are
  images and keep the colors they were taken with.
- **Print** prints the rendered report, or saves it as a PDF, without the
  viewer's menus.

Rename and delete are in the toolbar. Deleting a report removes only its
Markdown file; the runs are not touched.

The demo (`nuboard demo`) writes a sample report in `vit-ablations`.
