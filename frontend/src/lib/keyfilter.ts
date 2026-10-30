// Filters lists of dotted keys, such as the settings of compared runs, by text.
//
// Terms are separated by spaces and must all match. A term is a case-insensitive
// substring, or a regular expression when wrapped in slashes (`/\.(min|max)$/`) or
// when `regex` is on. A leading `!` excludes keys that match. Text wrapped in slashes
// as a whole is one regular expression, spaces included.

export interface KeyFilter {
  /** Whether a key (or with `values`, one of its values) passes every term. */
  test: (key: string, values?: string[]) => boolean;
  /** Ranges `[start, end)` of `key` that the including terms match, sorted and merged. */
  highlight: (key: string) => [number, number][];
  /** The message of an invalid regular expression; the filter then lets everything pass. */
  error: string | null;
  /** True when there is nothing to filter by. */
  empty: boolean;
}

interface Term {
  re: RegExp;
  exclude: boolean;
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const everything: KeyFilter = { test: () => true, highlight: () => [], error: null, empty: true };

function term(text: string, regex: boolean): Term | null {
  const exclude = text.startsWith('!');
  const body = exclude ? text.slice(1) : text;
  if (!body) return null;
  const slashed = body.length > 1 && body.startsWith('/') && body.endsWith('/');
  const source = slashed ? body.slice(1, -1) : regex ? body : escape(body);
  return { re: new RegExp(source, 'gi'), exclude };
}

export function keyFilter(text: string, opts: { regex?: boolean; values?: boolean } = {}): KeyFilter {
  const trimmed = text.trim();
  if (!trimmed) return everything;
  let terms: Term[];
  try {
    const whole = trimmed.replace(/^!/, '');
    terms = (
      whole.length > 1 && whole.startsWith('/') && whole.endsWith('/')
        ? [term(trimmed, false)]
        : trimmed.split(/\s+/).map((t) => term(t, !!opts.regex))
    ).filter((t): t is Term => t !== null);
  } catch (e) {
    return { ...everything, error: (e as Error).message, empty: false };
  }
  if (!terms.length) return everything;

  const hit = (re: RegExp, s: string) => {
    re.lastIndex = 0;
    return re.test(s);
  };
  return {
    error: null,
    empty: false,
    test: (key, values = []) =>
      terms.every((t) => {
        const found = hit(t.re, key) || (!!opts.values && values.some((v) => hit(t.re, v)));
        return found !== t.exclude;
      }),
    highlight: (key) => {
      const ranges: [number, number][] = [];
      for (const t of terms) {
        if (t.exclude) continue;
        t.re.lastIndex = 0;
        for (const m of key.matchAll(t.re)) {
          if (m[0].length) ranges.push([m.index, m.index + m[0].length]);
        }
      }
      ranges.sort((a, b) => a[0] - b[0]);
      const merged: [number, number][] = [];
      for (const r of ranges) {
        const last = merged[merged.length - 1];
        if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
        else merged.push([...r]);
      }
      return merged;
    },
  };
}

/** `text` cut into parts, marking those inside `ranges` (as from `KeyFilter.highlight`). */
export function splitMarked(text: string, ranges: [number, number][]): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  let at = 0;
  for (const [a, b] of ranges) {
    if (a > at) parts.push({ text: text.slice(at, a), mark: false });
    parts.push({ text: text.slice(a, b), mark: true });
    at = b;
  }
  if (at < text.length) parts.push({ text: text.slice(at), mark: false });
  return parts;
}
