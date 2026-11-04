import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('../src/lib/state.svelte', () => ({ app: { info: null } }));
vi.mock('../src/lib/api', () => ({
  DirectionConflict: class extends Error {
    constructor(public current: string | null) {
      super('changed');
    }
  },
  api: {
    directions: async () => ({
      directions: { 'asr-v1': { wer: 'min', score: 'max' }, 'asr-v2': { wer: 'max', score: 'max' } },
    }),
    saveDirection: async (_p: string, name: string, direction: string | null) =>
      direction ? { [name]: direction } : {},
  },
}));

const { directionArrow, directionHint, directionOf, loadDirections, setDirection } =
  await import('../src/lib/directions.svelte');

describe('which way is better, per project', () => {
  beforeAll(() => loadDirections());

  it('uses the direction a project set, else a guess from the name', () => {
    expect(directionOf(['asr-v1'], 'wer')).toEqual({ direction: 'min', set: true, mixed: null });
    expect(directionOf(['asr-v1'], 'train/loss')).toEqual({ direction: 'min', set: false, mixed: null });
    expect(directionOf(['asr-v1'], 'val/acc')).toEqual({ direction: 'max', set: false, mixed: null });
    // tables never guess
    expect(directionOf(['asr-v1'], 'train/loss', false).direction).toBeNull();
  });

  it('agrees across projects that say the same, and is mixed when they disagree', () => {
    expect(directionOf(['asr-v1', 'asr-v2'], 'score').direction).toBe('max');
    const wer = directionOf(['asr-v1', 'asr-v2'], 'wer');
    expect(wer.direction).toBeNull();
    expect(wer.mixed).toEqual([
      { project: 'asr-v1', direction: 'min' },
      { project: 'asr-v2', direction: 'max' },
    ]);
    expect(directionArrow(wer)).toBe('↕');
    expect(directionHint('wer', wer, null)).toContain('↓ in asr-v1, ↑ in asr-v2');
    // a view's own choice decides, and the disagreement is still known
    const picked = directionOf(['asr-v1', 'asr-v2'], 'wer', true, 'max');
    expect(picked.direction).toBe('max');
    expect(picked.mixed).not.toBeNull();
  });

  it('saves a direction in one project only', async () => {
    await setDirection('asr-v2', 'wer', 'min', 'max');
    expect(directionOf(['asr-v1', 'asr-v2'], 'wer').direction).toBe('min');
    // the server's reply is what the project holds now
    expect(directionOf(['asr-v2'], 'score').set).toBe(false);
  });
});
