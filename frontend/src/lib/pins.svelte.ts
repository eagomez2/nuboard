// Files pinned as tabs in run details and Compare, per project, shared through
// `<project>/pins.json`. A pin is a path inside a run folder or a pattern.
import { api } from './api';
import { notice } from './dialog.svelte';

class PinState {
  byProject = $state<Record<string, string[]>>({});

  load(project: string) {
    api
      .pins(project)
      .then((r) => (this.byProject[project] = r.pins))
      .catch(() => {});
  }

  /** The pins of these projects, each once, in the order they were added. */
  of(projects: string[]): string[] {
    return [...new Set(projects.flatMap((p) => this.byProject[p] ?? []))];
  }

  async set(projects: string[], pin: string, on: boolean) {
    try {
      for (const p of new Set(projects)) this.byProject[p] = await api.pin(p, on ? { add: pin } : { remove: pin });
    } catch (e) {
      await notice(on ? 'Not pinned' : 'Not unpinned', String(e instanceof Error ? e.message : e));
    }
  }
}

export const pins = new PinState();
