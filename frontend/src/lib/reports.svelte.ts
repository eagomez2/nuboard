import { api } from './api';
import { ask } from './dialog.svelte';
import { prefs } from './router.svelte';

// Adding items (media, charts) to a report, and the notice that offers to open it.

export const lastAdded = $state<{ value: { project: string; name: string } | null }>({ value: null });
let timer: ReturnType<typeof setTimeout> | undefined;

/**
 * Ask which report of `project` to add to and with what caption (none asked when `caption` is null).
 *
 * Returns the report name and caption, or null when cancelled.
 */
export async function askReport(
  project: string,
  caption: string | null,
  message: string,
): Promise<{ name: string; caption: string } | null> {
  const names = (await api.reports(project)).reports.map((r) => r.name);
  const res = await ask(
    'Add to a report',
    [
      {
        label: 'Report',
        value: prefs.get('lastReport', names[0] ?? 'notes'),
        suggestions: names,
        hint: `In ${project}/reports/. A new name starts a new report.`,
      },
      ...(caption === null ? [] : [{ label: 'Caption', value: caption }]),
    ],
    { confirm: 'Add', message },
  );
  if (!res || !res[0].trim()) return null;
  return { name: res[0].trim(), caption: res[1] ?? '' };
}

/** Append a Markdown block to a report (creating it if needed) and show the notice. */
export async function appendToReport(project: string, name: string, block: string) {
  const saved = await api.saveReport({ project, name, append: block });
  if (saved.error) throw new Error(saved.error);
  const final = saved.saved ?? name;
  prefs.set('lastReport', final);
  lastAdded.value = { project, name: final };
  clearTimeout(timer);
  timer = setTimeout(() => (lastAdded.value = null), 6000);
}

/**
 * Ask for a report and add a PNG snapshot to it, linked to the page it came from.
 *
 * The line is `![caption](files/x.png "view:<page>?<params>")`: an image in any Markdown viewer,
 * and in nuboard also an "Open in ..." button that restores the view.
 */
export async function addSnapshotToReport(
  project: string,
  png: string,
  caption: string,
  view: { page: string; params: Record<string, string> },
): Promise<boolean> {
  const res = await askReport(project, caption, 'A snapshot of the plot as shown now, linked to this page.');
  if (!res) return false;
  const shot = await api.saveSnapshot(project, res.name, png);
  if (!shot.path) throw new Error(shot.error ?? 'could not save the snapshot');
  const params = new URLSearchParams(view.params).toString();
  const cap = res.caption.replace(/[[\]\n]/g, ' ');
  await appendToReport(project, res.name, `![${cap}](${shot.path} "view:${view.page}?${params}")`);
  return true;
}

/**
 * Ask for a report and add the "All runs on one chart" overlay of PR curves or distributions.
 *
 * The line is `![caption](files/x.png "overlay:<ref> <ref> ...")`, one `media:` reference per run:
 * a PNG in any Markdown viewer, and in nuboard the chart drawn live from the logged items.
 */
export async function addOverlayToReport(
  project: string,
  png: string,
  caption: string,
  refs: string[],
): Promise<boolean> {
  const res = await askReport(project, caption, 'The chart of every run, drawn live in the report.');
  if (!res) return false;
  const shot = await api.saveSnapshot(project, res.name, png);
  if (!shot.path) throw new Error(shot.error ?? 'could not save the snapshot');
  const cap = res.caption.replace(/[[\]\n]/g, ' ');
  await appendToReport(project, res.name, `![${cap}](${shot.path} "overlay:${refs.join(' ')}")`);
  return true;
}
