import { describe, expect, it } from 'vitest';
import { comboMatches, highlight } from '../src/lib/combo';

const reports = [
  { value: 'notes', label: 'Lab notes', detail: 'notes.md' },
  { value: 'ablation', label: 'Ablation study', detail: 'ablation.md' },
  { value: 'weekly', label: 'Weekly sync', detail: 'weekly.md' },
];

describe('comboMatches', () => {
  it('lists every option for an empty query', () => {
    expect(comboMatches(reports, '  ')).toEqual(reports);
  });
  it('matches title or file name, case-insensitively, keeping the order', () => {
    expect(comboMatches(reports, 'ABL').map((o) => o.value)).toEqual(['ablation']);
    expect(comboMatches(reports, 'note').map((o) => o.value)).toEqual(['notes']);
    expect(comboMatches(reports, 'y').map((o) => o.value)).toEqual(['ablation', 'weekly']);
    expect(comboMatches(reports, 'zzz')).toEqual([]);
  });
});

describe('highlight', () => {
  it('splits every match out, keeping the original case', () => {
    expect(highlight('Lab notes', 'LA')).toEqual([
      { text: 'La', hit: true },
      { text: 'b notes', hit: false },
    ]);
    expect(highlight('abab', 'b')).toEqual([
      { text: 'a', hit: false },
      { text: 'b', hit: true },
      { text: 'a', hit: false },
      { text: 'b', hit: true },
    ]);
    expect(highlight('x', '')).toEqual([{ text: 'x', hit: false }]);
  });
});
