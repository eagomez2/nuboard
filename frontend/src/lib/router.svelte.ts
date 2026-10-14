/**
 * All view state lives in the URL hash (#/page?key=value), so any view can be
 * bookmarked, shared or saved. Per-viewer preferences go to localStorage instead.
 */

export type Page = 'runs' | 'charts' | 'media';
const PAGES: Page[] = ['runs', 'charts', 'media'];

function parse(): { page: Page; params: URLSearchParams } {
  const hash = location.hash.replace(/^#\/?/, '');
  const [path, query = ''] = hash.split('?');
  const page = (PAGES.includes(path as Page) ? path : 'runs') as Page;
  return { page, params: new URLSearchParams(query) };
}

class Router {
  page = $state<Page>('runs');
  params = $state<Record<string, string>>({});

  constructor() {
    this.read();
    window.addEventListener('hashchange', () => this.read());
  }

  private read() {
    const { page, params } = parse();
    this.page = page;
    this.params = Object.fromEntries(params.entries());
  }

  get(key: string, fallback = ''): string {
    return this.params[key] ?? fallback;
  }

  list(key: string): string[] {
    const v = this.params[key];
    return v ? v.split(',').filter(Boolean) : [];
  }

  /** Merge params into the URL. `null` removes a key. `push` adds a history entry. */
  set(
    update: Record<string, string | number | boolean | null | undefined>,
    opts: { page?: Page; push?: boolean } = {},
  ) {
    const next = { ...this.params };
    for (const [k, v] of Object.entries(update)) {
      if (v === null || v === undefined || v === '' || v === false) delete next[k];
      else next[k] = String(v);
    }
    const page = opts.page ?? this.page;
    const query = new URLSearchParams(next).toString();
    const hash = `#/${page}${query ? `?${query}` : ''}`;
    if (hash === location.hash) return;
    if (opts.push || page !== this.page) history.pushState(null, '', hash);
    else history.replaceState(null, '', hash);
    this.page = page;
    this.params = next;
  }

  go(page: Page, update: Record<string, string | number | boolean | null | undefined> = {}) {
    this.set(update, { page, push: true });
  }
}

export const router = new Router();

export const prefs = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private mode: preferences just don't persist */
    }
  },
};
