import { api, type FieldDef, type FieldType } from './api';
import { ask, type DialogField } from './dialog.svelte';
import { FIELD_TYPES } from './fields';

export const TYPE_LABELS: Record<FieldType, string> = {
  text: 'Text',
  number: 'Number',
  choice: 'Choice (one of a list)',
  tags: 'Tags (several of a list)',
  bool: 'Yes / no',
  date: 'Date',
  link: 'Link',
};

const listText = (names: string[]) =>
  names.length < 3 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;

/**
 * Ask for a new property (name, type, options or unit, description) and save
 * its definition in each of `projects`. `name` and `type` prefill the dialog,
 * as when defining a property that already has values. Null when cancelled.
 */
export async function defineProperty(
  projects: string[],
  { name = '', type = 'text' as FieldType, title = 'Add a property' } = {},
): Promise<FieldDef | null> {
  if (!projects.length) return null;
  const res = await ask(
    title,
    [
      { label: 'Name', value: name, placeholder: 'e.g. dataset, verdict, paper' },
      {
        label: 'Type',
        value: type,
        options: FIELD_TYPES.map((t) => ({ value: t, label: TYPE_LABELS[t] })),
        hint: 'Choice and tags take a list of options; numbers can have a unit.',
      },
      { label: 'Options or unit', placeholder: 'choice/tags: a, b, c · number: unit such as ms' },
      { label: 'Description', placeholder: 'optional' },
    ],
    { confirm: 'Add property', message: `Defined for every run of ${listText(projects)}.` },
  );
  const n = res?.[0].trim().replace(/[,\s]+/g, '_');
  if (!res || !n) return null;
  const t = (FIELD_TYPES.includes(res[1].trim() as FieldType) ? res[1].trim() : 'text') as FieldType;
  const def: FieldDef = { name: n, type: t };
  if (t === 'choice' || t === 'tags')
    def.options = res[2]
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  if (t === 'number' && res[2].trim()) def.unit = res[2].trim();
  if (res[3].trim()) def.description = res[3].trim();
  for (const p of projects) {
    const defs = (await api.fields(p)).fields;
    await api.saveFields(p, [...defs.filter((d) => d.name !== def.name), def]);
  }
  return def;
}

/** A dialog field for typing or picking a value of `def`; an empty value clears it. */
export function valueField(def: FieldDef, current = ''): DialogField {
  const label = def.unit ? `${def.name} (${def.unit})` : def.name;
  const clear = { value: '', label: '— (clear)' };
  if (def.type === 'bool')
    return {
      label,
      value: current,
      options: [{ value: 'true', label: 'yes' }, { value: 'false', label: 'no' }, clear],
    };
  if (def.type === 'choice' && def.options?.length)
    return { label, value: current, options: [...def.options.map((o) => ({ value: o, label: o })), clear] };
  if (def.type === 'tags' && def.options?.length)
    return {
      label,
      value: current,
      multiple: true,
      options: def.options.map((o) => ({ value: o, label: o })),
      hint: 'None picked clears it.',
    };
  return {
    label,
    value: current,
    inputType: def.type === 'date' ? 'date' : def.type === 'link' ? 'url' : undefined,
    placeholder:
      def.type === 'number'
        ? 'e.g. 4'
        : def.type === 'link'
          ? 'https://'
          : def.type === 'tags'
            ? 'comma, separated'
            : 'e.g. keep',
    hint: 'Empty clears it.',
  };
}
