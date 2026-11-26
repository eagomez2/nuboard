import { describe, expect, it } from 'vitest';
import { merge3 } from '../src/lib/merge';

const base = '# Report\n\nIntro.\n\n## Results\n\nNumbers.\n';

describe('merge3', () => {
  it('keeps edits made to different parts', () => {
    const mine = base.replace('Intro.', 'A better intro.');
    const theirs = `${base}\n![loss](media:run/loss@10)\n`;
    expect(merge3(base, mine, theirs)).toBe(`${mine}\n![loss](media:run/loss@10)\n`);
  });

  it('takes the only side that changed, and identical changes once', () => {
    const mine = base.replace('Numbers.', 'More numbers.');
    expect(merge3(base, mine, base)).toBe(mine);
    expect(merge3(base, base, mine)).toBe(mine);
    expect(merge3(base, mine, mine)).toBe(mine);
  });

  it('gives up when both changed the same lines', () => {
    expect(merge3(base, base.replace('Intro.', 'Mine.'), base.replace('Intro.', 'Theirs.'))).toBeNull();
  });

  it('merges insertions on both sides around a kept line', () => {
    const o = 'a\nb\nc';
    expect(merge3(o, 'a\nx\nb\nc', 'a\nb\nc\ny')).toBe('a\nx\nb\nc\ny');
    expect(merge3(o, 'b\nc', 'a\nb\nz')).toBe('b\nz');
  });
});
