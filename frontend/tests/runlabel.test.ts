import { describe, expect, it } from 'vitest';
import { idSuffix, pickMatches } from '../src/lib/runlabel';

describe('run picker labels', () => {
  const run = { id: '20261109T1554-103745e1', name: 'baseline', status: 'finished', tags: ['lr-sweep'] };
  it('takes the random part of an id', () => {
    expect(idSuffix(run.id)).toBe('103745e1');
    expect(idSuffix('plain')).toBe('plain');
  });
  it('matches by name, id, status, tag and context', () => {
    expect(pickMatches(run, '')).toBe(true);
    expect(pickMatches(run, 'BASE')).toBe(true);
    expect(pickMatches(run, '3745')).toBe(true);
    expect(pickMatches(run, '#lr')).toBe(true);
    expect(pickMatches(run, 'cutmix', 'Pasting patches (CutMix)')).toBe(true);
    expect(pickMatches(run, 'crashed')).toBe(false);
  });
});
