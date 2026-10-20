// Baselines set with `add_scalar_baseline`: a reference value (and optional range) drawn
// as a dashed horizontal line on the scalar's chart.

export interface Baseline {
  value: number;
  low?: number;
  high?: number;
}

export interface BaselineLine extends Baseline {
  /** Labels of the series that share this baseline. */
  labels: string[];
  /** Indices of those series in the chart data. */
  series: number[];
}

/**
 * One line per distinct baseline of the shown series. Baselines that match to 6 significant
 * digits share a line, so recomputing the same input does not split it.
 */
export function baselineLines(
  series: { label: string; baseline?: Baseline | null }[],
  hidden: Set<string> = new Set(),
): BaselineLine[] {
  const lines = new Map<string, BaselineLine>();
  series.forEach((s, i) => {
    const b = s.baseline;
    if (!b || !Number.isFinite(b.value) || hidden.has(s.label)) return;
    const key = [b.value, b.low, b.high].map((v) => (v === undefined ? '' : v.toPrecision(6))).join('|');
    const line = lines.get(key);
    if (line) {
      line.labels.push(s.label);
      line.series.push(i);
    } else lines.set(key, { ...b, labels: [s.label], series: [i] });
  });
  return [...lines.values()];
}

/** Smallest and largest value the lines cover (bounds included); null when there are none. */
export function baselineExtent(lines: Baseline[], positiveOnly = false): [number, number] | null {
  const vals = lines
    .flatMap((l) => [l.value, l.low, l.high])
    .filter((v): v is number => v !== undefined && Number.isFinite(v) && (!positiveOnly || v > 0));
  return vals.length ? [Math.min(...vals), Math.max(...vals)] : null;
}
