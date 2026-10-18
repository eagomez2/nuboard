export function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return '—';
  if (Number.isNaN(v)) return 'NaN';
  if (!Number.isFinite(v)) return v > 0 ? '∞' : '−∞';
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1e9) return (v / 1e9).toPrecision(3) + 'B';
  if (a >= 1e6) return (v / 1e6).toPrecision(3) + 'M';
  if (a >= 1e4) return (v / 1e3).toPrecision(3) + 'k';
  if (a < 1e-3) return v.toExponential(1).replace('e-', 'e-').replace('.0e', 'e');
  return Number(v.toPrecision(digits)).toString();
}

export function fmtAxis(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1e9) return +(v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return +(v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return +(v / 1e3).toFixed(1) + 'k';
  if (a < 1e-2) return v.toExponential(1);
  return +v.toPrecision(3) + '';
}

export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.round((s % 86400) / 3600)}h`;
}

export function fmtAgo(t: number | null | undefined, now = Date.now() / 1000): string {
  if (!t) return '—';
  const d = now - t;
  if (d < 45) return 'just now';
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  if (d < 86400 * 30) return `${Math.round(d / 86400)} d ago`;
  return new Date(t * 1000).toLocaleDateString();
}

export function fmtDate(t: number | null | undefined): string {
  if (!t) return '—';
  return new Date(t * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** A byte count with a binary unit: 512 B, 1.5 KB, 240 MB. */
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return fmtNum(v, 6);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

/** Lower is better for losses/errors; higher for everything else. */
export function lowerIsBetter(metric: string): boolean {
  return /loss|error|err\b|perplexity|ppl|mse|mae|rmse|wer|cer|nll|regret|time|latency/i.test(metric);
}

/** The metric to show first: a training loss if there is one. */
export function defaultMetric(metrics: string[]): string {
  const rank = (m: string) =>
    m === 'loss' ? 0 : m === 'train/loss' ? 1 : /(^|\/)loss$/.test(m) ? 2 : /loss/.test(m) ? 3 : 4;
  return [...metrics].sort((a, b) => rank(a) - rank(b))[0] ?? '';
}
