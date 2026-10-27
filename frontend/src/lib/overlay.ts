// The "All runs on one chart" overlay saved in a report: one `media:` reference per run.

import { api } from './api';
import { seriesVar } from './colors';
import { HIST_MIME, PR_MIME } from './media';

export interface Overlay {
  kind: 'pr' | 'hist';
  key: string;
  curves: { name: string; color: string; url: string }[];
  /** References that were not found, such as runs deleted since. */
  missing: string[];
}

/**
 * Find the items of an overlay's references (`<run id>/<key>@<step>`, space-separated).
 *
 * Throws when none is found, or when they are neither PR curves nor distributions.
 */
export async function resolveOverlay(project: string, refs: string): Promise<Overlay> {
  const list = refs.split(/\s+/).filter(Boolean);
  const found = await Promise.allSettled(list.map((ref) => api.mediaRef(project, ref)));
  const curves: Overlay['curves'] = [];
  const missing: string[] = [];
  let mime = '';
  let key = '';
  found.forEach((res, i) => {
    if (res.status === 'rejected' || res.value.item.index === undefined) {
      missing.push(decodeURIComponent(list[i]));
      return;
    }
    const { run, run_name, item } = res.value;
    mime ||= item.mime;
    key ||= item.key;
    curves.push({
      name: `${run_name} · step ${item.step.toLocaleString()}`,
      color: seriesVar(i),
      url: api.mediaUrl(run, item.index!),
    });
  });
  if (!curves.length) throw new Error(`not found: ${missing.join(', ')}`);
  if (mime !== PR_MIME && mime !== HIST_MIME) throw new Error(`not a PR curve or distribution: ${key}`);
  return { kind: mime === PR_MIME ? 'pr' : 'hist', key, curves, missing };
}
