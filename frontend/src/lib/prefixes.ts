import type { RunBrief } from './api';

/**
 * The first segments that runs reserve for their own scalars: timers (`timing/` by
 * default) and system metrics (`system/`). Each run records its own in run.json, so
 * runs that renamed them still sort and format right next to runs that did not.
 */
export function reservedPrefixes(runs: RunBrief[]): { timing: Set<string>; system: Set<string> } {
  const timing = new Set<string>();
  const system = new Set<string>();
  for (const r of runs) {
    timing.add(r.prefixes?.timing ?? 'timing');
    system.add(r.prefixes?.system ?? 'system');
  }
  if (!runs.length) {
    timing.add('timing');
    system.add('system');
  }
  return { timing, system };
}

/** The first segment of a scalar name (`other` when it has none), as the Charts sections group it. */
export const sectionOf = (metric: string): string => (metric.includes('/') ? metric.split('/')[0] : 'other');
