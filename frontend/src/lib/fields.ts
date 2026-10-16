import type { FieldDef, FieldType, FieldValue } from './api';

export const FIELD_TYPES: readonly FieldType[] = ['text', 'number', 'choice', 'tags', 'bool', 'date', 'link'];

/** A stored value as editable text. */
export function fieldText(v: FieldValue | null | undefined, type: FieldType = 'text'): string {
  if (v === null || v === undefined) return '';
  if (Array.isArray(v)) return v.join(', ');
  if (type === 'bool' && typeof v !== 'boolean')
    return ['true', 'yes', '1'].includes(String(v).toLowerCase()) ? 'true' : 'false';
  return String(v);
}

/** Parse edited text into the value stored for a property of `type` (null clears it). */
export function parseFieldValue(raw: string, type: FieldType = 'text'): FieldValue | null {
  const text = raw.trim();
  if (text === '') return null;
  switch (type) {
    case 'number': {
      const n = Number(text.replace(/_/g, ''));
      return Number.isFinite(n) ? n : text;
    }
    case 'bool':
      return ['true', 'yes', '1', 'y'].includes(text.toLowerCase());
    case 'tags': {
      const tags = [
        ...new Set(
          text
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
        ),
      ];
      return tags.length ? tags : null;
    }
    case 'text':
    case 'choice':
    case 'date':
    case 'link':
      return text;
  }
}

/** Why edited text does not fit a property (null when it does). The server checks the same rules. */
export function fieldProblem(raw: string, def: FieldDef): string | null {
  const text = raw.trim();
  if (text === '') return null;
  const options = def.options ?? [];
  switch (def.type) {
    case 'number':
      return Number.isFinite(Number(text.replace(/_/g, ''))) ? null : `${def.name} needs a number.`;
    case 'date':
      return /^\d{4}-\d{2}-\d{2}$/.test(text) ? null : `${def.name} needs a date (YYYY-MM-DD).`;
    case 'link':
      return /^https?:\/\/\S+$/.test(text) ? null : `${def.name} needs an http:// or https:// address.`;
    case 'choice':
      return !options.length || options.includes(text) ? null : `${def.name} must be one of: ${options.join(', ')}.`;
    case 'tags': {
      const bad = text
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t && options.length && !options.includes(t));
      return bad.length ? `Not an option of ${def.name}: ${bad.join(', ')}.` : null;
    }
    default:
      return null;
  }
}
