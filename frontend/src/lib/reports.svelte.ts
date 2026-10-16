import { api } from './api';
import { ask } from './dialog.svelte';
import { prefs } from './router.svelte';

// Adding items (media, charts) to a report, and the notice that offers to open it.

export const lastAdded = $state<{ value: { project: string; name: string } | null }>({ value: null });
let timer: ReturnType<typeof setTimeout> | undefined;

/**
 * Ask which report of `project` to add to and with what caption.
 *
 * Returns the report name and caption, or null when cancelled.
 */
export async function askReport(
  project: string,
  caption: string,
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
      { label: 'Caption', value: caption },
    ],
    { confirm: 'Add', message },
  );
  if (!res || !res[0].trim()) return null;
  return { name: res[0].trim(), caption: res[1] };
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
