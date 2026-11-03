import { timeZone, type RunZoneInfo } from './timezone.svelte';
import type { ZoneKit } from './tz';

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

/** A duration in seconds with the precision timers need: `850 ms`, `12.3 s`, `1m 22s`, `1h 04m`. */
export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  const a = Math.abs(s);
  if (a === 0) return '0 s';
  if (a < 0.001) return `${+(s * 1e6).toPrecision(2)} µs`;
  if (a < 1) return `${+(s * 1000).toPrecision(a < 0.01 ? 2 : 3)} ms`;
  if (a < 60) return `${+s.toPrecision(3)} s`;
  const r = Math.round(s);
  if (r < 3600) return `${Math.floor(r / 60)}m ${String(r % 60).padStart(2, '0')}s`;
  const m = Math.round(s / 60);
  if (m < 1440) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
  const h = Math.round(s / 3600);
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** A count in short form: `980`, `49.5k`, `1.04M`, `3.2B`. */
export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  const a = Math.abs(n);
  if (a < 1e4) return Math.round(n).toLocaleString('en');
  if (a < 1e6) return `${+(n / 1e3).toPrecision(3)}k`;
  if (a < 1e9) return `${+(n / 1e6).toPrecision(3)}M`;
  return `${+(n / 1e9).toPrecision(3)}B`;
}

export function fmtAgo(t: number | null | undefined, now = Date.now() / 1000, run?: RunZoneInfo | null): string {
  if (!t) return '—';
  const d = now - t;
  if (d < 45) return 'just now';
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  if (d < 86400 * 30) return `${Math.round(d / 86400)} d ago`;
  return timeZone.kitAt(t, run).kit.format(t, { year: 'numeric', month: 'numeric', day: 'numeric' });
}

// Wall-clock times. Every one the viewer shows goes through these, so all views
// agree; lint forbids formatting a Date anywhere else. A time that belongs to a run
// passes the run: by default ("machine time") it is written on the clock of the
// machine that recorded it. Times shared by several runs (an axis, a read-out) use
// `timeZone.shared(runs)` and `fmtTimeIn`.

/** The zone's short name at `t`, marked when machine time was asked for but is not known. */
function zoneName(kit: ZoneKit, known: boolean, t: number): string {
  return known ? kit.abbr(t) : `${kit.abbr(t)} (local)`;
}

/** A date and time to the minute: `Oct 13, 2026, 07:20`. */
export function fmtDate(t: number | null | undefined, run?: RunZoneInfo | null): string {
  if (!t) return '—';
  return timeZone.kitAt(t, run).kit.format(t, { dateStyle: 'medium', timeStyle: 'short' });
}

/** A date and time to the second, with the zone: `Oct 13, 2026, 07:20:05 GMT-3`. For hover read-outs. */
export function fmtDateTime(t: number | null | undefined, run?: RunZoneInfo | null): string {
  if (!t) return '—';
  const { kit, known } = timeZone.kitAt(t, run);
  return `${kit.format(t, { dateStyle: 'medium', timeStyle: 'medium' })} ${zoneName(kit, known, t)}`;
}

/** A date and time to the second in a given zone, with its name, such as an axis read-out's. */
export function fmtTimeIn(kit: ZoneKit, t: number, clockOnly = false): string {
  return `${kit.format(t, clockOnly ? { timeStyle: 'medium' } : { dateStyle: 'medium', timeStyle: 'medium' })} ${kit.abbr(t)}`;
}

/** The zone a run's time `t` is written in, such as `UTC−03:00` or `GMT-3 (local)`. */
export function fmtZone(t: number, run?: RunZoneInfo | null): string {
  const { kit, known } = timeZone.kitAt(t, run);
  return zoneName(kit, known, t);
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

/** The text with its first letter capitalized, for showing a value such as a run status as a label. */
export const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);
