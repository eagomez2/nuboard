// Filtering and match highlighting for components/ComboBox.svelte.
import type { ComboOption } from './dialog.svelte';

/** The options whose label, detail or value contain `query`, case-insensitively, in their order. */
export function comboMatches(options: ComboOption[], query: string): ComboOption[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;
  return options.filter((o) => [o.label, o.detail ?? '', o.value].some((s) => s.toLowerCase().includes(q)));
}

/** `text` split into the parts that match `query` (case-insensitively) and the rest. */
export function highlight(text: string, query: string): { text: string; hit: boolean }[] {
  const q = query.trim().toLowerCase();
  if (!q) return [{ text, hit: false }];
  const parts: { text: string; hit: boolean }[] = [];
  const low = text.toLowerCase();
  let at = 0;
  for (let i = low.indexOf(q); i >= 0; i = low.indexOf(q, at)) {
    if (i > at) parts.push({ text: text.slice(at, i), hit: false });
    parts.push({ text: text.slice(i, i + q.length), hit: true });
    at = i + q.length;
  }
  if (at < text.length) parts.push({ text: text.slice(at), hit: false });
  return parts;
}
