// Suggestions for the query bar (components/QueryBar.svelte): what can come next at the caret.
//
// The fields and their common values come once from `/api/query-fields` when the bar gains
// focus; everything here runs on that snapshot, so typing makes no requests and a live run
// update never changes the list under the caret.

export interface QueryField {
  /** As written in a query: `status`, `config.optim.lr`, `fields.stage`, `train/loss`. */
  name: string;
  kind: 'run' | 'config' | 'field' | 'metric';
  /** Runs that have it. */
  runs: number;
  /** The most common values, most common first. */
  values: (string | number | boolean)[];
}

export interface Suggestion {
  /** What the list shows. */
  label: string;
  /** What replaces the word at the caret. */
  insert: string;
  detail?: string;
  kind: 'field' | 'value' | 'keyword' | 'operator' | 'example';
}

export interface Completion {
  /** The text between `from` and `to` is replaced by a picked suggestion. */
  from: number;
  to: number;
  /** The partly typed word the list is narrowed by (without an opening quote). */
  word: string;
  items: Suggestion[];
}

type Token = { kind: 'str' | 'num' | 'op' | 'kw' | 'word'; text: string };

// the same tokens as nuboard/query.py
const TOKEN =
  /\s*(?:("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(?![\w/]))|(==|!=|<=|>=|!~|=|<|>|~|\(|\)|,)|([A-Za-z_][\w./\-±+]*))/y;
const KEYWORDS = new Set([
  'where',
  'and',
  'or',
  'not',
  'group',
  'by',
  'agg',
  'order',
  'asc',
  'desc',
  'has',
  'in',
  'limit',
  'exists',
]);
const COMPARE = new Set(['=', '==', '!=', '<', '<=', '>', '>=', '~', '!~']);
const STATS: [string, string][] = [
  ['last', 'last value'],
  ['min', 'lowest value'],
  ['max', 'highest value'],
  ['count', 'points logged'],
  ['step', 'last step'],
  ['nonfinite', 'NaN or Inf points'],
];
export const AGGS: [string, string][] = [
  ['mean±std', 'mean with a ±1 std band'],
  ['mean±sem', 'mean with a ±1 standard error band'],
  ['min-max', 'mean with a min–max band'],
  ['median', 'median with a 25–75% band'],
  ['none', 'every run as its own line'],
];
const FIELD_HELP: Record<string, string> = {
  status: 'running, finished, crashed, killed or lost',
  project: 'project folder',
  tags: 'use with has',
  host: 'machine',
  group: 'run group',
  collections: 'use with has',
  name: 'run name',
  starred: 'true or false',
  archived: 'true or false',
  reviewed: 'true or false',
  created: 'Unix time',
  started: 'Unix time',
  ended: 'Unix time',
  duration: 'seconds',
  world_size: 'ranks',
  alerts: 'number of health alerts',
  commit: 'git commit',
  notes: 'use with ~ or has',
};
const LIMIT = 60;

/** Tokens of `text`, skipping characters that start none (the server reports those). */
function tokenize(text: string): Token[] {
  const out: Token[] = [];
  let pos = 0;
  while (pos < text.length) {
    TOKEN.lastIndex = pos;
    const m = TOKEN.exec(text);
    if (!m || m.index !== pos || TOKEN.lastIndex === pos) {
      pos++;
      continue;
    }
    pos = TOKEN.lastIndex;
    if (m[1] !== undefined) out.push({ kind: 'str', text: m[1] });
    else if (m[2] !== undefined) out.push({ kind: 'num', text: m[2] });
    else if (m[3] !== undefined) out.push({ kind: 'op', text: m[3] });
    else if (m[4] !== undefined) {
      const low = m[4].toLowerCase();
      out.push(KEYWORDS.has(low) ? { kind: 'kw', text: low } : { kind: 'word', text: m[4] });
    }
  }
  return out;
}

/** A value as it is written in a query: bare when it reads as one word, else quoted. */
export function quoteValue(v: string | number | boolean): string {
  if (typeof v !== 'string') return String(v);
  if (/^[A-Za-z_][\w./-]*$/.test(v) && !KEYWORDS.has(v.toLowerCase())) return v;
  return JSON.stringify(v);
}

/** Suggestions whose label holds `word`, those starting with it first, then the order given. */
function narrow(items: Suggestion[], word: string): Suggestion[] {
  const w = word.toLowerCase();
  if (!w) return items.slice(0, LIMIT);
  const starts: Suggestion[] = [];
  const parts: Suggestion[] = [];
  for (const it of items) {
    const low = it.label.toLowerCase();
    if (low === w && it.kind !== 'value') continue; // typed in full already
    // a config key also matches by its last parts, so `lr` finds `config.optim.lr`
    if (low.startsWith(w) || (it.kind === 'field' && low.startsWith('config.' + w))) starts.push(it);
    else if (low.includes(w)) parts.push(it);
  }
  return [...starts, ...parts].slice(0, LIMIT);
}

function fieldItems(fields: QueryField[]): Suggestion[] {
  return fields.map((f) => ({
    label: f.name,
    insert: f.name,
    kind: 'field',
    detail:
      f.kind === 'run'
        ? (FIELD_HELP[f.name] ?? 'run')
        : `${f.kind === 'field' ? 'custom field' : f.kind} · ${f.runs.toLocaleString()} run${f.runs === 1 ? '' : 's'}`,
  }));
}

function words(list: [string, string][], kind: Suggestion['kind']): Suggestion[] {
  return list.map(([label, detail]) => ({ label, insert: label, detail, kind }));
}

/** The field a value at token `i` (exclusive) is compared with, if any. */
function fieldBefore(tokens: Token[], i: number): string | null {
  // field op | field has | field in ( v, v,
  let j = i - 1;
  if (j >= 0 && (tokens[j].text === ',' || tokens[j].text === '(')) {
    while (j >= 0 && tokens[j].text !== '(') j--;
    if (j < 1 || tokens[j - 1].text !== 'in') return null;
    j -= 1; // at `in`
    if (j >= 1 && tokens[j - 1].text === 'not') j -= 1;
  }
  const f = tokens[j - 1];
  return f && f.kind === 'word' ? f.text : null;
}

function valueItems(field: string | null, fields: QueryField[], op: string): Suggestion[] {
  const f = field
    ? fields.find((x) => x.name === field || x.name === `config.${field}` || x.name === `fields.${field}`)
    : null;
  const values = f?.values ?? [];
  const items: Suggestion[] = values.map((v) => ({
    label: String(v),
    insert: quoteValue(v),
    kind: 'value',
    detail: typeof v === 'string' ? undefined : typeof v,
  }));
  if (!items.length && (f?.kind === 'metric' || op === '<' || op === '>')) return [];
  return items;
}

/** What may follow a complete term, given the clause the caret is in. */
function afterTerm(tokens: Token[]): Suggestion[] {
  const last = tokens[tokens.length - 1];
  const prev = tokens[tokens.length - 2];
  let clause = 'where';
  for (const t of tokens) {
    if (t.kind !== 'kw') continue;
    if (t.text === 'group' || t.text === 'order' || t.text === 'agg' || t.text === 'limit') clause = t.text;
  }
  const kw = (label: string, detail: string): Suggestion => ({ label, insert: label, detail, kind: 'keyword' });
  const tail = [
    kw('group by', 'one line per value'),
    kw('agg', 'how grouped lines are drawn'),
    kw('order by', 'sort the runs'),
    kw('limit', 'keep the first runs'),
  ];
  const used = (k: string) => tokens.some((t) => t.kind === 'kw' && t.text === k);
  const rest = tail.filter((s) => !used(s.label.split(' ')[0]));
  if (clause === 'order') {
    const dir = last.kind === 'kw' && (last.text === 'asc' || last.text === 'desc');
    return [...(dir ? [] : [kw('desc', 'highest first'), kw('asc', 'lowest first')]), ...rest];
  }
  if (clause !== 'where') return rest;
  // a field just written, at the start or after where/and/or/not/(: an operator comes next
  const fieldStart =
    last.kind === 'word' &&
    (!prev || (prev.kind === 'kw' && ['where', 'and', 'or', 'not'].includes(prev.text)) || prev.text === '(');
  if (fieldStart) {
    const op = (label: string, detail: string): Suggestion => ({ label, insert: label, detail, kind: 'operator' });
    return [
      op('=', 'equals'),
      op('!=', 'differs from'),
      op('<', 'less than'),
      op('>', 'greater than'),
      op('<=', 'at most'),
      op('>=', 'at least'),
      op('~', 'matches a regular expression'),
      op('!~', 'does not match'),
      op('has', 'list holds, or text contains'),
      op('in (', 'one of a list'),
      op('exists', 'is set'),
    ];
  }
  return [kw('and', 'both hold'), kw('or', 'either holds'), ...rest];
}

/**
 * The suggestions at `caret` in `text`, given the workspace's fields, or null when there is
 * nothing to suggest (inside a number, after `limit`, or with no fields loaded yet).
 */
export function complete(
  text: string,
  caret: number,
  fields: QueryField[],
  examples: string[] = [],
): Completion | null {
  const before = text.slice(0, caret);
  // the word at the caret: a field or bare value, a number, or a quoted string still open
  const m = /(?:"(?:[^"\\]|\\.)*|'(?:[^'\\]|\\.)*|[A-Za-z_][\w./\-±+]*|[-+]?[\d.][\w.+-]*)$/.exec(before);
  let from = m ? m.index : caret;
  let partial = m ? m[0] : '';
  // a word is only partial when nothing but space or an operator comes before it
  if (partial && from > 0 && /[\w"']/.test(before[from - 1])) {
    from = caret;
    partial = '';
  }
  const quoted = partial.startsWith('"') || partial.startsWith("'");
  const rest = /^[\w./\-±+]*["']?/.exec(text.slice(caret))?.[0] ?? '';
  const to = caret + (quoted || /^[A-Za-z_]/.test(partial) || !partial ? rest.length : 0);
  const word = quoted ? partial.slice(1) : partial;
  const tokens = tokenize(text.slice(0, from));
  const last = tokens[tokens.length - 1];
  const result = (items: Suggestion[]): Completion | null => (items.length ? { from, to, word, items } : null);

  if (!text.trim() && examples.length) {
    return {
      from: 0,
      to: text.length,
      word: '',
      items: [
        ...examples.map((e): Suggestion => ({ label: e, insert: e, kind: 'example', detail: 'example' })),
        ...fieldItems(fields).slice(0, LIMIT),
      ],
    };
  }

  // a metric name and a dot: its summary statistics
  const dot = /^(.+)\.(\w*)$/.exec(partial);
  if (!quoted && dot && fields.some((f) => f.kind === 'metric' && f.name === dot[1])) {
    const stats = STATS.map(([s, d]): Suggestion => ({
      label: `${dot[1]}.${s}`,
      insert: `${dot[1]}.${s}`,
      detail: d,
      kind: 'field',
    }));
    return result(narrow(stats, partial));
  }

  const expectField =
    !last ||
    (last.kind === 'kw' && ['where', 'and', 'or', 'not', 'by'].includes(last.text)) ||
    (last.text === '(' && fieldBefore(tokens, tokens.length) === null);
  if (expectField) {
    const items = fieldItems(fields);
    if (!last) items.unshift({ label: 'where', insert: 'where', detail: 'optional, before a filter', kind: 'keyword' });
    if (last && last.text === 'by') {
      const order = tokens[tokens.length - 2]?.text === 'order';
      // `group by` and `order by` take a field only; metrics sort by their stats
      if (order) {
        const metrics = fields.filter((f) => f.kind === 'metric');
        for (const f of metrics)
          items.push({ label: `${f.name}.min`, insert: `${f.name}.min`, detail: 'lowest value', kind: 'field' });
      }
    }
    return result(narrow(items, word));
  }

  if (last.kind === 'kw' && last.text === 'agg') return result(narrow(words(AGGS, 'keyword'), word));
  if (last.kind === 'kw' && last.text === 'limit') return null;

  const isValueSlot =
    (last.kind === 'op' && COMPARE.has(last.text)) ||
    (last.kind === 'kw' && last.text === 'has') ||
    ((last.text === '(' || last.text === ',') && fieldBefore(tokens, tokens.length) !== null);
  if (isValueSlot) {
    if (/^[-+\d.]/.test(partial)) return null; // typing a number
    return result(narrow(valueItems(fieldBefore(tokens, tokens.length), fields, last.text), word));
  }

  if (last.kind === 'kw' && last.text === 'in')
    return result([{ label: '(', insert: '(', kind: 'operator', detail: 'start the list' }]);
  if (last.kind === 'kw' && (last.text === 'group' || last.text === 'order')) {
    return result(narrow([{ label: 'by', insert: 'by', kind: 'keyword' }], word));
  }
  // after a complete term: an operator, or the next keyword
  if (!partial || /^[A-Za-z_]/.test(partial)) return result(narrow(afterTerm(tokens), word));
  return null;
}

/** `text` with the word of `c` replaced by `s`, and where the caret goes after it. */
export function applySuggestion(text: string, c: Completion, s: Suggestion): { text: string; caret: number } {
  if (s.kind === 'example') return { text: s.insert, caret: s.insert.length };
  const after = text.slice(c.to);
  const join = s.insert.endsWith('(') ? '' : ' ';
  const space = after.startsWith(' ') || (join === '' && after.startsWith('(')) ? '' : join;
  const out = text.slice(0, c.from) + s.insert + space + after;
  return { text: out, caret: c.from + s.insert.length + (space || (after.startsWith(' ') ? ' ' : '')).length };
}
