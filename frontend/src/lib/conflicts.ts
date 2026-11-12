// What to do when a run's notes or properties were saved by someone else after an edit began.
import { ask } from './dialog.svelte';
import type { FieldValue } from './api';

export type Resolution = 'mine' | 'theirs' | 'both';

const preview = (text: string) => {
  const t = text.trim().replace(/\s+/g, ' ');
  return t ? `“${t.length > 160 ? `${t.slice(0, 160)}…` : t}”` : 'empty';
};

/** Ask what to do with notes that changed meanwhile; null keeps the editor open as it is. */
export async function resolveNotes(theirs: string): Promise<Resolution | null> {
  const res = await ask(
    'These notes changed since you started editing',
    [
      {
        label: 'Keep',
        value: 'both',
        options: [
          { value: 'both', label: 'Both' },
          { value: 'mine', label: 'Mine' },
          { value: 'theirs', label: 'Theirs' },
        ],
      },
    ],
    {
      message:
        `Someone saved this run's notes after you opened them. Theirs are now ${preview(theirs)}. ` +
        'Both puts your text under theirs to tidy up before saving; Mine replaces theirs; Theirs drops your edit.',
      confirm: 'Continue',
    },
  );
  return (res?.[0] as Resolution | undefined) ?? null;
}

const shown = (v: FieldValue | null | undefined) =>
  v === null || v === undefined || v === '' ? 'unset' : Array.isArray(v) ? v.join(', ') || 'unset' : String(v);

/** Ask whether to overwrite properties that changed meanwhile; true saves mine. */
export async function resolveFields(
  changed: Record<string, { mine: FieldValue | null; theirs: FieldValue | null | undefined }>,
  runs = 1,
): Promise<boolean> {
  const lines = Object.entries(changed).map(([k, v]) => `${k}: now ${shown(v.theirs)}, yours ${shown(v.mine)}`);
  const res = await ask(
    runs === 1 ? 'This property changed meanwhile' : `Properties of ${runs} runs changed meanwhile`,
    [
      {
        label: 'Keep',
        value: 'theirs',
        options: [
          { value: 'theirs', label: 'Theirs' },
          { value: 'mine', label: 'Mine' },
        ],
      },
    ],
    {
      message: `Someone saved after you started editing. ${lines.join('; ')}.`,
      confirm: 'Continue',
    },
  );
  return res?.[0] === 'mine';
}
