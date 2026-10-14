import { SvelteSet } from 'svelte/reactivity';
import { api, type Info, type RunBrief, type RunsResponse } from './api';
import { prefs, router } from './router.svelte';

class AppState {
  info = $state<Info | null>(null);
  runs = $state<RunsResponse | null>(null);
  loading = $state(false);
  error = $state<string | null>(null);
  selected = new SvelteSet<string>();
  theme = $state<'light' | 'dark'>('light');
  /** Bumps when CSS variables change so canvases can re-read colors. */
  themeVersion = $state(0);
  private seq = 0;

  constructor() {
    const stored = prefs.get<string | null>('theme', null);
    const system = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    this.theme = stored === 'light' || stored === 'dark' ? stored : system;
    window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!prefs.get('theme', null)) {
        this.theme = e.matches ? 'dark' : 'light';
        this.themeVersion++;
      }
    });
  }

  toggleTheme() {
    this.theme = this.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = this.theme;
    prefs.set('theme', this.theme);
    this.themeVersion++;
  }

  async loadInfo() {
    try {
      this.info = await api.info();
    } catch (e) {
      this.error = String(e);
    }
  }

  async loadRuns() {
    const seq = ++this.seq;
    this.loading = true;
    try {
      const res = await api.runs(router.get('q'), router.get('project') || null);
      if (seq === this.seq) {
        this.runs = res;
        this.error = null;
      }
    } catch (e) {
      if (seq === this.seq) this.error = String(e);
    } finally {
      if (seq === this.seq) this.loading = false;
    }
  }

  runByKey(key: string): RunBrief | undefined {
    return this.runs?.runs.find((r) => r.key === key);
  }

  /** Runs in view: selected ones if any (from the URL), else the query result. */
  visibleRuns(includeArchived = false): RunBrief[] {
    const all = this.runs?.runs ?? [];
    const sel = router.list('sel');
    if (sel.length) {
      const set = new Set(sel);
      return all.filter((r) => set.has(r.key));
    }
    return includeArchived ? all : all.filter((r) => !r.archived);
  }
}

export const app = new AppState();
