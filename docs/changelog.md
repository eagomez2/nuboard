# Changelog

## 0.21.0

`init` no longer hangs a multi-GPU job when only rank 0 calls it, and a new
Benchmarks page compares nuboard with TensorBoard. One breaking change:
`init(gpus=...)` is now `system_devices`.

- **Breaking: `init(gpus=...)` is renamed `system_devices`**, next to
  `system_metrics` and `system_interval`, so it reads as the devices system
  metrics track, not the devices you train on. Replace `gpus=` with
  `system_devices=`; the old name is gone.
- **`init` no longer hangs a multi-GPU job when only rank 0 calls it**, as is
  usual with TensorBoard (`if rank == 0: run = nb.init(...)`). Rank 0 used to
  broadcast its run id through `torch.distributed` and wait for every rank to
  receive it. It now never waits for other ranks: they find the run through a
  shared job id (`SLURM_JOB_ID`, or torchrun's `--rdzv-id`), and without one
  they log nothing, which loses only other machines' system metrics (#24).
- **Benchmarks** page in the docs: nuboard against tensorboardX and
  `torch.utils.tensorboard`, as interactive charts (exact values and ratios on
  hover), with the script that reproduces it
  (`benchmarks/vs_tensorboard.py`).
- **Full screen** replaces **Expand** in **Files**. A text file taller than
  its 520 px box opens full screen, as charts do: it fills the screen and
  scrolls inside however long it is, and **Exit full screen** or Esc brings
  it back. The page around it no longer grows with the file, so a huge log
  can't stretch it. A file that fits its box has no button.
- **Only changes** and the **Diff … against …** run menus are also in a full
  screen diff, so a long file compared between runs can be cut down to the
  lines that differ without leaving it.

## 0.20.1

The Files tab no longer jumps back to the top while a run is live.

- **The Files tab keeps its scroll on live runs.** A running run's
  heartbeat no longer reloads the open file, so a long file such as a
  `config.yaml` stays where you scrolled instead of jumping to the top.
  A text file the run is still writing is read again as it reports in and
  grows in place, following new lines only when you are at its end (#21).
- **Expand** next to a text file in **Files** or a pinned tab shows it at full
  height instead of in a 520 px box; the choice is remembered (#21).
- The demo's live run saves a `config.yaml` and writes a growing
  `files/progress.log`.

## 0.20.0

The first release on PyPI: `pip install nuboard` (or `uv pip install nuboard`).

- **`nuboard rm`** deletes runs chosen by a query (`-q 'status = crashed'`)
  or by id or name (`--run`, repeatable). It lists the runs with their sizes
  and deletes nothing until you confirm; `--dry-run` and `--yes` work as in
  `merge`. Running runs are skipped unless `--include-running`, artifact
  versions the runs produced are kept, and with neither a query nor `--run`
  it refuses, so it never deletes every run by accident (#18).
- **Command line reference.** A new [page](reference/cli.md) lists every
  command with its options and defaults (#18).
- **Known limitations** have their own [page](reference/limitations.md).
- **Viewer pages can't be framed by another website**, so a page you visit
  cannot overlay the viewer to trick clicks, and the sign-in form no longer
  follows a `next` link with a backslash to another site.
- **`pip install nuboard` includes the viewer.** NumPy, PyArrow, Starlette
  and uvicorn are now regular dependencies, so `nuboard up` works without
  `[viewer]`; `nuboard[viewer]` still installs. Logging still uses only the
  standard library and imports none of them.
- Package metadata for PyPI: project links and classifiers. The docs are
  published at <https://eagomez2.github.io/nuboard/>, and GitHub workflows run
  the tests and publish the docs.

## 0.19.2

- **`nuboard merge SRC DEST`** merges a project logged on two machines into
  one folder. It shows the full plan first (runs to copy, identical items,
  conflicts, renamed or renumbered items) and writes nothing until you
  confirm. It copies what DEST lacks and never overwrites or deletes:
  clashing artifact versions are renumbered and copied runs repointed,
  collections and hide rules are combined, and a report or view that differs
  is copied next to DEST's. `--dry-run`, `--yes`, `--json`, `-v`,
  `--project` and `--include-running` (#16). See
  [Working on several machines](guide/machines.md).

- **TensorBoard import: videos and meshes.** `import-tensorboard` now imports
  `add_video` clips (animated GIFs) as videos and `add_mesh` summaries as
  point clouds with their colors, instead of an image and a skipped plugin.
- **Small charts show values on hover.** Hovering a chart in the **All
  scalars** grid shows each run's value at the cursor, best first, up to eight
  and "+N more" (#3).
- **A pinned step shows on every chart.** While the main chart is pinned,
  every small chart draws a dashed line at that step with a dot on each
  curve, and hovering one shows its values there (#3).
- **Full scalar names under small charts**, wrapping instead of cut off;
  **Full names** in the display row turns them off (#3).
- **Timeline hover cards in reports.** A Timeline snapshot in a report shows
  the Timeline page's hover card on each bar (name, id, status, project,
  start, duration, alerts) in the preview and in exported HTML, instead of a
  slow browser tooltip; in NuBoard, clicking a bar opens the run (#3).
- **More room for reports.** A report with text opens in **Preview** (the
  view you pick is remembered). The report list and the **Workspace** list on
  the Runs page fold into a thin bar with their button or `[`, remembered per
  browser (#3).

- **Datasets as Sweeps parameters.** The artifact versions each run used are
  parameters named `inputs.<artifact>` (`v1`, `v2`), so runs can be compared
  by data version without copying it into the config (#14).
- **Readable list and dict values in Sweeps.** Axis labels, scatter labels and
  the Best runs table show only what differs between values (`[0]=0.08`,
  `flip, mixup`, `[1].dim=512`), with the full value on hover and, on click,
  pretty-printed with a **Copy** button (#14).
- **Split a list into element axes.** A list of plain values with one length
  in every run can be split in the picker into `key[0]`, `key[1]`, ..., kept
  in the URL as `split=` (#14).
- **The demo shows them.** Half of the `llm-pretrain` sweep trains on the
  older `fineweb-edu:v1` (a little worse), and `vit-ablations` runs have
  list-valued `transforms` and `crop_scale` settings. Delete an existing demo
  folder to get the new data.

## 0.19.1

- **Sweeps parameter picker.** **Parameters** opens a searchable list of every
  differing key, grouped by prefix, with its type, number of values and
  correlation with the objective. Chosen keys are chips you can drag to
  reorder and remove with **×**. **Clear all** and **Reset to defaults** are
  in the list.
- **Better default parameters.** With nothing picked, Sweeps shows up to six
  keys, the most correlated with the objective first, leaving out seeds,
  paths, id-like keys, long text and keys with many values. The last choice is
  remembered per project.
- **Hide rules for Sweeps.** A project can hide keys from the picker with a
  filter such as `!seed !.path`, saved in `<project>/sweeps.json`.
- **Categories with many values** keep their 11 most common values on the axis
  and gather the rest in **(other)**.

- **`nuboard demo` no longer piles up runs.** Run again on a folder that
  already holds the demo, it opens it instead of adding 31 more runs each
  time, so it starts in about the same time on every run. Delete the folder
  for a fresh demo.

- **Open selected runs in Charts and Sweeps.** The Runs selection bar has
  **Charts** and **Sweeps** next to **Media**. Charts,
  Sweeps, Media and Timeline show a **Showing N selected runs** banner while
  limited to a selection, with buttons to the other pages (which keep it) and
  **Show all**; **Clear selection** also drops it from the URL (#7). A run
  opened for inspection (or the runs being compared) has the same **Charts**,
  **Sweeps** and **Media** buttons after its tabs.

- **Report picker.** The **Report** field of **Add to a report** (every
  bookmark button, and **Add N to report** on Media) lists the project's
  reports as soon as it is focused, newest first, with their titles and file
  names. Typing narrows it by title or name with the matches highlighted, ↑/↓
  and Enter pick, the last used report is highlighted (and taken when nothing
  is typed), and a new name is offered as **New report "name"**. It lists the
  newest 50 and counts the rest, which typing reaches (#12).
- **Audio in reports.** **Insert → Audio** (or dropping an audio file on the
  text box) uploads a WAV, FLAC, MP3, Ogg, M4A or WebM file, checked from its
  bytes and capped at 50 MB (`--max-audio-mb`), and writes
  `[caption](files/<hash>.wav)`. It plays with the waveform player in the
  preview, is copied by the .zip export and embedded in the HTML export with
  the player chosen there (#12).
- **Report toolbar icons.** Link, lists, checklist, quote, code block, rule,
  table, undo and redo are drawn as theme icons instead of emoji and symbols,
  so they follow the light and dark themes and the pressed color (#12).
- **Media item is grayed out** in **Insert** when no run of the report's
  project logged media, saying so. Runs now record `media_count` in
  `run.json` with each write they already make; runs from older versions are
  checked once for a media pack when indexed (#12).

- **Reproducibility.** A new [guide](guide/reproducibility.md) explains what a
  run records, how to replay it, and what is not covered. `init` now:
  - removes any user, password or token from the recorded git remote URL;
  - records the repository of your code: `code_dir=` if given, else the
    running script's folder, else the working directory (`git.source`), with
    a warning when the script and the working directory are in different
    repositories;
  - records `git.pushed` (whether a remote-tracking branch has the commit)
    and `git.untracked` (how many untracked files, never their names),
    shown and highlighted in **All settings**;
  - keeps the commit of packages installed from git in `requirements.txt`,
    without credentials;
  - records the folder and git state of packages installed from a local
    folder (`pip install -e ../lib`): a clean, pushed checkout becomes an
    installable `git+URL@commit` line, uncommitted changes are saved as
    `files/git-<package>.patch` (#13);
  - never lets a repository's config run a program during capture
    (`core.fsmonitor` off, diffs with `--no-textconv`), and skips patches over
    10 MB, recording `git.patch_bytes` instead (#13);
  - records what it can in a repository with no commits, on a detached
    `HEAD`, from a deleted working directory or with broken package
    metadata, and never fails the run over it (#11).
- **Report editor: formatting toolbar and Insert menu.** Buttons for bold,
  italic, underline (`<u>`), strikethrough, headings, lists, checklists,
  quotes, code, links, rules and tables write plain Markdown, with Ctrl/⌘+B,
  I, U, Shift+X and K, undo and redo, and show as pressed when the cursor is
  inside their formatting (pressing again removes it). **Insert** adds an
  **Image** (pick, drop or paste, with alt text and a caption), a **Text file**
  (inline as Markdown, a table or code, or attached as a collapsible block with
  a download link), a **Table**, or goes to Charts and Media. Dropping or
  pasting an image into the text box uploads it too (#4).
- **Uploads are checked and stored in the project.** They go in
  `reports/files/`, named by content hash, and are part of the .zip and HTML
  exports. The server checks the bytes (PNG, JPEG, GIF, WebP or a plain SVG;
  UTF-8 text with no NUL bytes), caps sizes at 20 MB for images and 5 MB for
  text (`--max-image-mb`, `--max-text-mb`), and serves report files with a
  fixed type, `nosniff` and a strict CSP; text files always download.
  `nuboard up --read-only-reports` turns off every change to reports.
- **Report images from other websites are not loaded**; they show as a link.
- **Filter the settings of compared runs.** A filter box in **All settings**
  narrows its rows by key: plain text, `/regex/` (or the **.\*** toggle),
  `!exclusions` and several terms at once, optionally matching values too. It
  works with **Only changes**, shows "12 of 340 keys", highlights the matches
  and is kept in the URL. `/` focuses it and `Esc` clears it (#9).
- **Sweeps sees every config key.** A key that differs between runs gets a
  parameter chip however deep it sits in a large config. Sweeps read its
  parameters from the run list, which keeps only the first 64 config values of
  each run, so later keys (such as
  `generator.config.weighted_sir_db.edge.min`) were missed. It now asks the new
  `GET /api/sweep-keys?runs=...` endpoint, which returns every differing key
  with each run's value; the run list stays small.
- **The demo shows it.** `speech-denoise` runs now carry a long training-mix
  generator config, and differ in `generator.config.weighted_sir_db.edge.min`,
  its 73rd value: open Sweeps on that project to see the chip.

## 0.19.0

- **Download a waveform figure's audio and signals.** Waveform figures
  (`nb.WaveformFigure`) have a Download menu next to **Fit**, on the Media
  page, in the large view, in report embeds and in exported HTML:
  **Audio (.wav)** saves the audio exactly as logged, and **Data (.zip)** a
  bundle of `audio.wav`, one float32 `.npy` per signal and a `metadata.json`
  with the sample rate, signal names, range, regions, caption, notes, run, key
  and step. The raw item, which no other tool could open, is no longer offered.
- **The report .zip export writes the same bundle** for a waveform figure,
  instead of a `.wav` and a `-signals.csv` that lost the regions and range and
  grew to millions of rows for long clips.
- **`nb.WaveformFigure.load(path)`** rebuilds a figure from a bundle; logging
  it again stores an identical figure. **`run.waveform(key, step)`** in the
  analysis API returns `(audio, sample_rate, signals, meta)` without
  downloading.
- Other media downloaded from their card get a file name extension from their
  type (`.png`, `.wav`, `.json`, ...).

## 0.18.0

- **Interactive charts in reports and exported HTML.** A chart saved from the
  Charts page lists every series' value at the step under the pointer, best
  first, as the Inspector does, in the viewer and in the exported HTML file;
  a click pins the values. In the exported file, PR curves show the nearest
  threshold with its precision, recall and TP/FP/TN/FN counts on hover, and
  distributions the bin under the pointer for each run, as in the viewer.
- **The all-runs chart in reports.** The "All runs on one chart" overlay on
  the Media page can be added to a report, where it is drawn live from the
  logged items (hover, legend, **Open in Media**), and exported to HTML with
  its hover read-outs. It also downloads as a PNG with its legend.
- **Timeline snapshots are SVG.** A Timeline added to a report is saved as an
  SVG drawing, sharp at any size, with a hover title on every bar (name, id,
  status, start, duration, alerts) in the viewer and in exported HTML.
- **Best-step mode** on the Media page always shows the choice last made:
  an answer for an earlier choice (Lowest before Highest, another scalar, a
  live refresh) could arrive later and show the other end. The line under the
  cards now says Lowest or Highest, and notes when the nearest logged item is
  from a different step than the best value.
- **Open the all-runs chart large.** The "All runs on one chart" overlay of
  PR curves and distributions on the Media page has a magnifier button that
  opens it in the large view, as single cards do; Esc closes it. It can also
  be downloaded as a PNG, with its legend, or added to a report as a snapshot
  with an **Open in Media** button.
- **Run ids on the Timeline.** Each row shows the end of the run id after the
  name, so runs with the same name can be told apart, and hovering a bar
  shows the full id.
- The AP next to a PR curve says what it is on hover (average precision, the
  area under the curve), and the docs say how it is computed.
- **Space plays and pauses audio in full screen.** Waveform figures and the
  audio player toggle playback with Space while in full screen, and only
  there: outside full screen, while typing (such as a note) or with Ctrl, Alt,
  Cmd or Shift, Space does what it did before, and Esc still leaves full
  screen. The audio player used to take Space whenever it had focus; it no
  longer does outside full screen.
- **Artifacts with many files stay fast in the viewer.** The Artifacts page
  no longer loads every version's file list: each version comes with its file
  count and size, and its files load 1,000 at a time when you open it, with
  **Show more** and a path filter. Before, one version with a million files
  slowed the whole page. The **New version** form warns from 10,000 files and
  suggests referencing shards or an index file instead.
- **New: `nuboard artifact unlink` and `nuboard artifact restore`.** They
  unlink a version (or with `--all`, every version) and restore one, as the
  viewer does: nothing is deleted. `nuboard artifact ls --unlinked` lists
  unlinked versions too.
- **Docs:** [Recommendations](guide/artifacts.md#recommendations) for
  registering data: shards over millions of files, when to hash, versions as
  snapshots. The guide no longer says references are checked by modification
  time: they are checked by size.
- **New: `init(gpus=...)` picks the GPUs that system metrics track**, by the
  device names your script uses: `gpus="cuda:0"`, a list such as
  `["cuda:0", "cuda:1"]`, a `torch.device`, `"mps"` or `"all"`. A name that
  cannot be tracked raises `ValueError`. See
  [Choosing GPUs](api/init.md#choosing-gpus).
- **Changed: GPU metrics respect `CUDA_VISIBLE_DEVICES`.** Only the GPUs the
  process can use are tracked, named by the index the script sees, so with
  `CUDA_VISIBLE_DEVICES=2` the machine's third GPU logs as `system/gpu0/...`.
  Without the variable nothing changes. `run.json`'s `env.gpus` lists the same
  GPUs, now with `device`, `index` and `uuid`.
- **Breaking: `all_ranks` is removed** from `init`, `add_scalar` and
  `add_text`. In distributed training only rank 0 logs, and the calls are
  no-ops on other ranks. The viewer only plots rank 0, so values from other
  ranks could not be seen anyway. System metrics are still sampled by local
  rank 0 of each machine. Drop the argument from your calls; runs logged
  before keep their per-rank files and still load.

## 0.17.1

- **Fixed: a pinned point now follows the chart when you zoom or pan.** In
  Charts, the dots of a pinned point kept their place on screen while the
  axes changed under them, and disappeared once the data for the new range
  loaded. They now stay on the points they mark.

## 0.17.0

- **Breaking: `init(name=...)` is now `init(run_name=...)`**, so it reads as
  the pair it forms with `run_id`. `run_name` is a free label shown in the
  viewer; it is no longer sanitized, since it is not part of any path.
- **New run ids.** The default `run_id` is `<YYYYMMDDTHHMM>-<hash>`, such as
  `20261001T1833-48ad8bb2`: a local timestamp plus 8 random hex digits,
  redrawn if the folder already exists. The run name is no longer part of the
  id. You can still pass your own `run_id`; existing runs keep their ids.
  TensorBoard imports use the same shape, with a hash of the source folder.
- Charts: a **Ranges** switch hides the shaded bands (group mean ± std or
  min–max, logged low/high bounds, rank ranges) when they clutter the chart.
  It is saved with charts added to reports. Smooth and the display switches
  moved to their own row under the grouping and x-axis controls.
- Charts: **Ctrl/⌘ + mouse wheel** (or a trackpad pinch) zooms the focus
  chart around the cursor, also past the ends of the data, with y fitted to
  the view; **Alt + wheel** zooms both axes; **Shift + drag** pans in any
  direction and **Shift + wheel** along x. The view stays put while finer data
  for it loads, and the data comes with a margin on each side so smoothing does
  not restart at the edge. Dragging still zooms to a range and double-click
  still resets.
- Charts: the inspector's latest values leave out hidden series, and take the
  last value in the zoomed range.
- Timeline: **Day / Week / Month / Year / All** windows with **‹ ›** to step
  through time, Ctrl/⌘ + wheel zoom around the cursor, Shift + wheel or
  Shift + drag to move, and month and year ticks on long ranges.
- **Calmer live updates.** Charts redraw new points only while you are not
  zoomed, pinned or hovering, with a **Live** switch and a **New data ·
  Update** button otherwise. That button and **Reset zoom** sit in the chart's
  fixed-height header, a slow fetch shows a small spinner instead of swapping
  text, and metric tabs stay on one row, so nothing moves when data arrives. Runs table rows hold still under the pointer.
  Media, Sweeps, Timeline, Artifacts and Reports no longer change under you:
  a **New results · Refresh** button appears instead, and heartbeat-only
  changes are ignored.
- Audio players label the waveform's amplitude (±1 full scale, per
  channel), with an **Amplitude axis** switch on the Media page.
- Waveform figures (signals and region lanes, such as VAD) get a full screen
  button like the audio player's, in Media and in exported reports.
- Run details follow the run's status, duration and summary live, so a run
  that finishes shows **Finished** there too.
- Tables: a highlighted row no longer gets a rounded corner when it is the
  last row; table frames have square corners.
- Updated the screenshots in the docs.
- **Waveform figures.** `run.add_figure(key, nb.WaveformFigure(audio,
  sample_rate, signals))` logs audio with signals over its waveform, one value
  per sample, such as a voice activity probability or a gain mask. The viewer
  draws it as a plot that is accurate at every zoom (M4 decimation: the first,
  smallest, largest and last sample of each pixel column, recomputed as you
  zoom), fast on files an hour long, down to single samples. Hovering shows
  the exact values at a sample; the clip plays from where you click. It is
  listed under **Figures**; `add_audio` and its spectrogram player are
  unchanged. `regions=` adds labelled tracks from training (a list of
  segments, a class per frame, or multi-hot frames for classes that overlap),
  drawn in lanes under the plot. Dragging selects a section to loop, zoom to
  or note; notes are kept apart from the logged regions, in the run's
  `annotations.json`. In a report, an HTML export looks and works the same,
  offline, with its audio, regions and notes, and a .zip export writes its
  audio as a WAV and its signals as a CSV. See
  [`add_figure`](api/add_figure.md#waveforms-with-signals).
- The demo's `speech-denoise` runs log `vad/enhanced`, a waveform figure of
  the enhanced output with a speech probability and target, predicted and
  overlapping event tracks, with notes on the first one's false alarms; its
  listening report embeds one.

## 0.16.0

- **Jobs.** A second process can log into a running run with
  `nb.init(..., run_id=ID, job="eval")`, for example an evaluator that scores
  checkpoints while training goes on. Its scalars share the run's step axis,
  and it never changes the run's status, heartbeat or summary: its own state
  goes in `jobs/<job>.json`, its console in `files/output.<job>.log` and its
  system metrics under `system/<job>/`. The viewer shows each job as a chip
  next to the run. A job can only join an existing run, the same job cannot
  run twice at once, and logging a name the main job also logs gives a
  warning. The last job to end compacts the run. See
  [Evaluating while training](guide/jobs.md), which includes a checkpoint
  queue recipe. Runs without jobs are unchanged, and older versions still read
  new runs (without the jobs).
- **Storage.** A disk button in the left rail shows how much space runs,
  artifacts and other files take, per project and per run. The Artifacts page
  has the same button for artifact versions. It is measured only when you
  press **Measure** or **Refresh**, pauses after 10 s on large folders to ask
  before going on, and counts only what is stored in the folder: a referenced
  artifact counts its manifest, with the size it points to shown apart.
- Sweeps: the scatter plots under the parallel-coordinates chart no longer
  scale their axis labels with the plot width; text keeps the same size with
  one column or four.
- The demo's `convtasnet` run has an `eval` job that logged `eval/dnsmos`.

## 0.15.8

- **Access token off localhost.** `nuboard up --host` with an address other
  than `127.0.0.1` now protects the whole viewer with a token, like Jupyter:
  it prints a link with a random token, and opening it signs the browser in.
  Without the token, pages show a sign-in form and API calls get a 401.
  `--token VALUE` or `NUBOARD_TOKEN` sets a fixed token and `--no-token` turns
  it off. Scripts send `Authorization: token VALUE`. On `127.0.0.1` nothing
  changes. If you already serve on `0.0.0.0`, open the printed link once, or
  pass `--no-token` to keep the old behavior.
- Changes sent from a page of another website through your browser are
  refused, with or without a token.
- **Adding artifact versions in the viewer.** Started with
  `--edit-artifacts`, the Artifacts page has **New version**: a form that adds
  a version by reference to a file or folder (absolute, `~`, `$VAR` or
  relative to the served folder), checks the path as you type, and shows a
  review step before adding. Nothing is copied or uploaded.
- **Unlinking.** With `--edit-artifacts`, **Unlink version** moves a version
  to `artifacts/.unlinked/` after a confirmation, without deleting any file.
  **Show unlinked** lists them, and **Restore** puts one back. Runs show such
  a version as "(unlinked)", and version numbers are never reused.
- Without `--edit-artifacts`, artifacts are read-only in the viewer, as before.

## 0.15.7

- New `run.add_scalar_baseline(key, value, *, low=None, high=None)` sets a
  reference value for a scalar, such as the score of the unprocessed input:
  `run.add_scalar_baseline("val/pesq", 1.31)`. It is linked to the scalar by
  name, saved in `run.json` right away, and replaced by calling it again; a
  dict sets several at once.
- Charts draw it as a dashed horizontal line, with a light band for `low` and
  `high`. Runs with the same baseline share one gray line; a baseline only one
  run has is dashed in its color. Hiding or highlighting a run does the same to
  its baseline, grouped charts use each group's mean baseline, and the y-axis
  keeps baselines in view. The inspector lists each baseline and its runs.
- A **Baseline** switch next to **Points** turns them off. It shows only when a
  run has a baseline, so other charts look as before. Charts saved to reports
  and exported to HTML keep the setting.
- The demo's `speech-denoise` runs have PESQ and SI-SDR baselines.

## 0.15.6

- `add_scalar` takes optional `low` and `high`, a range around the value such
  as mean ± std over an epoch: `run.add_scalar("val/loss", mean, step=epoch,
  low=mean - std, high=mean + std)`. Charts shade the range around each run's
  line, and the inspector shows it after the value. Scalars logged without
  them work exactly as before. When runs are grouped (for example several
  seeds), the band shows the spread across runs as before.
- The demo's `llm-pretrain` runs log `eval/loss` with a range.

## 0.15.5

- Console logs show their colors. Color codes (the 16 terminal colors,
  256-color and true color, bold, dim, italic, underline, inverse) are drawn
  instead of removed, with terminal colors that suit the light and dark
  themes. **Raw** shows the text as stored. The log file is unchanged.
- In the Files tab and pinned tabs, any text file with color codes or
  progress bars (such as `output.log` or your own `.log` files) is drawn the
  same way instead of showing the codes, and two runs' logs are diffed by
  their visible text, so a change of color alone is not a difference.

## 0.15.4

- Labels start with a capital letter everywhere in the viewer: toggles,
  buttons and menus (**Best** / **Last**, **Show archived**, **No grouping**,
  **Wall time**, **Ignore outliers**, **Log y**, **Pick step**, **Waveform**,
  **One row per run**, **Packed**, ...), hints, tooltips and run statuses
  (**Finished**, **Running**, **Crashed**). Only the first word is
  capitalized. Names that come from your data (scalars, config keys, run
  names, tags, captions) are shown as written, and queries still use
  lowercase statuses (`status = "finished"`).

## 0.15.3

- Files tab: the tree is on top, full width, about 12 rows tall with its own
  scroll bar and a corner to drag it taller; the preview and diffs use the
  full width below it. Long names lose their middle rather than their end,
  and the full path shows on hover. `files/` starts open, other folders
  folded.
- The row of tabs no longer has a tab for every file in `files/`; Console
  stays. Instead, any file can be **pinned** as a tab, by path or by a
  pattern such as `checkpoints/*/best_*.pth`, which picks each run's own
  match (newest first) so differently named files are compared side by
  side. Pins are shared by everyone through `<project>/pins.json`.

## 0.15.2

- Run details and Compare have a **Files** tab that lists every file in the
  run folder as a tree, with the number of files and their size per folder.
  NuBoard's own data files are hidden unless asked for. Text files (logs,
  YAML, JSON, CSV, patches, code) are shown, up to their first 2 MB, and
  diffed side by side between two runs; images are shown; every file can be downloaded.
- Checkpoints (`.pt`, `.pth`, `.ckpt`, `.bin`, `.safetensors`, `.npy`,
  `.npz`) list their keys as a tree with each tensor's shape, dtype and size,
  plus the total parameter count. Between runs the keys are diffed (added,
  removed, changed shape or dtype). PyTorch is not needed, and no code in a
  checkpoint ever runs: the pickle is read with every class replaced by an
  inert placeholder. A malformed, cut-off or hostile file shows what could be
  read and why the rest could not, and never stops the viewer.
- Compare: the All settings table has the same borders as the other tables.
  Changed rows were picking up the file diff's styles.

## 0.15.1

- Ctrl+C stops `nuboard up` at once, even with a viewer tab open. Before, the
  open live-update connection kept the server waiting forever.
- The run table never cuts values off: every column is as wide as its widest
  value, and a table wider than the window scrolls sideways. All config keys
  that differ between runs are shown, not only the first eight. Notes are the
  one column still capped; their full text is in the notes editor.
- The Columns menu has a search box, so a column is easy to find among many
  scalars and config keys.
- Charts: the big chart has an **All N** picker that searches every scalar,
  so any of them can be brought into focus. With more than 12 series, the
  legend shows the first 10 and a "+N more" button, plus a filter that
  matches run names and config values (`lr=3e-4`, `layers=24`); **Only
  these** hides every series that does not match.
- Charts: scalar sections fold like Media sections, with Expand all and
  Collapse all. With more than six sections only the first three start open;
  what you open or close is remembered.

## 0.15.0

- `nuboard artifact add` adds an artifact version from the command line.
  Give every value as a flag, or run it in a terminal and it asks for what is
  missing, one field at a time. Each answer is checked as you enter it (the
  project and name, that the path exists and holds files, the store, the
  type, a non-empty description), `<` goes back a field, metadata can be
  added, edited and deleted with its type shown, and nothing is written until
  you confirm the review. Without a terminal or with `--no-input` it never
  asks; every invalid or missing flag is reported at once. `--dry-run`
  checks without writing.
- `nuboard artifact ls` lists artifact versions, and `nuboard artifact show`
  prints one and checks its files.
- Artifact versions have a `description` (`add_artifact(..., description=)`),
  and the manifest records who created each one (`created_by`: user, host and
  command). The Artifacts page shows both.

## 0.14.1

- A leading `~` is expanded in artifact paths and in `NUBOARD_DATA_DIR`, so
  `nb.add_artifact("datasets", "fineweb-edu", "~/data/fineweb-edu", reference=True)`
  works as written.

## 0.14.0

- Reference artifacts: `add_artifact(..., reference=True)` records where a
  file or folder is, with each file's size and modification time, and copies
  nothing, for datasets that live on shared storage. `checksum=True` also
  hashes every file. `use_artifact` warns when a version's files are missing
  or changed in size since it was made, and `Artifact.verify()` lists them.
- References work across machines: a path inside `$NUBOARD_DATA_DIR`, or one
  written with any environment variable (`"${IMAGENET}/train"`), is stored
  with the variable and expanded where the artifact is used, so one version
  points at the laptop's copy on the laptop and the cluster's on the
  cluster.
- Artifacts across projects: `run.use_artifact("datasets/fineweb-edu:v2")`
  uses an artifact of the `datasets` project from a run in any other project,
  and `run.add_artifact("datasets/fineweb-edu", ...)` adds one there. The
  run's `inputs` and `outputs` record the other project (`project`,
  `project_path`). An artifact name can no longer contain `/`.
- `nb.add_artifact(project, name, path, ...)` adds a version without a run,
  such as a dataset no script produced, and `nb.get_artifact(ref)` finds one
  without recording it, such as in a notebook.
- Artifacts page: projects that hold only artifacts are listed, a project's
  list includes the artifacts its runs used from other projects, references
  show where their files are, and the `use_artifact` line names the project.
  Run details show another project's artifact as `project/name:vN`.
- The demo keeps its datasets in `shared-data/`, registered as references in
  a `datasets` project that `llm-pretrain` and `vit-ablations` use.
- The [Artifacts guide](guide/artifacts.md) now explains how to organize
  datasets, checkpoints and projects.

## 0.13.3

- Fixes `NotADirectoryError: ... runs/.DS_Store/run.json` on macOS: a file
  where a run, project or artifact folder is expected, such as the
  `.DS_Store` that Finder leaves in folders it has shown, is now skipped.
  This broke `nuboard demo` on a folder that already had demo runs, and
  listing artifacts with a stray file in `artifacts/`.

## 0.13.2

- Fixes `pnpm install` in `frontend/`, which failed with "No matching version
  found for eslint@^10.13.1": the 0.13.0 version bump had also changed
  eslint's version range in `package.json`. It is back to `^10.12.0`, as in
  the lockfile, and a test now checks that `package.json` and
  `pnpm-lock.yaml` agree and that every version string matches.

## 0.13.1

- Saved views can be deleted from the Runs page: hover a view in the
  workspace list and click **×**, then confirm. The view's file in
  `<project>/views/` is removed; runs, collections and reports are not
  touched. The **×** of views and collections also shows when the row has
  keyboard focus.

## 0.13.0

- Breaking: `run.log` is removed; `run.add_scalar` is the one way to log
  scalars. Replace `run.log(data, step=s)` with `run.add_scalar(data, step=s)`,
  which takes the same dict and keyword arguments. The docs, examples, tests
  and benchmarks use `add_scalar` throughout.

## 0.12.0

**Logging**

- `run.add_scalar` logs scalars, named as in TensorBoard:
  `run.add_scalar("train/loss", 0.42, step=10)` logs one, and
  `run.add_scalar({"train/loss": 0.42, "train/lr": 3e-4}, step=10)` several,
  which covers TensorBoard's `add_scalars` too. `run.log` keeps working as
  the same call (removed in 0.13.0).
- `run.add_video` logs clips from `(T, H, W, C)`, `(T, C, H, W)` or
  `(N, T, C, H, W)` arrays and tensors, encoded as looping animated PNGs with
  no ffmpeg needed, or MP4, WebM, MOV, Ogg and GIF files as they are. The
  Media page has a **Video** kind with a frame player, and the `ppo-atari`
  demo logs rollout videos.
- System scalars: `nb.init` samples CPU, memory and GPU use every 30 seconds
  into `system/` scalars, from `LOCAL_RANK` 0 of each machine. GPUs are read
  with `nvidia-smi`, and PyTorch's CUDA and MPS allocators are read when the
  script has imported torch. Turn it off with `system_metrics=False`, pick
  groups with `system_metrics=["cpu", "memory", "gpu"]`, and change the rate
  with `system_interval`.
- Console capture: what the script prints to stdout and stderr, including
  the traceback of a crash, is also written to `files/output.log` and shown
  as **Console** in the run details. Turn it off with
  `capture_console=False`.
- PyTorch tensors passed to `add_image`, `add_audio`, `add_histogram`,
  `add_point_cloud` and `add_video` are copied to NumPy before the call
  returns, so changing the tensor in place afterwards no longer changes what
  is logged. `bfloat16` tensors work.

**Naming**

- Docs, labels and the Python API say "scalar" instead of "metric", as
  TensorBoard does: **All scalars**, **X axis scalar**, **best scalar**.
  `RunReader.scalar_names` replaces `metric_names`, which stays as an alias.
- Breaking: `RunHandle.scalars()` and `Project.scalars()` in the analysis API
  name their first column `key` instead of `metric`.
- The file format is unchanged, and so are saved views, report charts and
  query syntax.

**Docs**

- The Python API section has a page per method, all listed in the menu,
  including `add_video` and the new `nb.init` options.

## 0.11.0

**Runs table**

- Tags can be edited in the viewer. In a run's details, the tag button under
  its name removes a tag with × and adds one by typing, with the project's
  tags suggested. **Tags…** in the selection bar adds and removes tags on
  every selected run, keeping each run's other tags. Once edited, a run's tags
  replace the ones it logged, so those can be removed too; `run.json` keeps
  the logged ones.
- Custom fields and properties are now one thing, properties. **Set field…**
  is now **Set property…**: it picks a property, then its value with a control
  that fits its type (buttons for a choice or yes/no, pills for tags, a date
  picker), and a new name is defined with its type first. **Columns** lists
  every property of the listed projects under **Properties**, marks values
  without a definition as untyped, and **New property…** defines one and shows
  it as a column. In a run's Properties tab, **untyped · define** gives such a
  value a type. The stored format is unchanged.

**Docs**

- A **Python API** section describes every call, in the style of PyTorch's
  `SummaryWriter` reference: its signature, parameters, the shapes and dtypes
  it accepts, what it stores and how big, what the viewer shows, a complete
  example and a picture of the result. It ends with a table mapping each
  `SummaryWriter` method to NuBoard.
- **Get started** walks through training a small NumPy network on a spiral
  with three learning rates, logging scalars, images, PR curves,
  distributions, a point cloud and a table, then reading them in the viewer.
  The script is `examples/get_started.py`.
- The examples in the API pages run as tests, so they stay correct.

## 0.10.2

- The Columns menu of the runs table floats above the page, so a table with
  only a few runs no longer cuts it off.

## 0.10.1

- HTML export draws audio with the viewer's waveform and spectrogram player,
  embedded once in the file and working offline, with notes on its lane and
  the page's light or dark theme. When a report has audio, the export dialog
  offers **Audio player**: Waveform (default) or Simple, the browser's own
  player as before.

## 0.10.0

**Media**

- Distributions: `run.add_histogram(key, values)` stores bin counts and the
  values' min, max, mean and standard deviation, as TensorBoard's histograms
  do. They show with the figures: each card draws the chosen step filled with
  the step before it dashed, hovering shows a bin's share, and **over steps**
  shows the median and 68%, 86% and 100% bands across training. A chart above
  the cards overlays every run. They export to HTML, and the `vit-ablations`
  demo logs weight, gradient and logit-margin distributions.
- `nuboard import-tensorboard` imports histograms (TF1, TF2, PyTorch and
  tensorboardX), re-binned into 50 even bins.
- Point clouds: an **axes** button draws x, y and z axes with round values.
  `add_point_cloud(..., axes=True)` shows them from the start, and three names
  label them, as the demo's embeddings do.

## 0.9.1

- The run details panel (click a run name) shows the run's tags under its name,
  and updates when they are edited.
- Roadmap: dropped the finished TensorBoard import item and the old Runs table
  item (TanStack Virtual, Bits UI).

## 0.9.0

**Media**

- Tables: `run.add_table(key, rows)` logs per-example results, with audio and
  image cells (`nb.Audio`, `nb.Image`). The viewer compares each cell with the
  same row at the previous or first step, tinted green or orange with the
  change next to it, and rows glide to their new place as the step slider
  moves. Tables sort, filter (`snr_in < 0 and noise = babble`), show a trend
  per row and open a row's history and media. They export to HTML, and
  `RunHandle.table()` reads them back. The `speech-denoise` demo logs a table
  of 40 test files per eval, and its new `listening-notes` report shows it
  with audio notes.
- PR curves: `run.add_pr_curve(key, labels, predictions)` counts true and
  false positives at evenly spaced thresholds, as TensorBoard does, and stores
  only the counts. Each run's curve shows with the figures, all runs are
  overlaid on one chart above them, and hovering shows the threshold and
  counts. `nuboard import-tensorboard` imports TensorBoard's PR curves, and the
  `vit-ablations` demo logs three of them.
- Point clouds: `run.add_point_cloud(key, points, colors=...)` logs an
  `(N, 3)` cloud (lidar scans, mesh samples, 3D projections of embeddings).
  The Media page draws it in a view you can rotate, pan and zoom, colored by
  the logged colors or by height, with a step slider per run. It works in
  reports and in HTML exports. The `vit-ablations` demo logs eval embeddings
  that separate into classes over training.
- Audio notes: select a section in the waveform player and add a note. Notes
  can be edited and deleted, are kept in the run's `annotations.json`, show
  in reports, and are listed under the clip in HTML exports, where clicking
  one plays its section. `Run.audio_notes` reads them from Python.

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
