/** One shared EventSource for live updates from the server. */
type Handler = (changed: string[]) => void;
const handlers = { runs: new Set<Handler>(), data: new Set<Handler>(), directions: new Set<Handler>() };
let source: EventSource | null = null;
let version: number | null = null;

/** In `changed`: anything may have changed (the tab was disconnected and missed events). */
export const EVERYTHING = '*';

function connect() {
  if (source) return;
  source = new EventSource('/api/stream');
  // Each (re)connection starts with `hello`. A catalog version other than the last one
  // seen means events were missed while disconnected (the viewer restarted, or the
  // laptop slept), so every listener catches up once.
  source.addEventListener('hello', (ev) => {
    const seen = version;
    version = JSON.parse((ev as MessageEvent).data).version;
    if (seen !== null && seen !== version) {
      handlers.runs.forEach((h) => h([EVERYTHING]));
      handlers.data.forEach((h) => h([EVERYTHING]));
    }
  });
  for (const kind of ['runs', 'data', 'directions'] as const) {
    source.addEventListener(kind, (ev) => {
      const { changed } = JSON.parse((ev as MessageEvent).data);
      handlers[kind].forEach((h) => h(changed));
    });
  }
}

/** `directions`: a project's `directions.json` changed (lib/directions.svelte.ts reloads them). */
export function onLive(kind: 'runs' | 'data' | 'directions', h: Handler): () => void {
  connect();
  handlers[kind].add(h);
  return () => handlers[kind].delete(h);
}
