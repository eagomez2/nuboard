/** What tells runs with the same name apart in a run picker (see RunLine and RunPicker). */

/** A run as a picker lists it: a RunBrief, or a stand-in for a run that is gone. */
export interface PickRun {
  id: string;
  name: string;
  status: string;
  started?: number | null;
  created?: number | null;
  tags?: string[];
}

/** The random part of a run id (`20261109T1554-103745e1` → `103745e1`), or the id itself. */
export const idSuffix = (id: string): string => id.split('-').pop() || id;

/** Whether a run matches a picker's filter text: by name, id, status, tag or its context line. */
export function pickMatches(r: PickRun, q: string, context = ''): boolean {
  const t = q.trim().toLowerCase();
  if (!t) return true;
  return [r.name, r.id, r.status, context, ...(r.tags ?? []).map((g) => `#${g}`)].some((s) =>
    s.toLowerCase().includes(t),
  );
}
