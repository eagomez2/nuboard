/**
 * Hypothesis boards: types and the pure logic behind the Hypotheses page (tree layout, folding,
 * highlighting, timeline lanes). Every function tolerates runs, parents and categories that no
 * longer exist, and parent links that would loop, so a hand-edited board never breaks the page.
 */
import type { MetricSummary } from './api';
import { num } from './api';
import { defaultStat } from './format';

export type CategoryColor = 's1' | 's2' | 's3' | 's4' | 's5' | 's6' | 's7' | 'gray';
export const COLORS: CategoryColor[] = ['s4', 's5', 's1', 's2', 's3', 's6', 's7', 'gray'];
export const ICONS = ['check', 'x', 'circle', 'star', 'question', 'pause'] as const;
export type VerdictIcon = (typeof ICONS)[number];
export const MAX_CATEGORIES = 8;

export interface Verdict {
  id: string;
  label: string;
  color: CategoryColor;
  icon: VerdictIcon;
}

export interface Outcome {
  id: string;
  label: string;
  color: CategoryColor;
  /** Faded and struck through; hidden by "Hide dead ends". */
  dead_end: boolean;
}

/** The number a run chip shows: one metric, summarized. */
export interface CardSetting {
  metric: string;
  stat: 'min' | 'max' | 'last';
  /** Which run of a hypothesis is marked as its top one: the lowest or highest number (= `stat` unless Last). */
  top: 'min' | 'max';
}

/**
 * The chip setting picked in a "Number" menu: `min`, `max` or `last`. Last ranks by the metric's
 * direction in the project (see `cardTop`); `last:min` and `last:max` say which end the card
 * keeps for when the project has none set.
 */
export type CardChoice = 'min' | 'max' | 'last' | 'last:min' | 'last:max';
export const CARD_CHOICES: { value: CardChoice; label: string }[] = [
  { value: 'min', label: 'Min' },
  { value: 'max', label: 'Max' },
  { value: 'last', label: 'Last' },
];
export const cardChoice = (c: CardSetting): CardChoice => c.stat;

/**
 * The setting for `metric` with `choice` (or, without one, what Min / Max guesses for its name).
 * `last` keeps `top` (the metric's current direction) for when the project has none set.
 */
export function cardFor(metric: string, choice: CardChoice | null, top?: 'min' | 'max'): CardSetting {
  const c = choice ?? defaultStat(metric);
  if (c === 'min' || c === 'max') return { metric, stat: c, top: c };
  const end = c === 'last:min' ? 'min' : c === 'last:max' ? 'max' : (top ?? defaultStat(metric));
  return { metric, stat: 'last', top: end };
}

export interface Board {
  title: string;
  description: string;
  verdicts: Verdict[];
  outcomes: Outcome[];
  card: CardSetting | null;
  /** The metrics the run panel lists, in order; empty for the default choice (see `panelMetrics`). */
  panel_metrics: string[];
  /** How wide cards are, unless a card sets its own `width`. */
  card_width: CardWidth;
}

/** Card widths: M is the width cards always had. */
export type CardWidth = 's' | 'm' | 'l' | 'xl';
export const CARD_WIDTHS: { value: CardWidth; label: string; px: number }[] = [
  { value: 's', label: 'S', px: 220 },
  { value: 'm', label: 'M', px: 260 },
  { value: 'l', label: 'L', px: 340 },
  { value: 'xl', label: 'XL', px: 420 },
];
/** A card's width in pixels: its own size, else the board's, else M. */
export function cardWidth(h: Pick<Hypothesis, 'width'>, board?: Pick<Board, 'card_width'>): number {
  const w = h.width ?? board?.card_width ?? 'm';
  return (CARD_WIDTHS.find((c) => c.value === w) ?? CARD_WIDTHS[1]).px;
}

export interface HRun {
  id: string;
  outcome: string;
  conclusion: string;
  star: boolean;
}

export interface Hypothesis {
  id: string;
  title: string;
  note: string;
  parent_run: string | null;
  reason: string;
  show_reason: boolean;
  also: { run: string; reason: string }[];
  runs: HRun[];
  verdict: string;
  star: boolean;
  reports: string[];
  position: { dx: number; dy: number };
  folded: boolean | null;
  card: CardSetting | null;
  /** This card's width; null follows the board's `card_width`. */
  width: CardWidth | null;
  created: number;
  updated: number;
}

/** A run the board mentions, as the server found it; runs that are gone are absent. */
export interface BoardRun {
  key: string;
  id: string;
  name: string;
  status: string;
  created: number | null;
  started: number | null;
  summary: Record<string, MetricSummary>;
  config: Record<string, unknown>;
}

/** A board of a project, as listed. */
export interface BoardInfo {
  name: string;
  title: string;
  /** Number of hypotheses. */
  count: number;
}

/** A board in the list of every project's boards. */
export interface BoardListItem extends BoardInfo {
  project: string;
}

export interface BoardData {
  project: string;
  /** The board's name (its folder). */
  name: string;
  boards: BoardInfo[];
  board: Board;
  hypotheses: Hypothesis[];
  runs: Record<string, BoardRun>;
  reports: string[];
  read_only: boolean;
}

export const colorVar = (c: string): string => (c === 'gray' ? 'var(--faint)' : `var(--${c})`);

/** The verdict category of an id, falling back to "open", then to the first category. */
export function verdictOf(board: Board, id: string): Verdict {
  return board.verdicts.find((v) => v.id === id) ?? board.verdicts.find((v) => v.id === 'open') ?? board.verdicts[0];
}

/** The outcome category of an id, falling back to "open", then to the first category. */
export function outcomeOf(board: Board, id: string): Outcome {
  return board.outcomes.find((o) => o.id === id) ?? board.outcomes.find((o) => o.id === 'open') ?? board.outcomes[0];
}

/** Map each run id to the hypothesis that lists it. */
export function ownerOf(hyps: Hypothesis[]): Map<string, Hypothesis> {
  const out = new Map<string, Hypothesis>();
  for (const h of hyps) for (const r of h.runs) if (!out.has(r.id)) out.set(r.id, h);
  return out;
}

/**
 * The parent hypothesis of each hypothesis (the one listing its `parent_run`), or null for a
 * starting point. A parent that is unknown, the hypothesis itself, or part of a loop counts as none.
 */
export function parents(hyps: Hypothesis[]): Map<string, Hypothesis | null> {
  const owner = ownerOf(hyps);
  const raw = new Map<string, Hypothesis | null>();
  for (const h of hyps) {
    const p = h.parent_run ? owner.get(h.parent_run) : undefined;
    raw.set(h.id, p && p.id !== h.id ? p : null);
  }
  const out = new Map<string, Hypothesis | null>();
  for (const h of hyps) {
    const seen = new Set([h.id]);
    let p = raw.get(h.id) ?? null;
    let loops = false;
    while (p) {
      if (seen.has(p.id)) {
        loops = true;
        break;
      }
      seen.add(p.id);
      p = raw.get(p.id) ?? null;
    }
    out.set(h.id, loops ? null : (raw.get(h.id) ?? null));
  }
  return out;
}

/** How many metrics the run panel lists when none are chosen. */
export const PANEL_DEFAULT = 12;

/**
 * The metrics the run panel (and a chip's tooltip) lists for a run: the board's choice when it has
 * one, in its order, even those the run lacks; else the card's metric first, then the run's other
 * metrics in the order it logged them, leaving out system metrics and timers.
 */
export function panelMetrics(
  board: Pick<Board, 'panel_metrics' | 'card'>,
  summary: Record<string, unknown> | undefined,
  card: CardSetting | null = board.card,
  prefixes: { system: string; timing: string } = { system: 'system', timing: 'timing' },
): string[] {
  if (board.panel_metrics?.length) return board.panel_metrics;
  const skip = [prefixes.system, prefixes.timing].filter(Boolean).map((p) => `${p}/`);
  const names = Object.keys(summary ?? {}).filter((m) => !skip.some((p) => m.startsWith(p)));
  const first = card && summary && card.metric in summary ? [card.metric] : [];
  return [...first, ...names.filter((m) => m !== card?.metric)].slice(0, PANEL_DEFAULT);
}

/** A run's value for the chip number, or null when the run, metric or value is missing. */
export function cardValue(run: BoardRun | undefined, card: CardSetting | null): number | null {
  if (!run || !card) return null;
  const s = run.summary?.[card.metric];
  if (!s) return null;
  const v = card.stat === 'last' ? num(s.last) : card.stat === 'min' ? s.min : s.max;
  return v === null || v === undefined || !Number.isFinite(v) ? null : v;
}

/**
 * Which end is the top for a card: Min and Max their own end; Last the direction set for the
 * metric in the project (`dirOf`, read live, so the card follows a change), else the one the card
 * was saved with.
 */
export function cardTop(card: CardSetting, dirOf?: (metric: string) => 'min' | 'max' | null): 'min' | 'max' {
  if (card.stat !== 'last') return card.stat;
  return dirOf?.(card.metric) ?? card.top;
}

/** The id of the run with the top chip number in a hypothesis (lowest or highest, see `cardTop`), or null. */
export function bestRun(
  h: Hypothesis,
  runs: Record<string, BoardRun>,
  card: CardSetting | null,
  dirOf?: (metric: string) => 'min' | 'max' | null,
): string | null {
  if (!card) return null;
  let best: string | null = null;
  let bv = 0;
  const top = cardTop(card, dirOf);
  const better = (a: number, b: number) => (top === 'max' ? a > b : a < b);
  for (const r of h.runs) {
    const v = cardValue(runs[r.id], card);
    if (v !== null && (best === null || better(v, bv))) {
      best = r.id;
      bv = v;
    }
  }
  return best;
}

export interface ViewOptions {
  board: Board;
  runs: Record<string, BoardRun>;
  /** Hide runs whose outcome is a dead end (unless the hypothesis is in `showDeadEnds`). */
  hideDeadEnds: boolean;
  showDeadEnds?: Set<string>;
  /** Keep only starred items and the paths through them. */
  starredOnly: boolean;
  /** The selected run, kept visible when its hypothesis is folded. */
  selectedRun?: string | null;
  /** The direction set for a metric in the project, which cards set to Last rank by. */
  dirOf?: (metric: string) => 'min' | 'max' | null;
}

/** Hypotheses with more runs than this start folded. */
export const FOLD_AT = 5;

export const isFolded = (h: Hypothesis): boolean => h.folded ?? h.runs.length > FOLD_AT;

/** Ids of everything on the path through a run or hypothesis: its ancestors and descendants. */
export function related(hyps: Hypothesis[], target: { run?: string; hyp?: string }): Set<string> {
  const owner = ownerOf(hyps);
  const par = parents(hyps);
  const byParentRun = new Map<string, Hypothesis[]>();
  for (const h of hyps) {
    if (h.parent_run && par.get(h.id)) byParentRun.set(h.parent_run, [...(byParentRun.get(h.parent_run) ?? []), h]);
  }
  const set = new Set<string>();
  const up = (h: Hypothesis) => {
    while (!set.has(h.id)) {
      set.add(h.id);
      const p = par.get(h.id);
      if (!p || !h.parent_run) break;
      set.add(h.parent_run);
      h = p;
    }
  };
  const down = (runId: string) => {
    for (const k of byParentRun.get(runId) ?? []) {
      if (set.has(k.id)) continue;
      set.add(k.id);
      for (const r of k.runs) {
        set.add(r.id);
        down(r.id);
      }
    }
  };
  if (target.run) {
    set.add(target.run);
    const h = owner.get(target.run);
    if (h) up(h);
    down(target.run);
  } else if (target.hyp) {
    const h = hyps.find((x) => x.id === target.hyp);
    if (h) {
      up(h);
      for (const r of h.runs) {
        set.add(r.id);
        down(r.id);
      }
    }
  }
  return set;
}

/** Ids on the paths through every starred run and hypothesis. */
export function starredPaths(hyps: Hypothesis[]): Set<string> {
  const out = new Set<string>();
  for (const h of hyps) {
    if (h.star) for (const id of related(hyps, { hyp: h.id })) out.add(id);
    for (const r of h.runs) if (r.star) for (const id of related(hyps, { run: r.id })) out.add(id);
  }
  return out;
}

/** The runs of a hypothesis after the dead-end and starred filters, before folding. */
export function filteredRuns(h: Hypothesis, o: ViewOptions, starred?: Set<string>): HRun[] {
  return h.runs.filter(
    (r) =>
      !(o.hideDeadEnds && outcomeOf(o.board, r.outcome)?.dead_end && !o.showDeadEnds?.has(h.id)) &&
      !(o.starredOnly && starred && !starred.has(r.id)),
  );
}

/**
 * The runs a card shows. A folded card keeps the runs that carry the story: starred, best,
 * running, missing, selected, and any run an arrow starts from.
 */
export function visibleRuns(h: Hypothesis, hyps: Hypothesis[], o: ViewOptions, starred?: Set<string>): HRun[] {
  const base = filteredRuns(h, o, starred);
  if (!isFolded(h)) return base;
  const best = bestRun(h, o.runs, h.card ?? o.board.card, o.dirOf);
  const linked = new Set(hyps.flatMap((k) => [k.parent_run, ...k.also.map((a) => a.run)]).filter(Boolean));
  return base.filter(
    (r) =>
      r.star ||
      r.id === best ||
      r.id === o.selectedRun ||
      linked.has(r.id) ||
      !o.runs[r.id] ||
      o.runs[r.id].status === 'running',
  );
}

export interface Size {
  head: number;
  row: number;
  foot: number;
  width: number;
  pitch: number;
  gap: number;
}

export const SIZE: Size = { head: 60, row: 34, foot: 26, width: 260, pitch: 380, gap: 30 };

export interface Placed {
  hyp: Hypothesis;
  x: number;
  y: number;
  height: number;
  runs: HRun[];
  /** Runs hidden by folding or filters, shown as a footer. */
  hidden: HRun[];
  depth: number;
  /** The card's width in pixels (see `cardWidth`). */
  width: number;
}

/**
 * Lay the hypotheses out left to right: starting points in the first column, each follow-up one
 * column right of its parent, below its earlier siblings. Manual nudges (`position`) are added
 * on top. In starred-only mode, hypotheses with nothing on a starred path are left out.
 */
export function layout(hyps: Hypothesis[], o: ViewOptions, size: Size = SIZE): Placed[] {
  const starred = o.starredOnly ? starredPaths(hyps) : undefined;
  const par = parents(hyps);
  const kids = new Map<string, Hypothesis[]>();
  for (const h of hyps) {
    const p = par.get(h.id);
    if (p) kids.set(p.id, [...(kids.get(p.id) ?? []), h]);
  }
  const shown = (h: Hypothesis) => !starred || starred.has(h.id);
  const out: Placed[] = [];
  const place = (h: Hypothesis, depth: number, y: number): number => {
    const runs = visibleRuns(h, hyps, o, starred);
    const all = filteredRuns(h, o, starred);
    const deadHidden = h.runs.filter(
      (r) => o.hideDeadEnds && outcomeOf(o.board, r.outcome)?.dead_end && !o.showDeadEnds?.has(h.id),
    );
    const hidden = [...all.filter((r) => !runs.includes(r)), ...deadHidden];
    const height = size.head + runs.length * size.row + (hidden.length ? size.foot : 0) + 8;
    const p: Placed = { hyp: h, x: 0, y, height, runs, hidden, depth, width: cardWidth(h, o.board) };
    out.push(p);
    // children follow the order of the run they come from, then creation
    const order = new Map(runs.map((r, i) => [r.id, i]));
    const children = (kids.get(h.id) ?? [])
      .filter(shown)
      .filter((k) => order.has(k.parent_run ?? ''))
      .sort((a, b) => order.get(a.parent_run!)! - order.get(b.parent_run!)! || a.created - b.created);
    let cy = y;
    for (const k of children) cy += place(k, depth + 1, cy) + size.gap;
    return Math.max(height, cy - y - (children.length ? size.gap : 0));
  };
  let y = 0;
  for (const h of hyps) if (!par.get(h.id) && shown(h)) y += place(h, 0, y) + size.gap * 2;
  // each column is as wide as its widest card; the next starts the same gap after it, so arrows
  // keep an even length whatever the sizes (with every card M, columns are `pitch` apart)
  const colW: number[] = [];
  for (const p of out) colW[p.depth] = Math.max(colW[p.depth] ?? 0, p.width);
  const colX = [0];
  for (let d = 1; d < colW.length; d++) colX[d] = colX[d - 1] + (colW[d - 1] ?? size.width) + size.pitch - size.width;
  for (const p of out) {
    p.x = Math.max(0, colX[p.depth] + (p.hyp.position?.dx ?? 0));
    p.y = Math.max(0, p.y + (p.hyp.position?.dy ?? 0));
  }
  return out;
}

/** The vertical center of a run's chip in a placed card, or of the card's header if not shown. */
export function chipY(p: Placed, runId: string, size: Size = SIZE): number {
  const i = p.runs.findIndex((r) => r.id === runId);
  return i < 0 ? p.y + size.head / 2 : p.y + size.head + i * size.row + size.row / 2;
}

export interface Edge {
  from: Placed;
  to: Placed;
  run: string;
  reason: string;
  showReason: boolean;
  also: boolean;
  /** Index in `to.hyp.also`, for dashed links. */
  index: number;
}

/** The arrows between placed cards: each card's parent link, then its "also informed by" links. */
export function edges(placed: Placed[], hyps: Hypothesis[]): Edge[] {
  const owner = ownerOf(hyps);
  const at = new Map(placed.map((p) => [p.hyp.id, p]));
  const par = parents(hyps);
  const out: Edge[] = [];
  for (const to of placed) {
    const h = to.hyp;
    const p = par.get(h.id);
    const from = p && at.get(p.id);
    if (from && h.parent_run && from.runs.some((r) => r.id === h.parent_run)) {
      out.push({ from, to, run: h.parent_run, reason: h.reason, showReason: h.show_reason, also: false, index: -1 });
    }
    h.also.forEach((a, index) => {
      const o = owner.get(a.run);
      const f = o && o.id !== h.id ? at.get(o.id) : undefined;
      if (f && f.runs.some((r) => r.id === a.run)) {
        out.push({ from: f, to, run: a.run, reason: a.reason, showReason: true, also: true, index });
      }
    });
  }
  return out;
}

export interface Lane {
  hyp: Hypothesis;
  lane: number;
  first: number;
  last: number;
}

/** Timeline rows (runs in date order) and one lane per hypothesis, in order of first run. */
export function timeline(
  hyps: Hypothesis[],
  o: ViewOptions,
): { rows: { run: HRun; hyp: Hypothesis; time: number | null }[]; lanes: Lane[] } {
  const starred = o.starredOnly ? starredPaths(hyps) : undefined;
  const rows = hyps
    .filter((h) => !starred || starred.has(h.id))
    .flatMap((h) =>
      filteredRuns(h, o, starred).map((run) => {
        const r = o.runs[run.id];
        return { run, hyp: h, time: r?.started ?? r?.created ?? null };
      }),
    )
    .sort((a, b) => (a.time ?? Infinity) - (b.time ?? Infinity) || a.run.id.localeCompare(b.run.id));
  const lanes: Lane[] = [];
  rows.forEach((row, i) => {
    const l = lanes.find((x) => x.hyp.id === row.hyp.id);
    if (l) l.last = i;
    else lanes.push({ hyp: row.hyp, lane: lanes.length, first: i, last: i });
  });
  return { rows, lanes };
}

/** A new hypothesis with defaults, for the "follow up" and "new hypothesis" forms. */
export function newHypothesis(fields: Partial<Hypothesis>): Hypothesis {
  const now = Date.now() / 1000;
  return {
    id: '',
    title: 'Untitled hypothesis',
    note: '',
    parent_run: null,
    reason: '',
    show_reason: true,
    also: [],
    runs: [],
    verdict: 'open',
    star: false,
    reports: [],
    position: { dx: 0, dy: 0 },
    folded: null,
    card: null,
    width: null,
    created: now,
    updated: now,
    ...fields,
  };
}
