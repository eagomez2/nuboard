import { describe, expect, it } from 'vitest';
import { wordDiff } from '../src/lib/diff';

const marked = (parts: { text: string; changed: boolean }[]) =>
  parts.map((p) => (p.changed ? `[${p.text}]` : p.text)).join('');

describe('wordDiff', () => {
  it('marks only the words that changed', () => {
    const [a, b] = wordDiff('the model learns fast', 'the model learns slowly');
    expect(marked(a)).toBe('the model learns [fast]');
    expect(marked(b)).toBe('the model learns [slowly]');
  });

  it('keeps the text of each side whole', () => {
    const before = 'Step 20000: shards the model  predict';
    const after = 'Step 25000: down the model predict now';
    const [a, b] = wordDiff(before, after);
    expect(a.map((p) => p.text).join('')).toBe(before);
    expect(b.map((p) => p.text).join('')).toBe(after);
  });

  it('marks nothing for equal lines and everything for disjoint ones', () => {
    expect(wordDiff('same words', 'same words')[1].every((p) => !p.changed)).toBe(true);
    const [a, b] = wordDiff('alpha beta', 'gamma delta');
    expect(marked(a)).toBe('[alpha] [beta]');
    expect(marked(b)).toBe('[gamma] [delta]');
  });
});
