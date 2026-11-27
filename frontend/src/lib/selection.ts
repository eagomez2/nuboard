// Helpers of the Shortlist page: rows are a run at a step, scored on a few scalars (see
// `nuboard/selection.py`, which finds the shortlist). These stay free of Svelte so they can be tested.

export type Dir = 'min' | 'max';

/** The id of a row in the URL: the run's catalog key and the step. */
export const rowId = (key: string, step: number) => `${key}@${step}`;

/** The run key and step of a row id; null when it is not one. */
export function parseRowId(id: string): { key: string; step: number } | null {
  const at = id.lastIndexOf('@');
  if (at <= 0) return null;
  const step = Number(id.slice(at + 1));
  return Number.isInteger(step) ? { key: id.slice(0, at), step } : null;
}

/** True when `a` is better than `b` in direction `dir`. */
export const better = (a: number, b: number, dir: Dir) => (dir === 'min' ? a < b : a > b);

/** The index of the best value of each column, among `rows` (each a list of values). */
export function bestIndex(rows: number[][], dirs: Dir[]): number[] {
  return dirs.map((dir, k) => {
    let best = -1;
    rows.forEach((r, i) => {
      if (best < 0 || better(r[k], rows[best][k], dir)) best = i;
    });
    return best;
  });
}

/** 1 for the best of `values` in direction `dir`, 2 for the next, and so on (ties share a rank). */
export const rankOf = (values: number[], v: number, dir: Dir) => 1 + values.filter((x) => better(x, v, dir)).length;

/** Round tick values covering `[lo, hi]`, about `n` of them. */
export function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi <= lo) return [lo];
  const raw = (hi - lo) / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

/** The range of `values` with a margin on each side, so points never sit on the plot's edge. */
export function padded(values: number[], margin = 0.06): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (hi === lo) {
    const d = Math.abs(lo) * 0.05 || 1;
    lo -= d;
    hi += d;
  }
  const pad = (hi - lo) * margin;
  return [lo - pad, hi + pad];
}

/**
 * The staircase through the points no other point beats on both axes (`dx`, `dy` say which
 * way is better on each), as an ordered list from left to right. Drawn as a dashed line: the
 * trade-off edge on the two axes shown.
 */
export function edge2d(points: [number, number][], dx: Dir, dy: Dir): [number, number][] {
  const sx = dx === 'min' ? 1 : -1;
  const sy = dy === 'min' ? 1 : -1;
  const sorted = [...points].sort((a, b) => sx * (a[0] - b[0]) || sy * (a[1] - b[1]));
  const out: [number, number][] = [];
  let bestY = Infinity;
  for (const p of sorted) {
    if (sy * p[1] < bestY) {
      out.push(p);
      bestY = sy * p[1];
    }
  }
  return out.sort((a, b) => a[0] - b[0]);
}
