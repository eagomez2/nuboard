import { api } from './api';
import { app } from './state.svelte';

/** Every tag used by the listed runs, for suggestions. */
export function knownTags(): string[] {
  return [...new Set((app.runs?.runs ?? []).flatMap((r) => r.tags))].sort();
}

/** Split typed text into tags: comma or space separated, without duplicates. */
export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[,\s]+/)
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ];
}

/**
 * Add and remove tags on runs. Each run keeps its other tags; runs that end up
 * with the same list are saved together. The edited list replaces the logged
 * tags (see `annotations.json` in the file format).
 */
export async function editTags(keys: string[], add: string[], remove: string[] = []): Promise<void> {
  const groups = new Map<string, string[]>();
  for (const k of keys) {
    const r = app.runByKey(k);
    if (!r) continue;
    const next = [...new Set([...r.tags.filter((t) => !remove.includes(t)), ...add])].sort();
    if (next.join('\n') === [...r.tags].sort().join('\n')) continue;
    r.tags = next;
    const id = JSON.stringify(next);
    groups.set(id, [...(groups.get(id) ?? []), k]);
  }
  for (const [id, group] of groups) await api.annotate(group, { tags: JSON.parse(id) as string[] });
}
