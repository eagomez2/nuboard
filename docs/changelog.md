# Changelog

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
