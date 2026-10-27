# File format

This page is the specification of what NuBoard writes to disk. It is updated
with every format change. The current run folder format is **version 1**
(`format_version` in `run.json`); the event log format is **version 1**
(the last two bytes of the log's magic).

Everything a run produces lives in its own folder. A run folder never refers
to anything outside itself, so it can be copied, rsynced, zipped or deleted
on its own. There is no database next to the runs and no lock on the write
path.

## Layout

```text
<root>/                                   any folder; may hold many projects
  <project>/                              may be nested: team/llm/<project>/
    runs/
      <YYYYMMDDTHHMM>-<hash8>/            one run (the folder name is the run id)
        run.json                          metadata, rewritten atomically
        annotations.json                  viewer-owned: star, notes, tags, archived, reviewed, fields
        events.r<rank>.s<session>.log     append-only event log, one per rank and session
        media.r<rank>.pack                images, video, figures and HTML appended back to back
        media.r<rank>.s<session>.pack     the same, for a session of a helper job (see Jobs)
        jobs/<job>.json                   state of a helper job: status, heartbeat, summary, ...
        data.parquet                      compacted scalars (written at finish, optional)
        files/
          requirements.txt                installed packages (pip freeze format)
          git.patch                       `git diff HEAD` at start (only if dirty)
          command.txt                     the command line that started the run
          output.log                      what rank 0 printed (capture_console)
          ...                             files and folders added with run.add_file
    artifacts/<name>/v<N>/
      manifest.json                       hashes, sizes, type, metadata, producing run
      files/...                           the artifact's files (absent for a reference)
    artifacts/.unlinked/<name>/v<N>/      versions unlinked in the viewer, kept as they were
    collections/<name>.json               hand-picked sets of run ids; safe to commit to git
    views/*.json                          saved viewer state; safe to commit to git
    reports/<name>.md                     Markdown reports written in the viewer
    reports/files/*.png, *.svg            chart and plot snapshots embedded in reports
    fields.json                           typed property definitions of the project
~/.cache/nuboard/<hash>.sqlite            disposable run catalog (see below)
```

### Run ids and names

- Run id: `<YYYYMMDDTHHMM>-<hash8>`, e.g. `20261013T0720-755037e9`.
  The timestamp is local time at `init`. `<hash8>` is 8 random lowercase hex
  digits (32 bits), and `init` draws again if the folder already exists, so ids
  are globally unique in practice and never collide on case-insensitive
  filesystems. An explicit `run_id` passed to `init` is used as given.
  Runs created before 0.17 keep their `<YYYYMMDD-HHMM>_<name>_<rand6>` ids;
  readers treat ids as opaque strings.
- The id does not contain the run name. `run_name` (stored as `name` in
  `run.json`) is a free label; no colons appear in any file name, so folders
  work on Windows.
- In a distributed job with a shared id (`TORCHELASTIC_RUN_ID` or
  `SLURM_JOB_ID`), `<hash8>` is the first 8 hex digits of the SHA-1 of that id
  so every rank finds the same folder.

## `run.json`

UTF-8 JSON, written by rank 0 only, always via a temporary file and
`os.replace` (retried on Windows while a reader holds the file). Readers must
ignore keys they do not know.

| Key | Type | Meaning |
| --- | --- | --- |
| `format_version` | int | Run folder format version (1). |
| `run_id` | str | Same as the folder name. |
| `project`, `group` | str | As given to `init`. |
| `name` | str | The `run_name` given to `init` (default `"run"`). |
| `tags` | list[str] | Tags given to `init` (the viewer adds its own in `annotations.json`). |
| `notes` | str | Notes given to `init`. |
| `config` | object | The config passed to `init`. |
| `status` | str | `running`, `finished`, `crashed` or `killed`. |
| `created`, `started`, `ended`, `heartbeat` | float | Unix seconds. `heartbeat` is refreshed every 10 s while running. |
| `sessions` | list | One `{session, started, ended}` per start or resume. |
| `summary` | object | Per scalar: `last`, `step`, `min`, `max`, `count`, `nonfinite`. Non-finite `last` values are the strings `"nan"`, `"inf"`, `"-inf"`. |
| `baselines` | object | Per scalar, set with `add_scalar_baseline`: `{value}`, plus `low` and `high` when given. Absent when none was set. |
| `git` | object/null | `commit`, `branch`, `remote`, `root`, `dirty`. |
| `env` | object | `host`, `platform`, `python`, `executable`, `argv`, `cwd`, `pid`, `gpus`, `cuda_visible_devices`. `gpus` lists the NVIDIA GPUs the process can use (after `CUDA_VISIBLE_DEVICES`), each with `device` (`cuda:i`), `index` (on the machine), `uuid`, `name`, `memory` and `driver`; older runs have only the last three, for every GPU of the machine. |
| `distributed` | object | `world_size`, `shared_id`. |
| `inputs`, `outputs` | list | Artifacts used / logged: `{artifact, version}`, plus `project` and `project_path` for another project's artifact (see [Artifacts](#artifacts)). |
| `fork` | object/null | `{run_id, step}` when created with `fork_from`. |
| `exit` | object/null | `{code, error}`; `error` holds the last 4,000 characters of the traceback. |
| `compacted` | object | Written after compaction: `{bytes: {log file: size}, time}`. |
| `alerts` | list | Written after compaction: the run's [health alerts](../guide/alerts.md), see below. |

A run whose `status` is `running` but whose `heartbeat` is older than 120 s is
shown as **lost** (the process died without running its exit handlers, e.g.
`SIGKILL` or a node failure). Nothing is written to the folder to mark it.

## `annotations.json`

Owned by the viewer, written atomically: `starred` (bool), `archived` (bool),
`reviewed` (bool), `notes` (Markdown str, overrides `run.json` notes in the
viewer), `tags` (list; once tags are edited in the viewer, this list replaces the
`run.json` tags, which keep what was logged), `fields` (object of property
values: string, number, boolean or list-of-string values; lists hold the
values of `tags` properties), `audio_notes` (object keyed by
`<media key>@<step>` of rank 0, each a list of `{id, start, end, text}` notes on
sections of that audio item, times in seconds). Keeping these inside the run
folder means they travel with the run.

### `alerts` in `run.json`

Each alert is an object:

| Key | Type | Meaning |
| --- | --- | --- |
| `kind` | str | `nonfinite`, `spike` or `drop`. |
| `metric`, `rank` | str, int | Where it happened. |
| `step` | int | First step of the problem. |
| `end_step` | int | Last step (`spike` and `drop`). |
| `severity` | str | `error` (non-finite) or `warning`. |
| `message` | str | A readable one-line description. |
| `value`, `baseline` | float | Peak or lowest value, and what it was compared with (`spike`, `drop`). |
| `count` | int | Number of non-finite values (`nonfinite`). |

The list is recomputed whenever the run is compacted. Readers treat a missing
key as "not checked yet", not as "healthy".

## Jobs: `jobs/<job>.json`

A process that joins a run with `init(..., run_id=ID, job="eval")` is a helper
job. It never writes `run.json`: its state goes in `jobs/<job>.json`, with the
same keys `run.json` uses for a process (`status`, `started`, `ended`,
`heartbeat`, `exit`, `sessions`, `summary`, `inputs`, `outputs`,
`baselines`), plus `job`, `heartbeat_interval`, `env` (`host`, `pid`) and
`command`. Its scalars go to event logs numbered after the run's other
sessions, and its media to `media.r<rank>.s<session>.pack`, so two processes
never append to the same file.

Readers merge the jobs into the run: summaries and baselines are added (the
main job's entry wins on a shared name), inputs and outputs are appended with
`job` set, and `jobs` lists each job's `job`, `status`, `started`, `ended`,
`heartbeat`, `error` and `host`. The run's `status` is the main job's.
Readers older than 0.16 ignore `jobs/` and show the main job only.

## Event log: `events.r<rank>.s<session>.log`

One file per rank and session. A session is one process lifetime: a new run
starts session 0; each resume writes the next session number. Files are only
ever appended to.

```text
file   := MAGIC frame*
MAGIC  := "RUNLOG" 0x00 0x01            8 bytes; the last two bytes are the log version
frame  := kind:u8 length:u32 crc32:u32 payload[length]
```

All integers and floats are **little-endian**. `crc32` is zlib's CRC-32 of the
payload. Strings are UTF-8 without a terminator (their length follows from
the frame length).

| Kind | Payload | Meaning |
| --- | --- | --- |
| `N` | `id:u32, name:utf8` | Declares a key id (scalars, text keys and media keys share one id space per file). Always precedes the first use of the id. |
| `S` | `n:u32, metric_id:u32[n], step:i64[n], time:f64[n], value:f64[n]` | A batch of scalars as four columns. |
| `H` | `time:f64` | Heartbeat. |
| `T` | `key_id:u32, step:i64, time:f64, text:utf8` | Text sample. |
| `M` | `key_id:u32, step:i64, time:f64, offset:u64, length:u64, meta:utf8 JSON` | Media index entry: `length` bytes at `offset` in `media.r<rank>.pack`. `meta` holds at least `mime` and `kind` (`image`, `audio`, `video`, `figure`, `html`), plus `caption` for images, audio and video, `sample_rate`, `channels` and `duration` (seconds) for audio when known, and `fps`, `frames`, `width`, `height` and `duration` for video encoded from arrays. |
| `E` | `time:f64, status:utf8` | End of session, written by `finish()`. |

Scalars named `system/...` are the [system samples](../api/init.md#system-scalars)
of `system_metrics`. They are ordinary `S` frames, written by `LOCAL_RANK` 0
of each machine into its own rank's log. Their step is the latest training
step, so several samples can share a step, in time order.

A scalar logged with `low` and `high` writes them as two companion scalars
in the same `S` frame, named `<key>` followed by the unit separator `0x1f`
and `low` or `high` (`"val/loss\x1flow"`). Readers draw them as the band of
`<key>` and leave them out of scalar lists and the `summary` in `run.json`.
Older readers show them as two extra scalars.

Readers skip unknown kinds, so new frame kinds can be added without a version
bump.

**Crash safety.** A reader stops at the first frame that is incomplete or
whose CRC does not match, and remembers the offset of that frame. A torn final
frame (process killed mid-write) is therefore ignored; if the bytes arrive
later (slow network filesystem), the next incremental read picks the frame
up. The writer writes media bytes to the pack and flushes them before the
`M` frame that points at them.

**Values.** `time` is Unix seconds from `time.time()` unless the caller passes
`time=`. `value` is any float64, including NaN and ±Inf.

### Merging sessions and ranks

For one rank, sessions are combined in order. When a later session logs a
scalar, every point of that scalar with `step >= ` the later session's first
step for that scalar is dropped from the earlier sessions: **the later session
wins on overlapping steps** (a resume from a checkpoint replaces what was
logged after the checkpoint). Ranks are never merged; each rank is its own
series and rank 0 is the default.

## Media pack: `media.r<rank>.pack`

Raw bytes of images (PNG/JPEG/GIF/WebP/SVG), audio (WAV/FLAC/MP3/Ogg/MP4/WebM), video (APNG/MP4/WebM/MOV/Ogg/GIF), figures (Plotly JSON,
Vega-Lite JSON, Bokeh JSON, or SVG for matplotlib), PR curves, distributions, tables, point clouds and HTML documents,
appended back to back with no framing. Only `M` frames give them meaning, so
bytes after the last indexed entry (from a crash) are harmless.

| `mime` | Written by |
| --- | --- |
| `image/png`, `image/jpeg`, ... | `add_image` (arrays are PNG-encoded with the standard library) |
| `audio/wav` | `add_audio` with an array (16-bit PCM, standard library `wave`) or a WAV file |
| `audio/flac`, `audio/mpeg`, `audio/ogg`, `audio/mp4`, `audio/webm` | `add_audio` with a file or bytes of that format, stored unchanged |
| `image/apng` | `add_video` with an array: an animated PNG, one `fcTL` per frame with the delay `1/fps`, looping, filtered with the PNG Up filter |
| `video/mp4`, `video/webm`, `video/quicktime`, `video/ogg`, `image/gif` | `add_video` with a file or bytes of that format, stored unchanged |
| `image/svg+xml` | `add_figure` with a matplotlib figure |
| `application/vnd.plotly.v1+json` | `add_figure` with a Plotly figure or a figure dict |
| `application/vnd.vegalite+json` | `add_figure` with an Altair chart or a Vega-Lite dict |
| `application/vnd.bokeh+json` | `add_figure` with a Bokeh figure |
| `application/x-nuboard-pr+json` | `add_pr_curve`: `{thresholds, tp, fp, tn, fn, precision, recall}`, one value per threshold (thresholds evenly spaced from 0 to 1); the frame's `thresholds` and `positives` give the count of thresholds and positives |
| `application/x-nuboard-histogram+json` | `add_histogram`: `{edges, counts, count}` with `edges` one longer than `counts` (every bin includes its left edge, the last also its right edge), and optionally `min`, `max`, `mean`, `std` of the finite values, `outside` (finite values outside the edges) and `nonfinite` (NaN and infinite values, not binned); `count` includes both. The frame's `bins` and `count` give the counts |
| `application/x-nuboard-table+json` | `add_table`: `{columns: [{name, type}], id, rows}`; `type` is `number`, `bool`, `text`, `audio` or `image`, `id` names the column that matches rows across steps, and each row is a list of cells in column order. A media cell is `{"$cell": "<key>#<row>/<column>"}`, the key of a media item logged at the same step with `kind` `cell` (not listed on its own in the viewer). The frame's `rows` and `columns` give the counts |
| `application/x-nuboard-points` | `add_point_cloud`: N x 3 little-endian float32 x, y, z, then N x 3 RGB bytes when the frame's `colors` is true; `points` holds N, and `axes`, when present, the three axis names the viewer starts showing |
| `text/html` | `add_html` (the viewer renders it in a sandboxed iframe) |

## Compacted scalars: `data.parquet`

Written by `finish()` when PyArrow and NumPy are installed, or by
`nuboard compact <dir>`. It is a cache of the logs: the logs stay the source of
truth and are never deleted.

Columns: `metric: string`, `level: int8`, `rank: int32`, `step: int64`,
`time: float64`, `value: float64`, `vmin: float64`, `vmax: float64`.

- Rows are sorted by scalar, zoom level, rank, step, and there is **exactly one
  row group per (scalar, level)**.
- File key/value metadata `row_groups` holds a JSON map
  `{metric: [[row_group_index, rows], ...]}` indexed by level, so reading one
  scalar at one level is one row-group read. `format_version` is also stored.
- Level 0 is the raw data (`vmin`/`vmax` equal `value`). Level *k* averages
  consecutive buckets of 8^*k* points: `step`/`time` of the bucket's first
  point, `value` = mean of finite values, `vmin`/`vmax` = min/max. Levels stop
  when fewer than 512 points would remain.
- Compression is zstd.

**Freshness.** After writing the file, the compactor records the byte size of
every log file in `run.json` → `compacted.bytes`. Readers use `data.parquet`
only when those sizes equal the current sizes; otherwise (for example after a
resume added a session) they read the logs. No coordination is needed.

## Artifacts

`artifacts/<name>/v<N>/` is created by copying into a staging folder and
renaming it into place, so a version is either complete or absent.
`manifest.json`:

```json
{
  "name": "model", "version": 1, "type": "checkpoint",
  "description": "Final checkpoint of the lr=1e-3 seed 1 run",
  "metadata": {"step": 25000},
  "files": [{"path": "model.safetensors", "size": 2048, "sha256": "…"}],
  "created": 1791970000.0, "producer_run": "20261014T0831-f0885bdb",
  "created_by": {"user": "esteban", "host": "gpu-box", "command": "train.py --lr 1e-3"}
}
```

A **reference** version (`reference=True`) has no `files/` folder. Its
manifest records where the files are and a fingerprint of each one:

```json
{
  "name": "fineweb-edu", "version": 2, "type": "dataset",
  "metadata": {"tokens": "12B"},
  "reference": "/data/fineweb-edu/2026-10",
  "root": "/data/fineweb-edu/2026-10",
  "files": [{"path": "train.txt", "size": 3240, "mtime_ns": 1792279527703318788}],
  "created": 1791970000.0, "producer_run": null
}
```

| Key | Meaning |
| --- | --- |
| `reference` | Path of the file or folder that was referenced: absolute, or starting with an environment variable, as in `${NUBOARD_DATA_DIR}/fineweb-edu/2026-10`, which readers expand with their own environment. |
| `root` | The folder `files[].path` is relative to: `reference` for a folder, its parent for a file. |
| `files[].mtime_ns` | Modification time in nanoseconds, for information. Readers compare `size` to detect changes, since copies on other machines have their own times. |
| `files[].sha256` | Present for every copied file, and for referenced files only with `checksum=True`. |
| `producer_run` | `null` for a version added with `nb.add_artifact` or `nuboard artifact add`, outside a run. |
| `description` | Free text saying what the version is; `""` when none was given. Since 0.15. |
| `created_by` | `{user, host, command}`: who created the version, on which machine, with which command line. `user` is `null` when the environment has no user name. Since 0.15. |

Runs record what they used and produced in `run.json` (`inputs`, `outputs`).
An entry for an artifact of another project adds `project`, its name relative
to the root folder, and `project_path`, the path from the run's project
folder to that project's folder, which is what the viewer resolves:

```json
{"artifact": "fineweb-edu", "version": 2, "project": "datasets", "project_path": "../datasets"}
```

A project may hold only artifacts and no runs, such as a `datasets` project.
A run folder copied alone keeps its record of which artifact versions it used
but not the artifact files, and a reference keeps only the path, so the data
has to stay where it was for the version to be usable.

Unlinking a version in the viewer moves its folder, unchanged, to
`artifacts/.unlinked/<name>/v<N>/`; restoring moves it back. Unlinked versions
are not listed by `list_artifacts` or `nuboard artifact ls` and cannot be
loaded with `use_artifact`, but their numbers stay taken: the next version of
`<name>` is numbered after the highest version in either folder. Runs keep
their `inputs` and `outputs` entries, and the viewer shows them as unlinked.

## Collections: `collections/<name>.json`

```json
{"name": "shortlist", "runs": ["20261014T1045-9dc071b6", "…"],
 "description": "Candidates for the 7B run", "created": 1791980000.0, "updated": 1791981000.0}
```

`runs` holds run ids (folder names) of the same project, in the order they
were added. Ids of runs that no longer exist are ignored. Written atomically;
deleting the file deletes the collection.

## Saved views: `views/*.json`

`{"page": "charts", "params": {"q": "...", "metric": "...", ...}}`, where
`params` are the viewer's URL parameters. Safe to commit.

## Reports: `reports/<name>.md`

Plain Markdown, written atomically by the viewer and safe to edit by hand or
commit. The first `# ` heading is the report's title. A logged item is embedded
with an image line whose target is a media reference:

```markdown
![CutMix samples at epoch 100](media:20261016T0815-e8021047/samples/augmented@100)
```

that is `media:<run id>/<key>@<step>`, where the run id is the run's folder
name in the same project and `<key>` may contain `/`. A reference that no
longer resolves is shown as missing.

A chart saved from the Charts page is an ordinary image of a PNG snapshot in
`reports/files/`, whose title describes the chart as a URL query string after
`chart:`:

```markdown
![val/acc](files/findings-1a2b3c4d.png "chart:metric=val%2Facc&runs=<key>,<key>&x=step&smooth=0.6")
```

Keys: `metric`, `runs` (comma-separated run keys), `x`, `group`, `agg`,
`smooth`, `raw=0`, `robust=0`, `log=1`, `zoom=<from>~<to>` and `hide`
(series labels separated by newlines). The viewer draws the chart live from
these and shows the snapshot when it cannot; other Markdown viewers show the
snapshot.

A snapshot from another page (Sweeps, Timeline) has the title
`view:<page>?<viewer URL parameters>`; the viewer shows the image with a
button that reopens that page with those parameters. Timeline snapshots are
SVG files (no scripts, event handlers or links; each bar has a `<title>`), the
others PNG.

The Media page's "All runs on one chart" has the title
`overlay:<ref> <ref> ...`, one `<run id>/<key>@<step>` reference per run
(as after `media:`), separated by spaces. The viewer draws the chart live
from those items and shows the PNG snapshot when none of them is found.

## Property definitions: `fields.json`

```json
{"fields": [
  {"name": "verdict", "type": "choice", "options": ["keep", "drop", "rerun"]},
  {"name": "gpu_hours", "type": "number", "unit": "h"},
  {"name": "paper", "type": "link", "description": "Where the idea comes from"}
]}
```

`type` is one of `text`, `number`, `choice`, `tags`, `bool`, `date` (an ISO
`YYYY-MM-DD` string) or `link`. `options` is used by `choice` and `tags`,
`unit` by `number`; `description` is optional. The values live in each run's
`annotations.json` `fields`; a value without a definition is shown as text.
A value must fit its definition: a number for `number`, `true`/`false` for
`bool`, one of `options` for `choice`, a list drawn from `options` for `tags`
(any value when `options` is empty), `YYYY-MM-DD` for `date` and an `http(s)`
address for `link`. The viewer and `Run.set_field` refuse values that do not.

## The catalog cache

`~/.cache/nuboard/<sha1(root)[:16]>.sqlite` (`%LOCALAPPDATA%\nuboard` on
Windows; override with `NUBOARD_CACHE_DIR`) holds one row per run with the
viewer's record of it and the mtimes it was built from. It lives on local
disk, never next to the runs, so runs can sit on network filesystems. It is
purely a cache: when its schema version (`PRAGMA user_version`) differs it is
dropped and rebuilt. There are no migrations.

## Compatibility rules

- New keys may be added to `run.json`, `annotations.json`, manifests and
  frame `meta` JSON at any time; readers ignore unknown keys.
- New frame kinds may be added; readers skip unknown kinds.
- Changing the meaning or layout of an existing frame, or of the Parquet
  columns, requires bumping the relevant version and keeping a reader for the
  old one.
