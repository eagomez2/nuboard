# Sweeps

The Sweeps page answers "which settings matter, and which run is best?" for
any set of runs: a project, a query result or your selection.

![Sweeps page with parallel coordinates and per-parameter scatters](../assets/sweeps-light.png){ .nb-shot }

## Objective and parameters

- **Objective**: pick a scalar and whether to use its **best** value (the
  minimum for losses and errors, the maximum otherwise) or its **last** value.
  Lower-is-better scalars are flipped so the best runs are always on top.
- **Parameters**: every config key whose value differs between the runs, plus
  properties. Keys with `seed` in the name start unselected. Click a chip to
  add or remove an axis. The bar inside a chip is the parameter's rank
  correlation with the objective: Spearman's ρ for numbers, the correlation
  ratio on ranks for categories. It is a quick hint, not a causal estimate.

Numeric parameters that span more than a factor of 20 use a log axis.
Text and boolean parameters become ordered categories.

## Parallel coordinates

Each run is one line through every parameter axis to the objective axis.
Lines are colored from orange (worst) to blue (best). Runs without a value for
the objective (still starting, or diverged to NaN) are dashed and end below
the axis.

**Drag along any axis** to keep only the runs inside that range. Filters on
several axes combine, and the scatters, best-runs table and **Plot N runs**
button follow them. Click an axis to clear its filter.

The corner button next to **Plot N runs** shows the chart full screen (Esc
leaves), and the bookmark button adds it to a [report](reports.md) as a
snapshot.

## Scatters and best runs

Below the chart, one scatter per parameter plots the objective against it.
**Grid** sets the plots per row (fit to width, or 1 to 6) and the rows per page
(1 to 6, or all), with a pager when there are more; both are remembered and
kept in the URL (`scols`, `srows`). The bookmark button on each scatter adds
it to a report.
The **Best runs** table lists the top ten runs that pass the filters. Click a
run anywhere on the page to open its details on the Runs page, or press
**Plot N runs** to open them on Charts.

All of the page's state (objective, statistic, parameters) is in the URL,
so a sweep view can be bookmarked or saved like any other view.
