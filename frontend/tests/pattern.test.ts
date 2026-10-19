import { describe, expect, it } from 'vitest';
import { patternRegex, pinMatches } from '../src/lib/pattern';

describe('pin patterns', () => {
  it('match within a folder, across folders and one character', () => {
    expect(patternRegex('files/*.yaml').test('files/config.yaml')).toBe(true);
    expect(patternRegex('files/*.yaml').test('files/sub/config.yaml')).toBe(false);
    expect(patternRegex('**/*.pth').test('checkpoints/Best/a.pth')).toBe(true);
    expect(patternRegex('**/*.pth').test('a.pth')).toBe(true);
    expect(patternRegex('ckpt_?.pt').test('ckpt_1.pt')).toBe(true);
    expect(patternRegex('a.b').test('axb')).toBe(false);
  });

  it('list matches newest first, and exact pins only match themselves', () => {
    const f = (path: string, mtime: number) => ({ path, mtime, size: 1, kind: 'other' as const, internal: false });
    const files = [f('c/best_1.pth', 1), f('c/best_2.pth', 3), f('c/last.pth', 2)];
    expect(pinMatches('c/best_*.pth', files).map((x) => x.path)).toEqual(['c/best_2.pth', 'c/best_1.pth']);
    expect(pinMatches('c/last.pth', files).map((x) => x.path)).toEqual(['c/last.pth']);
  });
});
