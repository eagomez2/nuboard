/** A precision-recall curve as `add_pr_curve` stores it: one value per threshold. */
export interface PRData {
  thresholds: number[];
  precision: number[];
  recall: number[];
  tp: number[];
  fp: number[];
  tn: number[];
  fn: number[];
}

/** One curve to draw: a run's curve in its color. */
export interface PRSeries {
  name: string;
  /** Any CSS color, e.g. `var(--s1)`. */
  color: string;
  data: PRData;
}

/** Plot area inside the SVG, in its own units. */
export const PR_BOX = { left: 40, right: 12, top: 10, bottom: 34 };

/** Area under the curve (average precision by the trapezoid rule over recall). */
export function prArea(d: PRData): number {
  let area = 0;
  for (let i = 1; i < d.recall.length; i++)
    area += Math.abs(d.recall[i - 1] - d.recall[i]) * ((d.precision[i - 1] + d.precision[i]) / 2);
  return area;
}

/** Screen position of point `i` of a curve in an SVG of `width` x `height`. */
export function prPoint(d: PRData, i: number, width: number, height: number): [number, number] {
  const w = width - PR_BOX.left - PR_BOX.right;
  const h = height - PR_BOX.top - PR_BOX.bottom;
  return [PR_BOX.left + d.recall[i] * w, PR_BOX.top + (1 - d.precision[i]) * h];
}

/**
 * The curves as an SVG string: recall on x, precision on y, both 0 to 1, with
 * a light grid. Colors come from CSS variables (`--grid`, `--faint`), so the
 * same markup works in the viewer and in an HTML export.
 */
export function prSvg(series: PRSeries[], width: number, height: number): string {
  const w = width - PR_BOX.left - PR_BOX.right;
  const h = height - PR_BOX.top - PR_BOX.bottom;
  const x = (v: number) => (PR_BOX.left + v * w).toFixed(1);
  const y = (v: number) => (PR_BOX.top + (1 - v) * h).toFixed(1);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  let out = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="10.5" font-family="inherit">`;
  for (const t of ticks) {
    out += `<line x1="${x(0)}" x2="${x(1)}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)" stroke-width="1"/>`;
    out += `<line x1="${x(t)}" x2="${x(t)}" y1="${y(0)}" y2="${y(1)}" stroke="var(--grid)" stroke-width="1"/>`;
    out += `<text x="${PR_BOX.left - 6}" y="${y(t)}" dy="3.5" text-anchor="end" fill="var(--faint)">${t}</text>`;
    out += `<text x="${x(t)}" y="${PR_BOX.top + h + 14}" text-anchor="middle" fill="var(--faint)">${t}</text>`;
  }
  out += `<text x="${PR_BOX.left + w / 2}" y="${height - 4}" text-anchor="middle" fill="var(--faint)">recall</text>`;
  out += `<text transform="translate(10 ${PR_BOX.top + h / 2}) rotate(-90)" text-anchor="middle" fill="var(--faint)">precision</text>`;
  for (const s of series) {
    const d = s.data;
    // Thresholds run from 0 (recall 1) to 1 (recall 0); skip points with no predictions
    const pts: string[] = [];
    for (let i = 0; i < d.recall.length; i++)
      if (d.tp[i] + d.fp[i] > 0) pts.push(`${x(d.recall[i])},${y(d.precision[i])}`);
    out += `<polyline points="${pts.join(' ')}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"><title>${esc(s.name)} · area ${prArea(d).toFixed(3)}</title></polyline>`;
  }
  return out + '</svg>';
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}
