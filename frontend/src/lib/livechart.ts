/** Live updates of a chart: refetch only the runs that changed, then merge them in. */
import type { ChartData, Series } from './api';

/**
 * The runs of `runs` that a live update has to refetch, or null to refetch the
 * whole chart (no previous data, grouped series, or an unknown set of changes).
 * An empty list means nothing this chart shows has changed.
 */
export function runsToRefetch(
  runs: string[],
  changed: string[] | null,
  grouped: boolean,
  hasData: boolean,
): string[] | null {
  if (!changed || grouped || !hasData) return null;
  const set = new Set(changed);
  return runs.filter((k) => set.has(k));
}

/**
 * Replace the series of the refetched runs `part` in `old` with those of `fresh`, in `runs` order.
 *
 * A run keeps its label: the server tells runs of the same name apart by a
 * suffix only when both are in one request. Returns null when a new series
 * would share a label with another, so the caller refetches the whole chart.
 */
export function mergeSeries(old: ChartData, fresh: ChartData, part: string[], runs: string[]): ChartData | null {
  const redone = new Set(part);
  const order = new Map(runs.map((k, i) => [k, i]));
  const rank = (s: Series) => order.get(s.runs[0]) ?? runs.length;
  const labels = new Map(old.series.map((s) => [s.runs[0], s.label]));
  const kept = old.series.filter((s) => !s.runs.some((k) => redone.has(k)));
  const added = fresh.series.map((s) => ({ ...s, label: labels.get(s.runs[0]) ?? s.label }));
  const all = [...kept, ...added];
  if (new Set(all.map((s) => s.label)).size < all.length) return null;
  return { ...old, series: all.sort((a, b) => rank(a) - rank(b)) };
}
