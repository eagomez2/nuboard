// Which statistic of a scalar's history a screen shows: its minimum, maximum or last value.
//
// Each screen that shows one value per run has a Min / Max (and often Last) switch; the scalar's
// direction (lib/directions.svelte.ts) or the guess from its name only picks what the switch starts
// on, and the choice is remembered per screen and scalar.
import { defaultStat, type Extreme } from './format';
import { prefs } from './router.svelte';

export { defaultStat, type Extreme };

export type Stat = Extreme | 'last';

const key = (screen: string) => `stat.${screen}`;

/** The statistic last picked for `metric` on `screen`, or null if none was. */
export function rememberedStat(screen: string, metric: string): Stat | null {
  const v = prefs.get<Record<string, Stat>>(key(screen), {})[metric];
  return v === 'min' || v === 'max' || v === 'last' ? v : null;
}

/** Remember `stat` as the choice for `metric` on `screen`. */
export function rememberStat(screen: string, metric: string, stat: Stat) {
  const all = prefs.get<Record<string, Stat>>(key(screen), {});
  delete all[metric]; // re-added last: the most recent choice
  all[metric] = stat;
  // keep the most recent 200 scalars, so the stored list cannot grow without end
  const entries = Object.entries(all);
  prefs.set(key(screen), Object.fromEntries(entries.slice(Math.max(0, entries.length - 200))));
}

/**
 * The statistic a screen shows for `metric`: the one in the URL (`fromUrl`), else the one last
 * picked there, else `fallback` (the metric's direction, or the guess from its name). `last` only
 * where the screen offers it.
 */
export function statFor(
  screen: string,
  metric: string,
  fromUrl: string,
  allowLast = true,
  fallback: Extreme = defaultStat(metric),
): Stat {
  const ok = (v: string | null): v is Stat => v === 'min' || v === 'max' || (allowLast && v === 'last');
  if (ok(fromUrl)) return fromUrl;
  const kept = rememberedStat(screen, metric);
  return ok(kept) ? kept : fallback;
}

/** Read-out label of a statistic. */
export const statLabel = (s: Stat) => (s === 'min' ? 'Min' : s === 'max' ? 'Max' : 'Last');

/** Forget the statistic picked for `metric` on `screen`, so it is unset again. */
export function forgetStat(screen: string, metric: string) {
  const all = prefs.get<Record<string, Stat>>(key(screen), {});
  if (!(metric in all)) return;
  delete all[metric];
  prefs.set(key(screen), all);
}
