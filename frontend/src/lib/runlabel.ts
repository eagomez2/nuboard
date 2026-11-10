import { keyFilter } from './keyfilter';

/** What tells runs with the same name apart in a run picker (see RunLine and RunPicker). */

/** A run as a picker lists it: a RunBrief, or a stand-in for a run that is gone. */
export interface PickRun {
  id: string;
  name: string;
  status: string;
  started?: number | null;
  created?: number | null;
  tags?: string[];
  project?: string;
  notes?: string;
}

/** The random part of a run id (`20261109T1554-103745e1` → `103745e1`), or the id itself. */
export const idSuffix = (id: string): string => id.split('-').pop() || id;

/**
 * Whether a run matches a run filter: by name, id, status, project, tag (also as `#tag`), notes or
 * a context line. The text follows the shared filter rule (lib/keyfilter.ts): words that must all
 * match, `/regex/`, and `!word` to leave runs out.
 */
export function pickMatches(r: PickRun, q: string, context = ''): boolean {
  const f = keyFilter(q);
  if (f.empty) return true;
  const tags = (r.tags ?? []).flatMap((g) => [g, `#${g}`]);
  return f.test([r.name, r.id, r.status, r.project ?? '', r.notes ?? '', context, ...tags].join('\n'));
}
