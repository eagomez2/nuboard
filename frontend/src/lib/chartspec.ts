// A chart saved into a report: what the Charts page showed, written as a URL query string
// in the title of the snapshot image: `![caption](files/x.png "chart:metric=loss&runs=...")`.

export interface ChartSpec {
  metric: string;
  runs: string[];
  x: string;
  group: string | null;
  agg: string;
  smooth: number;
  raw: boolean;
  robust: boolean;
  log: boolean;
  /** Draw baselines (absent in older specs: on). */
  base: boolean;
  zoom: [number, number] | null;
  hidden: string[];
}

export function encodeSpec(s: ChartSpec): string {
  const p = new URLSearchParams({ metric: s.metric, runs: s.runs.join(','), x: s.x, smooth: String(s.smooth) });
  if (s.group) p.set('group', s.group);
  if (s.group) p.set('agg', s.agg);
  if (!s.raw) p.set('raw', '0');
  if (!s.robust) p.set('robust', '0');
  if (s.log) p.set('log', '1');
  if (!s.base) p.set('base', '0');
  if (s.zoom) p.set('zoom', `${s.zoom[0]}~${s.zoom[1]}`);
  if (s.hidden.length) p.set('hide', s.hidden.join('\n'));
  return p.toString();
}

export function decodeSpec(text: string): ChartSpec | null {
  const p = new URLSearchParams(text);
  const metric = p.get('metric');
  const runs = (p.get('runs') ?? '').split(',').filter(Boolean);
  if (!metric || !runs.length) return null;
  const z = (p.get('zoom') ?? '').split('~').map(Number);
  return {
    metric,
    runs,
    x: p.get('x') || 'step',
    group: p.get('group') || null,
    agg: p.get('agg') || 'std',
    smooth: Number(p.get('smooth') ?? 0) || 0,
    raw: p.get('raw') !== '0',
    robust: p.get('robust') !== '0',
    log: p.get('log') === '1',
    base: p.get('base') !== '0',
    zoom: z.length === 2 && z.every(Number.isFinite) ? [z[0], z[1]] : null,
    hidden: (p.get('hide') ?? '').split('\n').filter(Boolean),
  };
}

/** The Charts page's URL parameters that reopen a saved chart. */
export function chartsParams(s: ChartSpec): Record<string, string | null> {
  return {
    sel: s.runs.join(','),
    metric: s.metric,
    x: s.x === 'step' ? null : s.x,
    group: s.group ?? 'none',
    agg: s.group ? s.agg : null,
    smooth: String(s.smooth),
    raw: s.raw ? null : '0',
    robust: s.robust ? null : '0',
    log: s.log ? '1' : null,
    base: s.base ? null : '0',
    zoom: s.zoom ? `${s.zoom[0]}~${s.zoom[1]}` : null,
  };
}
