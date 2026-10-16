import type { FieldType, FieldValue } from './api';

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
