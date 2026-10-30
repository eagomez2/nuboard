/** Pure helpers for the Sweeps page: axes, scales and parameter importance. */

export type Value = string | number | boolean | null | undefined;

export interface Axis {
  key: string;
  numeric: boolean;
  log: boolean;
  min: number;
  max: number;
  /** Category labels in display order (categorical axes only). */
  categories: string[];
  /** Short labels for list and dict categories (see `diffLabels`); absent ones show as is. */
  labels: Record<string, string>;
}

export function isNum(v: Value): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

const catLabel = (v: Value) => (v === null || v === undefined ? '—' : String(v));

/** The category that gathers the less common values of an axis with too many of them. */
export const OTHER = '(other)';
/** A category key with more distinct values than this is marked, kept out of defaults and capped. */
export const MANY_VALUES = 12;

/**
 * An axis for the values of one key: numeric (log when the range is wide) or categorical.
 * A categorical axis keeps its `maxCategories - 1` most common values and gathers the rest in OTHER.
 */
export function makeAxis(key: string, values: Value[], maxCategories = MANY_VALUES): Axis {
  const present = values.filter((v) => v !== null && v !== undefined);
  const numeric = present.length > 0 && present.every(isNum);
  if (numeric) {
    const nums = present as number[];
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const log = min > 0 && max / min >= 20;
    return { key, numeric, log, min, max, categories: [], labels: {} };
  }
  const counts = new Map<string, number>();
  for (const v of values) counts.set(catLabel(v), (counts.get(catLabel(v)) ?? 0) + 1);
  let cats = [...counts.keys()];
  const capped = cats.length > maxCategories;
  if (capped) cats = cats.sort((a, b) => counts.get(b)! - counts.get(a)!).slice(0, maxCategories - 1);
  cats.sort((a, b) => {
    const na = Number(a);
    const nb = Number(b);
    return Number.isFinite(na) && Number.isFinite(nb) ? na - nb : a.localeCompare(b);
  });
  if (capped) cats.push(OTHER);
  const labels = diffLabels(cats);
  return { key, numeric: false, log: false, min: 0, max: Math.max(cats.length - 1, 1), categories: cats, labels };
}

/** Position of a value on an axis in [0, 1] (0 = bottom), or null if it has none. */
export function norm(axis: Axis, v: Value): number | null {
  if (axis.numeric) {
    if (!isNum(v)) return null;
    if (axis.max === axis.min) return 0.5;
    if (axis.log) return (Math.log(v) - Math.log(axis.min)) / (Math.log(axis.max) - Math.log(axis.min));
    return (v - axis.min) / (axis.max - axis.min);
  }
  let i = axis.categories.indexOf(catLabel(v));
  if (i < 0) i = axis.categories.indexOf(OTHER); // a value gathered in OTHER, or -1
  if (i < 0) return null;
  return axis.categories.length === 1 ? 0.5 : i / (axis.categories.length - 1);
}

/** The text shown for a category: its short label, or the value itself. */
export const shownLabel = (axis: Axis, category: string) => axis.labels[category] ?? category;

/**
 * A few labelled ticks for an axis: [position 0..1, label, full value]. The full value differs
 * from the label for list and dict categories.
 */
export function axisTicks(axis: Axis, fmt: (v: number) => string): [number, string, string?][] {
  if (!axis.numeric)
    return axis.categories.map((c, i, all) => [all.length === 1 ? 0.5 : i / (all.length - 1), shownLabel(axis, c), c]);
  if (axis.max === axis.min) return [[0.5, fmt(axis.min)]];
  if (axis.log) {
    const out: [number, string][] = [];
    const lo = Math.floor(Math.log10(axis.min));
    const hi = Math.ceil(Math.log10(axis.max));
    for (let e = lo; e <= hi; e++) {
      for (const m of hi - lo <= 2 ? [1, 3] : [1]) {
        const v = m * 10 ** e;
        if (v >= axis.min * 0.999 && v <= axis.max * 1.001) out.push([norm(axis, v)!, fmt(v)]);
      }
    }
    if (out.length < 2) out.push([0, fmt(axis.min)], [1, fmt(axis.max)]);
    return out;
  }
  return [0, 0.25, 0.5, 0.75, 1].map((f) => [f, fmt(axis.min + f * (axis.max - axis.min))]);
}

function ranks(xs: number[]): number[] {
  const order = xs.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]);
  const r = new Array<number>(xs.length);
  for (let i = 0; i < order.length;) {
    let j = i;
    while (j + 1 < order.length && order[j + 1][0] === order[i][0]) j++;
    for (let k = i; k <= j; k++) r[order[k][1]] = (i + j) / 2;
    i = j + 1;
  }
  return r;
}

function pearson(a: number[], b: number[]): number {
  const n = a.length;
  const ma = a.reduce((s, v) => s + v, 0) / n;
  const mb = b.reduce((s, v) => s + v, 0) / n;
  let num = 0;
  let da = 0;
  let db = 0;
  for (let i = 0; i < n; i++) {
    num += (a[i] - ma) * (b[i] - mb);
    da += (a[i] - ma) ** 2;
    db += (b[i] - mb) ** 2;
  }
  return da && db ? num / Math.sqrt(da * db) : 0;
}

/**
 * How strongly a parameter is associated with the metric, in [0, 1]:
 * |Spearman correlation| for numbers, the correlation ratio (eta) on metric
 * ranks for categories. Null with fewer than 3 usable runs.
 */
export function importance(params: Value[], metric: (number | null)[]): number | null {
  const pairs = params.map((p, i) => [p, metric[i]] as const).filter(([, m]) => m !== null && Number.isFinite(m));
  if (pairs.length < 3) return null;
  const m = ranks(pairs.map(([, v]) => v as number));
  if (pairs.every(([p]) => isNum(p))) {
    return Math.abs(pearson(ranks(pairs.map(([p]) => p as number)), m));
  }
  const groups = new Map<string, number[]>();
  pairs.forEach(([p], i) => {
    const k = catLabel(p);
    groups.set(k, [...(groups.get(k) ?? []), m[i]]);
  });
  if (groups.size < 2) return 0;
  const mean = m.reduce((s, v) => s + v, 0) / m.length;
  const total = m.reduce((s, v) => s + (v - mean) ** 2, 0);
  let between = 0;
  for (const g of groups.values()) {
    const gm = g.reduce((s, v) => s + v, 0) / g.length;
    between += g.length * (gm - mean) ** 2;
  }
  return total ? Math.sqrt(between / total) : 0;
}

/** What the parameter picker shows about one key, and what defaults are chosen from. */
export interface ParamInfo {
  key: string;
  numeric: boolean;
  /** Distinct values among the runs (missing counts as one). */
  distinct: number;
  /** A category with a different value in every run, such as an id, a timestamp or a folder. */
  unique: boolean;
  /** A category with more than MANY_VALUES distinct values. */
  many: boolean;
  /** Some value is text longer than 40 characters. */
  long: boolean;
  /** Association with the objective in [0, 1] (see `importance`); null with too few runs. */
  score: number | null;
  /** Some value is a list or dict. */
  complex: boolean;
  /** The length of the list when it can be split into elements (see `splitLength`), else 0. */
  split: number;
}

export function paramInfo(key: string, values: Value[], metric: (number | null)[]): ParamInfo {
  const present = values.filter((v) => v !== null && v !== undefined);
  const numeric = present.length > 0 && present.every(isNum);
  const distinct = new Set(values.map(catLabel)).size;
  return {
    key,
    numeric,
    distinct,
    unique: !numeric && values.length >= 3 && distinct === values.length,
    many: !numeric && distinct > MANY_VALUES,
    long: present.some((v) => typeof v === 'string' && v.length > 40 && !parseComplex(v)),
    score: importance(values, metric),
    complex: present.some((v) => parseComplex(v) !== undefined),
    split: splitLength(present),
  };
}

/** Names left out of the defaults: seeds, and paths, folders and files. */
export const SKIPPED_NAME = /seed|(^|[._-])(path|dir|file|folder)s?($|[._-])|(path|dir)$/i;

/**
 * The parameters shown when none are picked: up to `n` keys, the most associated with the
 * objective first (ties keep their order), leaving out seeds, paths, ids, long text, keys with
 * many values and hidden keys.
 */
export function defaultParams(infos: ParamInfo[], hidden: (key: string) => boolean = () => false, n = 6): string[] {
  const name = (key: string) => key.replace(/^fields\./, '');
  return infos
    .filter((p) => !hidden(p.key) && !SKIPPED_NAME.test(name(p.key)) && !p.unique && !p.many && !p.long)
    .map((p, i) => ({ p, i }))
    .sort((a, b) => (b.p.score ?? 0) - (a.p.score ?? 0) || a.i - b.i)
    .slice(0, n)
    .map(({ p }) => p.key);
}

/** Keys grouped under their prefix (everything before the last dot): top-level keys first, then groups in first-seen order. */
export function groupByPrefix<T extends { key: string }>(items: T[]): { prefix: string; items: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const it of items) {
    const at = it.key.lastIndexOf('.');
    const prefix = at < 0 ? '' : it.key.slice(0, at);
    groups.set(prefix, [...(groups.get(prefix) ?? []), it]);
  }
  const out = [...groups.entries()].map(([prefix, items]) => ({ prefix, items }));
  return [...out.filter((g) => !g.prefix), ...out.filter((g) => g.prefix)];
}

/** A list or dict sent as JSON text (`[64, 128]`, `{"lr": 0.1}`), parsed; else undefined. */
export function parseComplex(v: Value | unknown): unknown[] | Record<string, unknown> | undefined {
  if (typeof v !== 'string' || !/^\s*[[{]/.test(v)) return undefined;
  try {
    const out = JSON.parse(v);
    return out !== null && typeof out === 'object' ? out : undefined;
  } catch {
    return undefined;
  }
}

const scalar = (v: unknown) => v === null || typeof v !== 'object';
const show = (v: unknown) => (v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v));

// The leaves of a parsed value by path: `[0]`, `.lr`, `[1].dim`.
function leaves(v: unknown, path = '', out = new Map<string, unknown>()): Map<string, unknown> {
  if (Array.isArray(v)) v.forEach((x, i) => leaves(x, `${path}[${i}]`, out));
  else if (v !== null && typeof v === 'object')
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) leaves(x, `${path}.${k}`, out);
  else out.set(path, v);
  return out;
}

/** The most characters a diff label keeps. */
export const LABEL_MAX = 40;

/**
 * Short labels for categories that are lists or dicts: only what differs between them.
 * Lists of plain values with different lengths are labelled by the items not in every list
 * (`flip, mixup`); anything else by the differing paths (`[0]=0.08`, `.wd=0.1`). Labels are
 * cut to LABEL_MAX characters; a category that is not a list or dict keeps no label.
 */
export function diffLabels(categories: string[]): Record<string, string> {
  const parsed = categories.map((c) => [c, parseComplex(c)] as const).filter(([, v]) => v !== undefined);
  if (parsed.length < 2) return {};
  const cut = (t: string) => (t.length > LABEL_MAX ? t.slice(0, LABEL_MAX - 1) + '…' : t);
  const out: Record<string, string> = {};
  const lists = parsed.map(([, v]) => v).filter((v): v is unknown[] => Array.isArray(v) && v.every(scalar));
  if (lists.length === parsed.length && new Set(lists.map((l) => l.length)).size > 1) {
    const key = (x: unknown) => JSON.stringify(x);
    const common = new Set(lists[0].map(key).filter((k) => lists.every((l) => l.map(key).includes(k))));
    for (const [c, v] of parsed) {
      const rest = (v as unknown[]).filter((x) => !common.has(key(x))).map(show);
      out[c] = cut(rest.length ? rest.join(', ') : common.size ? 'common items only' : '[]');
    }
    return out;
  }
  const maps = parsed.map(([c, v]) => [c, leaves(v)] as const);
  const paths = [...new Set(maps.flatMap(([, m]) => [...m.keys()]))];
  const differing = paths.filter((p) => new Set(maps.map(([, m]) => show(m.get(p)))).size > 1);
  for (const [c, m] of maps) {
    const parts = differing.filter((p) => m.has(p)).map((p) => `${p.replace(/^\./, '')}=${show(m.get(p))}`);
    out[c] = cut(parts.length ? parts.join(', ') : differing.length ? '(fewer items)' : c);
  }
  return out;
}

/** The length of a list key that can be split into elements: every run holds a list of plain values of the same length (2 to 32); else 0. */
export function splitLength(values: Value[]): number {
  const lists = values.map(parseComplex);
  if (!lists.length || lists.some((l) => !Array.isArray(l) || !l.every(scalar))) return 0;
  const n = (lists[0] as unknown[]).length;
  return n >= 2 && n <= 32 && lists.every((l) => (l as unknown[]).length === n) ? n : 0;
}

/** For an element key `layers[2]`, its list key and index; else null. */
export function elementOf(key: string): { base: string; index: number } | null {
  const m = /^(.*)\[(\d+)\]$/.exec(key);
  return m ? { base: m[1], index: Number(m[2]) } : null;
}

/** Element `index` of a list sent as JSON text, or undefined. */
export function elementValue(v: Value, index: number): Value {
  const list = parseComplex(v);
  return Array.isArray(list) ? (list[index] as Value) : undefined;
}
