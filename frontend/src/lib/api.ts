import { tableFromIPC } from 'apache-arrow';

export type Num = number | 'nan' | 'inf' | '-inf' | null;

export interface MetricSummary {
  last: Num;
  step: number;
  min: number | null;
  max: number | null;
  count: number;
  nonfinite: number;
}

export interface Alert {
  kind: 'nonfinite' | 'spike' | 'drop' | string;
  metric: string;
  rank: number;
  step: number;
  end_step?: number;
  severity: 'error' | 'warning' | string;
  message: string;
  value?: number;
  baseline?: number;
  count?: number;
}

export type FieldValue = string | number | boolean | string[];

export type FieldType = 'text' | 'number' | 'choice' | 'tags' | 'bool' | 'date' | 'link';

/** A typed property, defined per project in `<project>/fields.json`. */
export interface FieldDef {
  name: string;
  type: FieldType;
  options?: string[];
  unit?: string;
  description?: string;
}

export interface ReportInfo {
  project: string;
  name: string;
  title: string;
  updated: number;
}

export interface Collection {
  name: string;
  project: string;
  runs: string[];
  description?: string;
  created?: number;
  updated?: number;
}

export interface ArtifactFile {
  path: string;
  size: number;
  sha256?: string;
  mtime_ns?: number;
}

export interface ArtifactVersion {
  project: string;
  name: string;
  version: number;
  size: number;
  producers: string[];
  consumers: string[];
  manifest: {
    type?: string | null;
    metadata?: Record<string, unknown>;
    files?: ArtifactFile[];
    created?: number;
    producer_run?: string | null;
    reference?: string;
    root?: string;
    description?: string;
    created_by?: { user?: string | null; host?: string | null; command?: string | null };
  };
}

export interface RunBrief {
  key: string;
  id: string;
  project: string;
  path: string;
  name: string;
  status: 'running' | 'finished' | 'crashed' | 'killed' | 'lost' | string;
  created: number | null;
  started: number | null;
  ended: number | null;
  heartbeat: number | null;
  duration: number | null;
  config: Record<string, unknown>;
  tags: string[];
  notes: string;
  starred: boolean;
  archived: boolean;
  reviewed: boolean;
  group: string | null;
  summary: Record<string, MetricSummary>;
  metric_count: number;
  nonfinite: string[];
  commit: string | null;
  dirty: boolean;
  host: string | null;
  world_size: number;
  fork: { run_id: string; step: number } | null;
  fields: Record<string, FieldValue>;
  collections: string[];
  alerts: Alert[];
}

export interface QueryInfo {
  group_by: string | null;
  agg: string;
  order_by: string | null;
  descending: boolean;
  limit: number | null;
}

export interface RunsResponse {
  runs: RunBrief[];
  total: number;
  query: QueryInfo;
  error: string | null;
  metrics: string[];
  version: number;
  elapsed_ms: number;
}

export interface ProjectInfo {
  name: string;
  runs: number;
  views: string[];
}

export interface Info {
  name: string;
  version: string;
  root: string;
  root_display: string;
  projects: ProjectInfo[];
}

export interface RunDetail {
  run: RunBrief & { error: string | null; inputs: unknown[]; outputs: unknown[] };
  meta: Record<string, any>;
  files: string[];
  ranks: number[];
  media: Record<string, { kind: string; count: number }>;
}

export interface MediaItem {
  key: string;
  step: number;
  time: number;
  index?: number;
  kind: string;
  mime: string;
  caption?: string | null;
  sample_rate?: number;
  channels?: number;
  duration?: number | null;
  /** Point clouds: the number of points and whether they carry colors. */
  points?: number;
  colors?: boolean;
  /** Point clouds: axis names, when logged with `axes`. */
  axes?: string[];
  /** Distributions: the number of bins and of values. */
  bins?: number;
  count?: number;
  text?: string;
  /** Notes on sections of an audio item, added in the viewer. */
  notes?: AudioNote[];
}

export interface AudioNote {
  id: string;
  start: number;
  end: number;
  text: string;
}

export interface SeriesMeta {
  label: string;
  runs: string[];
  group: unknown;
  n?: number;
  last: number | null;
  nonfinite: boolean;
}

export interface Series extends SeriesMeta {
  x: Float64Array;
  y: Float64Array;
  lo: Float64Array;
  hi: Float64Array;
}

export interface ChartData {
  metric: string;
  xKind: string;
  series: Series[];
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | null | undefined>) =>
  new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '') as [string, string][],
  ).toString();

export const api = {
  info: () => json<Info>('/api/info'),
  runs: (q: string, project?: string | null, metrics?: string[] | null) =>
    json<RunsResponse>(`/api/runs?${qs({ q, project, metrics: metrics?.join(',') })}`),
  run: (key: string) => json<RunDetail>(`/api/runs/${encodeURIComponent(key)}`),
  /** A file of the run's `files/` folder as text: its first 2 MB, or its last with `tail`. */
  file: async (key: string, path: string, tail = false) => {
    const res = await fetch(`/api/runs/${encodeURIComponent(key)}/files/${path}${tail ? '?tail=1' : ''}`);
    return res.ok ? res.text() : null;
  },
  annotate: (
    keys: string[],
    patch: Partial<Pick<RunBrief, 'starred' | 'archived' | 'reviewed' | 'notes' | 'tags'>> & {
      fields?: Record<string, FieldValue | null>;
    },
  ) =>
    json<{ updated: string[] }>('/api/runs/annotate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys, patch }),
    }),
  metrics: (keys: string[]) =>
    json<{ metrics: { name: string; runs: number }[] }>(`/api/metrics?runs=${keys.map(encodeURIComponent).join(',')}`),
  setAudioNotes: (key: string, item: string, notes: AudioNote[]) =>
    json<{ notes: AudioNote[] }>(`/api/runs/${encodeURIComponent(key)}/audio-notes`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item, notes }),
    }),
  media: (key: string) => json<{ items: MediaItem[] }>(`/api/runs/${encodeURIComponent(key)}/media`),
  alerts: (keys: string[]) =>
    json<{ alerts: Record<string, Alert[]> }>(`/api/alerts?runs=${keys.map(encodeURIComponent).join(',')}`),
  artifacts: (project?: string | null) => json<{ artifacts: ArtifactVersion[] }>(`/api/artifacts?${qs({ project })}`),
  collections: (project?: string | null) => json<{ collections: Collection[] }>(`/api/collections?${qs({ project })}`),
  saveCollection: (body: { name: string; add?: string[]; remove?: string[]; project?: string; delete?: boolean }) =>
    json<{ collections: Collection[] }>('/api/collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  mediaUrl: (key: string, index: number) => `/api/runs/${encodeURIComponent(key)}/media/${index}`,
  best: (keys: string[], metric: string, mode: 'min' | 'max') =>
    json<{ best: Record<string, { step: number; value: number }> }>(
      `/api/best?${qs({ runs: keys.join(','), metric, mode })}`,
    ),
  mediaRef: (project: string, ref: string) =>
    json<{ run: string; run_name: string; item: MediaItem }>(`/api/media/ref?${qs({ project, ref })}`),
  reports: (project?: string | null) => json<{ reports: ReportInfo[] }>(`/api/reports?${qs({ project })}`),
  report: (project: string, name: string) =>
    json<{ project: string; name: string; text: string }>(
      `/api/reports/${project.split('/').map(encodeURIComponent).join('/')}/${encodeURIComponent(name)}`,
    ),
  reportExportUrl: (project: string, name: string) =>
    `/api/reports/${project.split('/').map(encodeURIComponent).join('/')}/${encodeURIComponent(name)}/export`,
  saveReport: (body: {
    project: string;
    name: string;
    text?: string;
    append?: string;
    rename?: string;
    delete?: boolean;
  }) =>
    json<{ saved?: string; deleted?: string; error?: string }>('/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  saveSnapshot: (project: string, report: string, png: string) =>
    json<{ path?: string; error?: string }>('/api/reports/snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, report, png }),
    }),
  /** URL of a report-local file such as `files/chart.png`. */
  reportFileUrl: (project: string, path: string) =>
    `/api/reports/${project.split('/').map(encodeURIComponent).join('/')}/${path}`,
  fields: (project: string) => json<{ fields: FieldDef[] }>(`/api/fields?${qs({ project })}`),
  saveFields: (project: string, fields: FieldDef[]) =>
    json<{ fields: FieldDef[] }>('/api/fields', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, fields }),
    }),

  async chart(p: {
    runs: string[];
    metric: string;
    x: string;
    group?: string | null;
    agg?: string;
    points: number;
    xmin?: number | null;
    xmax?: number | null;
    signal?: AbortSignal;
  }): Promise<ChartData> {
    const url = `/api/scalars?${qs({
      runs: p.runs.join(','),
      metric: p.metric,
      x: p.x,
      group: p.group,
      agg: p.agg,
      points: p.points,
      xmin: p.xmin,
      xmax: p.xmax,
    })}`;
    const res = await fetch(url, { signal: p.signal });
    if (!res.ok) throw new Error(await res.text());
    return decodeChart(new Uint8Array(await res.arrayBuffer()));
  },
};

/** Decode the Arrow IPC stream from /api/scalars into per-series typed arrays. */
export function decodeChart(bytes: Uint8Array): ChartData {
  const table = tableFromIPC(bytes);
  const meta = table.schema.metadata;
  const metas: SeriesMeta[] = JSON.parse(meta.get('series') ?? '[]');
  const col = (name: string) => table.getChild(name)?.toArray() as Float64Array;
  const sid = (table.getChild('series')?.toArray() as Int32Array) ?? new Int32Array();
  const [x, y, lo, hi] = [col('x'), col('y'), col('lo'), col('hi')];
  const series: Series[] = metas.map((m) => ({
    ...m,
    x: new Float64Array(),
    y: new Float64Array(),
    lo: new Float64Array(),
    hi: new Float64Array(),
  }));
  let start = 0;
  for (let i = 1; i <= sid.length; i++) {
    if (i === sid.length || sid[i] !== sid[start]) {
      const s = series[sid[start]];
      if (s) {
        s.x = x.slice(start, i);
        s.y = y.slice(start, i);
        s.lo = lo.slice(start, i);
        s.hi = hi.slice(start, i);
      }
      start = i;
    }
  }
  return { metric: meta.get('metric') ?? '', xKind: meta.get('x') ?? 'step', series };
}

export function num(v: Num | undefined): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return v;
  return v === 'nan' ? NaN : v === 'inf' ? Infinity : -Infinity;
}
