import { api, type MediaItem } from './api';

/** A cell as stored: a value, or a reference to a media item logged with the table. */
export type Cell = number | string | boolean | null | { $cell: string };

export interface TableColumn {
  name: string;
  type: 'number' | 'bool' | 'text' | 'audio' | 'image';
}

/** A table as `add_table` stores it. */
export interface TableData {
  columns: TableColumn[];
  /** The column that matches rows across steps. */
  id: string;
  rows: Cell[][];
}

const tables = new Map<string, Promise<TableData | null>>();

/** Fetch (once) the table at a media URL. */
export function loadTable(url: string): Promise<TableData | null> {
  if (!tables.has(url))
    tables.set(
      url,
      fetch(url)
        .then((r) => (r.ok ? (r.json() as Promise<TableData>) : null))
        .catch(() => null),
    );
  return tables.get(url)!;
}

const lists = new Map<string, Promise<MediaItem[]>>();

/** A run's media list, fetched once per page load (tables need it for their history and cells). */
export function runMedia(runKey: string): Promise<MediaItem[]> {
  if (!lists.has(runKey))
    lists.set(
      runKey,
      api
        .media(runKey)
        .then((r) => r.items)
        .catch(() => []),
    );
  return lists.get(runKey)!;
}

/** Forget cached tables and media lists, e.g. when new steps may have been logged. */
export function forgetTables(): void {
  tables.clear();
  lists.clear();
}

export const isCellRef = (v: Cell): v is { $cell: string } => typeof v === 'object' && v !== null;

/**
 * Compile a row filter: comparisons such as `snr_in < 0` or `noise = babble`
 * joined with `and`; any other text matches the row id. Throws on an unknown
 * column or a non-numeric value compared with a number column.
 */
export function rowFilter(text: string, columns: TableColumn[]): (row: Cell[], id: string) => boolean {
  const t = text.trim();
  if (!t) return () => true;
  const index = new Map(columns.map((c, i) => [c.name, i]));
  const tests = t.split(/\s+and\s+/i).map((part) => {
    const m = part.match(/^([\w./-]+)\s*(<=|>=|!=|=|<|>)\s*(.+)$/);
    if (!m) return (_: Cell[], id: string) => id.toLowerCase().includes(part.toLowerCase());
    const [, name, op, rawValue] = m;
    const i = index.get(name);
    if (i === undefined) throw new Error(`no column named ${name}`);
    const raw = rawValue.trim().replace(/^["']|["']$/g, '');
    const kind = columns[i].type;
    const num = Number(raw);
    if (kind === 'number' && Number.isNaN(num)) throw new Error(`${name} is a number column`);
    return (row: Cell[]) => {
      const v = row[i];
      if (v === null || isCellRef(v)) return op === '!=';
      if (kind === 'number') {
        const x = v as number;
        return op === '<'
          ? x < num
          : op === '>'
            ? x > num
            : op === '<='
              ? x <= num
              : op === '>='
                ? x >= num
                : op === '!='
                  ? x !== num
                  : x === num;
      }
      const s = String(v);
      return op === '!=' ? s !== raw : op === '=' ? s === raw : false;
    };
  });
  return (row, id) => tests.every((f) => f(row, id));
}

function escHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

/**
 * A table as static HTML for an export: the first `limit` rows, with each
 * number tinted by its change since `base` (green better, orange worse) and
 * the change next to it. Colors come from the export's `--s4` and `--s5`.
 */
export function tableHtml(
  table: TableData,
  base: TableData | null,
  lowerIsBetter: (name: string) => boolean,
  limit = 200,
): string {
  const idCol = Math.max(
    0,
    table.columns.findIndex((c) => c.name === table.id),
  );
  const baseId = base
    ? Math.max(
        0,
        base.columns.findIndex((c) => c.name === base.id),
      )
    : 0;
  const baseRows = new Map((base?.rows ?? []).map((r) => [String(r[baseId] ?? ''), r]));
  const baseCol = table.columns.map((c) => (base ? base.columns.findIndex((b) => b.name === c.name) : -1));
  const ranges = table.columns.map((c, i) => {
    const vals = table.rows.map((r) => r[i]).filter((v): v is number => typeof v === 'number');
    return c.type === 'number' && vals.length ? Math.max(...vals) - Math.min(...vals) || 1 : 1;
  });
  const decimals = table.columns.map((_, i) => {
    const vals = table.rows.map((r) => r[i]).filter((v): v is number => typeof v === 'number');
    for (let d = 0; d <= 3; d++)
      if (vals.every((v) => Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) < 1e-6)) return d;
    return 3;
  });
  const head = table.columns
    .map((c) => `<th${c.type === 'number' ? ' class="n"' : ''}>${escHtml(c.name)}</th>`)
    .join('');
  const body = table.rows
    .slice(0, limit)
    .map((row) => {
      const old = baseRows.get(String(row[idCol] ?? ''));
      const cells = row.map((v, i) => {
        if (isCellRef(v)) return `<td class="m">${table.columns[i].type}</td>`;
        if (typeof v === 'number') {
          const was = old && baseCol[i] >= 0 ? old[baseCol[i]] : null;
          let extra = '';
          let style = '';
          if (typeof was === 'number' && v !== was) {
            const delta = v - was;
            const good = lowerIsBetter(table.columns[i].name) ? delta < 0 : delta > 0;
            const size = Math.abs(delta) / ranges[i];
            if (size >= 0.01)
              style = ` style="background:color-mix(in srgb, var(${good ? '--s4' : '--s5'}) ${Math.round(Math.min(40, 6 + size * 90))}%, transparent)"`;
            extra = `<small>${delta > 0 ? '+' : '−'}${Math.abs(delta).toFixed(decimals[i])}</small>`;
          }
          return `<td class="n"${style}>${v.toFixed(decimals[i])}${extra}</td>`;
        }
        if (typeof v === 'boolean') return `<td>${v ? '✓' : '–'}</td>`;
        return `<td>${escHtml(String(v ?? ''))}</td>`;
      });
      return `<tr>${cells.join('')}</tr>`;
    })
    .join('');
  const more = table.rows.length > limit ? `<p class="nbmore">First ${limit} of ${table.rows.length} rows.</p>` : '';
  return `<div class="nbtable"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
}
