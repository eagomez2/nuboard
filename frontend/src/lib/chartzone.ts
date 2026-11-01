// The zone of a time axis or read-out shared by several runs (see `timeZone.shared`).
import type { ChartData } from './api';
import { app } from './state.svelte';
import { timeZone, type SharedZone } from './timezone.svelte';

/** The zone for times shared by the runs with these keys. */
export function zoneForKeys(keys: Iterable<string>): SharedZone {
  return timeZone.shared([...new Set(keys)].map((k) => app.runByKey(k)));
}

/** The zone for a chart's wall-time axis: that of the runs it draws. */
export function chartZone(data: ChartData | null | undefined): SharedZone {
  return zoneForKeys((data?.series ?? []).flatMap((s) => s.runs));
}
