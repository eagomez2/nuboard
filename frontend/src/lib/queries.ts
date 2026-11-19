/**
 * Queries for the query bar: the saved ones (`queries.json` in the workspace folder, shared by
 * every browser on the server) and the ones this browser applied last.
 */

import { prefs } from './router.svelte';

export interface SavedQuery {
  name: string;
  query: string;
}

const RECENT_KEY = 'query.recent';
const RECENT_MAX = 8;

/** The queries applied last in this browser, newest first. */
export function recentQueries(): string[] {
  const got = prefs.get<unknown>(RECENT_KEY, []);
  return Array.isArray(got) ? got.filter((q): q is string => typeof q === 'string' && !!q.trim()) : [];
}

/** Remember an applied query (moved to the front if it was there already). */
export function rememberQuery(query: string) {
  const q = query.trim();
  if (!q) return;
  prefs.set(RECENT_KEY, [q, ...recentQueries().filter((x) => x !== q)].slice(0, RECENT_MAX));
}

/** Forget the recent queries of this browser. */
export function forgetRecent() {
  prefs.set(RECENT_KEY, []);
}
