import { describe, expect, it } from 'vitest';
import {
  SIZE,
  bestRun,
  cardValue,
  edges,
  isFolded,
  layout,
  newHypothesis,
  outcomeOf,
  parents,
  related,
  timeline,
  verdictOf,
  visibleRuns,
  type Board,
  type BoardRun,
  type HRun,
  type Hypothesis,
  type ViewOptions,
} from '../src/lib/hypotheses';

const board: Board = {
  title: '',
  description: '',
  verdicts: [
    { id: 'supported', label: 'Supported', color: 's4', icon: 'check' },
    { id: 'open', label: 'Open', color: 'gray', icon: 'circle' },
  ],
  outcomes: [
    { id: 'continued', label: 'Continued', color: 's4', dead_end: false },
    { id: 'open', label: 'Open', color: 'gray', dead_end: false },
    { id: 'dropped', label: 'Dropped', color: 's6', dead_end: true },
  ],
  card: { metric: 'loss', stat: 'best', higher: false },
};

const r = (id: string, extra: Partial<HRun> = {}): HRun => ({
  id,
  outcome: 'open',
  conclusion: '',
  star: false,
  ...extra,
});
const run = (id: string, loss: number, started = 0): BoardRun => ({
  key: `p/${id}`,
  id,
  name: id,
  status: 'finished',
  created: started,
  started,
  summary: { loss: { last: loss, min: loss, max: loss, count: 1 } as never },
  config: {},
});
const h = (id: string, runs: HRun[], parent: string | null = null, extra: Partial<Hypothesis> = {}) =>
  newHypothesis({ id, title: id, runs, parent_run: parent, created: 0, ...extra });
const opts = (runs: Record<string, BoardRun>, extra: Partial<ViewOptions> = {}): ViewOptions => ({
  board,
  runs,
  hideDeadEnds: false,
  starredOnly: false,
  ...extra,
});

describe('hypotheses', () => {
  it('falls back to open for unknown categories', () => {
    expect(verdictOf(board, 'gone').id).toBe('open');
    expect(outcomeOf(board, 'gone').id).toBe('open');
    expect(verdictOf({ ...board, verdicts: [board.verdicts[0]] }, 'gone').id).toBe('supported');
  });

  it('treats loops and unknown parents as starting points', () => {
    const hyps = [h('a', [r('1')], '2'), h('b', [r('2')], '1'), h('c', [r('3')], 'missing'), h('d', [r('4')], '4')];
    const par = parents(hyps);
    expect(par.get('a')).toBeNull();
    expect(par.get('b')).toBeNull();
    expect(par.get('c')).toBeNull();
    expect(par.get('d')).toBeNull();
    // the layout still places every card and draws no arrow
    const placed = layout(hyps, opts({}));
    expect(placed).toHaveLength(4);
    expect(edges(placed, hyps)).toHaveLength(0);
  });

  it('lays children one column right, with an arrow from the parent run', () => {
    const hyps = [h('root', [r('1'), r('2')]), h('kid', [r('3')], '2', { reason: 'why' })];
    const runs = { '1': run('1', 1), '2': run('2', 0.5), '3': run('3', 0.4) };
    const placed = layout(hyps, opts(runs));
    const kid = placed.find((p) => p.hyp.id === 'kid')!;
    expect(kid.x).toBe(SIZE.pitch);
    const [e] = edges(placed, hyps);
    expect(e.run).toBe('2');
    expect(e.reason).toBe('why');
  });

  it('copes with missing runs', () => {
    const hyps = [h('a', [r('here'), r('gone')])];
    const runs: Record<string, BoardRun> = { here: run('here', 1) };
    expect(cardValue(runs.gone, board.card)).toBeNull();
    expect(bestRun(hyps[0], runs, board.card)).toBe('here');
    expect(cardValue(runs.here, null)).toBeNull();
    const [p] = layout(hyps, opts(runs));
    expect(p.runs.map((x) => x.id)).toEqual(['here', 'gone']);
    const tl = timeline(hyps, opts(runs));
    expect(tl.rows.map((x) => x.run.id)).toEqual(['here', 'gone']); // undated runs go last
  });

  it('folds big cards but keeps the runs that carry the story', () => {
    const ids = ['1', '2', '3', '4', '5', '6', '7'];
    const runs = Object.fromEntries(ids.map((id, i) => [id, run(id, 10 - i)]));
    const big = h('big', ids.map((id) => r(id, { star: id === '2' })).concat(r('gone')));
    const kid = h('kid', [r('k')], '3');
    expect(isFolded(big)).toBe(true);
    expect(isFolded({ ...big, folded: false })).toBe(false);
    const shown = visibleRuns(big, [big, kid], opts(runs)).map((x) => x.id);
    expect(shown.sort()).toEqual(['2', '3', '7', 'gone']); // star, arrow source, best, missing
    const [p] = layout([big, kid], opts(runs));
    expect(p.hidden).toHaveLength(4);
  });

  it('hides dead ends unless asked to show them', () => {
    const hyps = [h('a', [r('1'), r('2', { outcome: 'dropped' })])];
    expect(layout(hyps, opts({}, { hideDeadEnds: true }))[0].runs.map((x) => x.id)).toEqual(['1']);
    const shown = layout(hyps, opts({}, { hideDeadEnds: true, showDeadEnds: new Set(['a']) }));
    expect(shown[0].runs).toHaveLength(2);
  });

  it('keeps only the starred paths', () => {
    const hyps = [h('root', [r('1'), r('2')]), h('kid', [r('3', { star: true })], '1'), h('other', [r('4')], '2')];
    const ids = layout(hyps, opts({}, { starredOnly: true })).map((p) => p.hyp.id);
    expect(ids).toEqual(['root', 'kid']);
    expect([...related(hyps, { run: '3' })].sort()).toEqual(['1', '3', 'kid', 'root']);
  });

  it('adds manual nudges but never goes off the canvas', () => {
    const [p] = layout([h('a', [], null, { position: { dx: -500, dy: 40 } })], opts({}));
    expect(p.x).toBe(0);
    expect(p.y).toBe(40);
  });
});
