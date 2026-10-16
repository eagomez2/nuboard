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
      <YYYYMMDD-HHMM>_<name>_<rand6>/     one run (the folder name is the run id)
        run.json                          metadata, rewritten atomically
        annotations.json                  viewer-owned: star, notes, tags, archived, reviewed, fields
        events.r<rank>.s<session>.log     append-only event log, one per rank and session
        media.r<rank>.pack                images, figures and HTML appended back to back
        data.parquet                      compacted scalars (written at finish, optional)
        files/
          requirements.txt                installed packages (pip freeze format)
          git.patch                       `git diff HEAD` at start (only if dirty)
          command.txt                     the command line that started the run
          ...                             files and folders added with run.add_file
    artifacts/<name>/v<N>/
      manifest.json                       hashes, sizes, type, metadata, producing run
      files/...                           the artifact's files
    collections/<name>.json               hand-picked sets of run ids; safe to commit to git
    views/*.json                          saved viewer state; safe to commit to git
    reports/<name>.md                     Markdown reports written in the viewer
    reports/files/*.png                   chart and plot snapshots embedded in reports
    fields.json                           typed property definitions of the project
~/.cache/nuboard/<hash>.sqlite            disposable run catalog (see below)
```

### Run ids and names

- Run id: `<YYYYMMDD-HHMM>_<name>_<rand6>`, e.g. `20261013-0720_lr3e-4-s1_x5bq2k`.
  The timestamp is local time at `init`. `<rand6>` uses a lowercase alphabet
  without look-alike characters (`abcdefghijkmnpqrstuvwxyz23456789`), so ids
  are globally unique in practice and never collide on case-insensitive
  filesystems.
- `name` is sanitized to `[A-Za-z0-9._-]` (anything else becomes `-`), at most
  64 characters. No colons appear in any file name, so folders work on Windows.
- In a distributed job with a shared id (`TORCHELASTIC_RUN_ID` or
  `SLURM_JOB_ID`), `<rand6>` is derived from a hash of that id so every rank
  finds the same folder.

## `run.json`

UTF-8 JSON, written by rank 0 only, always via a temporary file and
`os.replace` (retried on Windows while a reader holds the file). Readers must
ignore keys they do not know.

| Key | Type | Meaning |
| --- | --- | --- |
| `format_version` | int | Run folder format version (1). |
| `run_id` | str | Same as the folder name. |
| `project`, `name`, `group` | str | As given to `init`. |
| `tags` | list[str] | Tags given to `init` (the viewer adds its own in `annotations.json`). |
| `notes` | str | Notes given to `init`. |
| `config` | object | The config passed to `init`. |
| `status` | str | `running`, `finished`, `crashed` or `killed`. |
| `created`, `started`, `ended`, `heartbeat` | float | Unix seconds. `heartbeat` is refreshed every 10 s while running. |
| `sessions` | list | One `{session, started, ended}` per start or resume. |
| `summary` | object | Per metric: `last`, `step`, `min`, `max`, `count`, `nonfinite`. Non-finite `last` values are the strings `"nan"`, `"inf"`, `"-inf"`. |
| `git` | object/null | `commit`, `branch`, `remote`, `root`, `dirty`. |
| `env` | object | `host`, `platform`, `python`, `executable`, `argv`, `cwd`, `pid`, `gpus`, `cuda_visible_devices`. |
| `distributed` | object | `world_size`, `shared_id`. |
| `inputs`, `outputs` | list | Artifacts used / logged: `{artifact, version}`. |
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
viewer), `tags` (list, merged with `run.json` tags), `fields` (object of custom
fields and property values: string, number, boolean or list-of-string values;
lists hold the values of `tags` properties). Keeping these inside the run
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
| `N` | `id:u32, name:utf8` | Declares a key id (metrics, text keys and media keys share one id space per file). Always precedes the first use of the id. |
| `S` | `n:u32, metric_id:u32[n], step:i64[n], time:f64[n], value:f64[n]` | A batch of scalars as four columns. |
| `H` | `time:f64` | Heartbeat. |
| `T` | `key_id:u32, step:i64, time:f64, text:utf8` | Text sample. |
| `M` | `key_id:u32, step:i64, time:f64, offset:u64, length:u64, meta:utf8 JSON` | Media index entry: `length` bytes at `offset` in `media.r<rank>.pack`. `meta` holds at least `mime` and `kind` (`image`, `audio`, `figure`, `html`), plus `caption` for images and audio, and `sample_rate`, `channels` and `duration` (seconds) for audio when known. |
| `E` | `time:f64, status:utf8` | End of session, written by `finish()`. |

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
metric, every point of that metric with `step >= ` the later session's first
step for that metric is dropped from the earlier sessions: **the later session
wins on overlapping steps** (a resume from a checkpoint replaces what was
logged after the checkpoint). Ranks are never merged; each rank is its own
series and rank 0 is the default.

## Media pack: `media.r<rank>.pack`

Raw bytes of images (PNG/JPEG/GIF/WebP/SVG), audio (WAV/FLAC/MP3/Ogg/MP4/WebM), figures (Plotly JSON,
Vega-Lite JSON, Bokeh JSON, or SVG for matplotlib) and HTML documents,
appended back to back with no framing. Only `M` frames give them meaning, so
bytes after the last indexed entry (from a crash) are harmless.

| `mime` | Written by |
| --- | --- |
| `image/png`, `image/jpeg`, ... | `add_image` (arrays are PNG-encoded with the standard library) |
| `audio/wav` | `add_audio` with an array (16-bit PCM, standard library `wave`) or a WAV file |
| `audio/flac`, `audio/mpeg`, `audio/ogg`, `audio/mp4`, `audio/webm` | `add_audio` with a file or bytes of that format, stored unchanged |
| `image/svg+xml` | `add_figure` with a matplotlib figure |
| `application/vnd.plotly.v1+json` | `add_figure` with a Plotly figure or a figure dict |
| `application/vnd.vegalite+json` | `add_figure` with an Altair chart or a Vega-Lite dict |
| `application/vnd.bokeh+json` | `add_figure` with a Bokeh figure |
| `text/html` | `add_html` (the viewer renders it in a sandboxed iframe) |

## Compacted scalars: `data.parquet`

Written by `finish()` when PyArrow and NumPy are installed, or by
`nuboard compact <dir>`. It is a cache of the logs: the logs stay the source of
truth and are never deleted.

Columns: `metric: string`, `level: int8`, `rank: int32`, `step: int64`,
`time: float64`, `value: float64`, `vmin: float64`, `vmax: float64`.

- Rows are sorted by metric, zoom level, rank, step, and there is **exactly one
  row group per (metric, level)**.
- File key/value metadata `row_groups` holds a JSON map
  `{metric: [[row_group_index, rows], ...]}` indexed by level, so reading one
  metric at one level is one row-group read. `format_version` is also stored.
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
  "name": "fineweb-edu", "version": 2, "type": "dataset",
  "metadata": {"tokens": "12B"},
  "files": [{"path": "train.txt", "size": 3240, "sha256": "…"}],
  "created": 1791970000.0, "producer_run": "20261014-0831_prepare-data_k2x9mf"
}
```

Runs record what they used and produced in `run.json` (`inputs`, `outputs`).
Artifacts are per project, so a run folder copied alone keeps its record of
which artifact versions it used but not the artifact files.

## Collections: `collections/<name>.json`

```json
{"name": "shortlist", "runs": ["20261014-1045_lr1e-3-s1_ei9ssn", "…"],
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
![CutMix samples at epoch 100](media:20261016-0815_cutmix-s0_ab12cd/samples/augmented@100)
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
button that reopens that page with those parameters.

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
