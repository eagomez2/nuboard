/** A distribution as `add_histogram` stores it. */
export interface HistData {
  /** Bin edges, one more than `counts`. */
  edges: number[];
  counts: number[];
  /** Every value counted, including those outside the edges. */
  count: number;
  min?: number;
  max?: number;
  mean?: number;
  std?: number;
  /** Finite values outside the edges. */
  outside?: number;
  /** NaN and infinite values, not binned. */
  nonfinite?: number;
}

/** One distribution to draw. */
export interface HistSeries {
  name: string;
  /** Any CSS color, e.g. `var(--s1)`. */
  color: string;
  data: HistData;
  /** Filled bars; otherwise an outline. */
  fill?: boolean;
  dashed?: boolean;
}

/** Plot area inside the SVG, in its own units. */
export const HIST_BOX = { left: 46, right: 12, top: 10, bottom: 34 };

/** The quantiles drawn over steps, as TensorBoard's distributions do. */
export const QUANTILES = [0, 0.07, 0.16, 0.5, 0.84, 0.93, 1];

const cache = new Map<string, Promise<HistData | null>>();

/** Fetch (once) the distribution at a media URL. */
export function loadHist(url: string): Promise<HistData | null> {
  if (!cache.has(url))
    cache.set(
      url,
      fetch(url)
        .then((r) => (r.ok ? (r.json() as Promise<HistData>) : null))
        .catch(() => null),
    );
  return cache.get(url)!;
}

/** Density of each bin: its share of the binned values per unit of x. */
export function densities(d: HistData): number[] {
  const total = d.counts.reduce((a, b) => a + b, 0) || 1;
  return d.counts.map((c, i) => c / total / (d.edges[i + 1] - d.edges[i] || 1));
}

/** The value below which a fraction `q` of the binned values lie (linear within a bin). */
export function quantile(d: HistData, q: number): number {
  const total = d.counts.reduce((a, b) => a + b, 0);
  if (!total) return NaN;
  if (q <= 0) return d.min ?? d.edges[0];
  if (q >= 1) return d.max ?? d.edges[d.edges.length - 1];
  let below = 0;
  for (let i = 0; i < d.counts.length; i++) {
    const c = d.counts[i];
    if (below + c >= q * total && c > 0) return d.edges[i] + ((q * total - below) / c) * (d.edges[i + 1] - d.edges[i]);
    below += c;
  }
  return d.edges[d.edges.length - 1];
}

/** About `n` round values from `a` to `b`. */
export function niceTicks(a: number, b: number, n: number): number[] {
  const span = b - a;
  if (!(span > 0) || !Number.isFinite(span)) return [a];
  const raw = span / n;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  const step = p * (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10);
  const out: number[] = [];
  for (let v = Math.ceil(a / step - 1e-9) * step; v <= b + step * 1e-9; v += step)
    out.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return out;
}

/** A number short enough for an axis label. */
export function fmtTick(v: number): string {
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(1).replace('e+', 'e');
  return String(Number(v.toPrecision(4)));
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

function frame(width: number, height: number, xs: number[], ys: number[], xLabel: string, yLabel: string) {
  const w = width - HIST_BOX.left - HIST_BOX.right;
  const h = height - HIST_BOX.top - HIST_BOX.bottom;
  let out = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="10.5" font-family="inherit">`;
  const [x0, x1] = [xs[0], xs[xs.length - 1]];
  const [y0, y1] = [ys[0], ys[ys.length - 1]];
  const x = (v: number) => HIST_BOX.left + ((v - x0) / (x1 - x0 || 1)) * w;
  const y = (v: number) => HIST_BOX.top + (1 - (v - y0) / (y1 - y0 || 1)) * h;
  for (const t of niceTicks(x0, x1, Math.max(2, Math.round(w / 90)))) {
    out += `<line x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="${HIST_BOX.top}" y2="${HIST_BOX.top + h}" stroke="var(--grid)"/>`;
    out += `<text x="${x(t).toFixed(1)}" y="${HIST_BOX.top + h + 14}" text-anchor="middle" fill="var(--faint)">${fmtTick(t)}</text>`;
  }
  for (const t of niceTicks(y0, y1, Math.max(2, Math.round(h / 50)))) {
    out += `<line x1="${HIST_BOX.left}" x2="${HIST_BOX.left + w}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="var(--grid)"/>`;
    out += `<text x="${HIST_BOX.left - 6}" y="${y(t).toFixed(1)}" dy="3.5" text-anchor="end" fill="var(--faint)">${fmtTick(t)}</text>`;
  }
  out += `<text x="${HIST_BOX.left + w / 2}" y="${height - 4}" text-anchor="middle" fill="var(--faint)">${esc(xLabel)}</text>`;
  out += `<text transform="translate(10 ${HIST_BOX.top + h / 2}) rotate(-90)" text-anchor="middle" fill="var(--faint)">${esc(yLabel)}</text>`;
  return { out, x, y };
}

/** The x range and top density shared by a set of distributions. */
export function histScale(series: HistSeries[]): { lo: number; hi: number; top: number } {
  let lo = Infinity;
  let hi = -Infinity;
  let top = 0;
  for (const s of series) {
    lo = Math.min(lo, s.data.edges[0]);
    hi = Math.max(hi, s.data.edges[s.data.edges.length - 1]);
    top = Math.max(top, ...densities(s.data));
  }
  return { lo, hi, top: top || 1 };
}

/**
 * Distributions as an SVG string: value on x, density on y, so runs and steps
 * with different ranges or bin counts compare fairly. Filled series are drawn
 * as bars, the others as outlines. Colors come from CSS variables, so the same
 * markup works in the viewer and in an HTML export.
 */
export function histSvg(series: HistSeries[], width: number, height: number): string {
  if (!series.length) return '';
  const { lo, hi, top } = histScale(series);
  const ys = niceTicks(0, top * 1.05, 4);
  const yMax = Math.max(top * 1.05, ys[ys.length - 1]);
  const { out: head, x, y } = frame(width, height, [lo, hi], [0, yMax], 'value', 'density');
  let out = head;
  for (const s of [...series].sort((a, b) => Number(!!b.fill) - Number(!!a.fill))) {
    const d = s.data;
    const dens = densities(d);
    let path = `M${x(d.edges[0]).toFixed(1)},${y(0).toFixed(1)}`;
    dens.forEach((v, i) => {
      path += `V${y(v).toFixed(1)}H${x(d.edges[i + 1]).toFixed(1)}`;
    });
    path += `V${y(0).toFixed(1)}`;
    const title = `<title>${esc(s.name)}${d.mean != null ? ` · mean ${fmtTick(d.mean)}` : ''}${d.std != null ? ` · std ${fmtTick(d.std)}` : ''}</title>`;
    out += s.fill
      ? `<path d="${path}Z" fill="${s.color}" fill-opacity="0.32" stroke="${s.color}" stroke-width="1.5" stroke-linejoin="round">${title}</path>`
      : `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="${s.dashed ? 1.5 : 2}"${s.dashed ? ' stroke-dasharray="4 3"' : ''} stroke-linejoin="round">${title}</path>`;
  }
  return out + '</svg>';
}

/** One step of a distribution over steps: its quantiles (see `QUANTILES`). */
export interface StepQuantiles {
  step: number;
  q: number[];
}

/**
 * How a distribution moves over steps, as TensorBoard's distributions: bands
 * between the 0/100, 7/93 and 16/84 percentiles, darker toward the median
 * line, with an optional line at the chosen `marker` step.
 */
export function bandsSvg(rows: StepQuantiles[], color: string, width: number, height: number, marker?: number): string {
  if (!rows.length) return '';
  const steps = rows.map((r) => r.step);
  const vals = rows.flatMap((r) => r.q).filter(Number.isFinite);
  let s0 = Math.min(...steps);
  let s1 = Math.max(...steps);
  if (s0 === s1) [s0, s1] = [s0 - 1, s1 + 1];
  let v0 = Math.min(...vals);
  let v1 = Math.max(...vals);
  if (v0 === v1) [v0, v1] = [v0 - 0.5, v1 + 0.5];
  const pad = (v1 - v0) * 0.04;
  const { out: head, x, y } = frame(width, height, [s0, s1], [v0 - pad, v1 + pad], 'step', 'value');
  let out = head;
  const band = (a: number, b: number, opacity: number) => {
    const up = rows.map((r) => `${x(r.step).toFixed(1)},${y(r.q[b]).toFixed(1)}`);
    const down = [...rows].reverse().map((r) => `${x(r.step).toFixed(1)},${y(r.q[a]).toFixed(1)}`);
    if (rows.length === 1) {
      const cx = x(rows[0].step);
      return `<rect x="${(cx - 3).toFixed(1)}" y="${y(rows[0].q[b]).toFixed(1)}" width="6" height="${(y(rows[0].q[a]) - y(rows[0].q[b])).toFixed(1)}" fill="${color}" fill-opacity="${opacity}"/>`;
    }
    return `<polygon points="${[...up, ...down].join(' ')}" fill="${color}" fill-opacity="${opacity}"/>`;
  };
  out += band(0, 6, 0.14) + band(1, 5, 0.2) + band(2, 4, 0.28);
  out += `<polyline points="${rows.map((r) => `${x(r.step).toFixed(1)},${y(r.q[3]).toFixed(1)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  if (marker !== undefined && marker >= s0 && marker <= s1)
    out += `<line x1="${x(marker).toFixed(1)}" x2="${x(marker).toFixed(1)}" y1="${HIST_BOX.top}" y2="${height - HIST_BOX.bottom}" stroke="var(--faint)" stroke-dasharray="3 3"/>`;
  return out + '</svg>';
}
