// Which way is better for a scalar or table column, as papers mark it: ↓ lower is better (`min`),
// ↑ higher is better (`max`).
//
// A direction is set per project and kept in `<project>/directions.json`, the only place it is stored:
// every screen reads it from here, live. Clicking an arrow changes only your view (`dir` in the
// URL, or the table's own state); "Save for everyone" is the one way to write it to the project,
// and only when one project is shown. Until one is set, screens that must rank (Sweeps, the Runs
// result column) use a guess from the name, shown as a faint arrow; tables color nothing. A view
// of several projects whose directions disagree is "mixed": ↕, nothing colored as better or
// worse, ranked by the view's own choice once picked.
import { api, DirectionConflict } from './api';
import { app } from './state.svelte';
import { defaultStat, type Extreme } from './format';
import { onLive } from './live';

export type { Extreme };

const store = $state<{ by: Record<string, Record<string, Extreme>>; loaded: boolean }>({ by: {}, loaded: false });
let loading: Promise<void> | null = null;
let listening = false;

/**
 * Load (or with `force`, reload) every project's directions. The server announces every change
 * to a `directions.json` (from any viewer, a merge or a hand edit), and they are read again then.
 */
export function loadDirections(force = false): Promise<void> {
  if (loading && !force) return loading;
  if (!listening && typeof EventSource !== 'undefined') {
    listening = true;
    onLive('directions', () => void loadDirections(true));
  }
  loading = api
    .directions()
    .then((r) => {
      store.by = r.directions;
      store.loaded = true;
    })
    .catch(() => {
      store.loaded = true;
    });
  return loading;
}

export interface Direction {
  /** The direction to use: set, guessed, or null (none set, or mixed). */
  direction: Extreme | null;
  /** True when the listed projects set it (not a guess). */
  set: boolean;
  /** When projects disagree: what each one says. */
  mixed: { project: string; direction: Extreme }[] | null;
}

/**
 * The direction of `name` across `projects`. With `guess`, an unset one falls back to the guess
 * from the name; `override` (a view's own choice, from its URL) wins over everything.
 */
export function directionOf(projects: string[], name: string, guess = true, override?: string | null): Direction {
  if (!store.loaded) void loadDirections();
  const said = projects
    .map((project) => ({ project, direction: store.by[project]?.[name] }))
    .filter((s): s is { project: string; direction: Extreme } => s.direction === 'min' || s.direction === 'max');
  const ends = new Set(said.map((s) => s.direction));
  const mixed = ends.size > 1 ? said : null;
  if (override === 'min' || override === 'max') return { direction: override, set: true, mixed };
  if (mixed) return { direction: null, set: false, mixed };
  if (said.length) return { direction: said[0].direction, set: true, mixed: null };
  return { direction: guess ? defaultStat(name) : null, set: false, mixed: null };
}

/** The name a table column's direction is kept under: never the same as a scalar's. */
export const columnKey = (table: string, column: string) => `${table} › ${column}`;

/** False when the viewer was started with `--read-only-directions`. */
export const canSaveDirections = () => !app.info?.lock_directions;

/**
 * Save the direction of `name` in `project` for everyone (null clears it). `expect` is what this
 * view showed as the project's: if someone changed it meanwhile, nothing is saved, the new value
 * is loaded and a `DirectionConflict` is thrown.
 */
export async function setDirection(project: string, name: string, direction: Extreme | null, expect: Extreme | null) {
  try {
    store.by = { ...store.by, [project]: await api.saveDirection(project, name, direction, expect) };
  } catch (e) {
    if (e instanceof DirectionConflict) await loadDirections(true);
    throw e;
  }
}

/** The arrow for a direction, as in papers; ↕ when projects disagree, ± when there is none. */
export const directionArrow = (g: Direction) =>
  g.mixed && !g.direction ? '↕' : g.direction === 'min' ? '↓' : g.direction === 'max' ? '↑' : '±';

/** Hover text of a direction button; `changed` when the view's own choice differs from the project. */
export function directionHint(name: string, g: Direction, project: string | null, changed = false): string {
  if (g.mixed && !g.direction)
    return `The projects shown disagree on ${name}: ${g.mixed.map((m) => `${m.direction === 'min' ? '↓' : '↑'} in ${m.project}`).join(', ')}. Click to pick a direction for this view only.`;
  if (!g.direction)
    return `No direction set for ${name}. Click to say ↑ higher is better (again for ↓ lower is better).`;
  const better = `${g.direction === 'min' ? '↓ Lower' : '↑ Higher'} is better for ${name}`;
  if (changed)
    return `${better}, in your view only. ${project ? `Save for everyone to keep it in ${project}.` : 'Several projects are shown, so it cannot be saved to one.'}`;
  const how = g.set ? (project ? `, as set in ${project}` : '') : ' (a guess from its name)';
  return `${better}${how}. Click to flip it in your view; nothing is saved until you choose Save for everyone.`;
}
