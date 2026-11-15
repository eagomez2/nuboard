/** One shared EventSource for live updates from the server. */
type Handler = (changed: string[]) => void;
const handlers = { runs: new Set<Handler>(), data: new Set<Handler>(), directions: new Set<Handler>() };
let source: EventSource | null = null;
// what the tab last saw: the server process (its catalog version restarts with it) and version
let seen: string | null = null;

/** In `changed`: anything may have changed (the tab was disconnected and missed events). */
export const EVERYTHING = '*';

function connect() {
  if (source) return;
  source = new EventSource('/api/stream');
  // Each (re)connection starts with `hello`. Another server, or a catalog version other
  // than the last one seen, means events were missed while disconnected (the viewer
  // restarted, or the laptop slept), so every listener catches up once.
  source.addEventListener('hello', (ev) => {
    const { version, server } = JSON.parse((ev as MessageEvent).data);
    const before = seen;
    seen = `${server}:${version}`;
    if (before !== null && before !== seen) {
      handlers.runs.forEach((h) => h([EVERYTHING]));
      handlers.data.forEach((h) => h([EVERYTHING]));
    }
  });
  for (const kind of ['runs', 'data', 'directions'] as const) {
    source.addEventListener(kind, (ev) => {
      const { changed, version } = JSON.parse((ev as MessageEvent).data);
      // a change seen live is not one to catch up on after a reconnect
      if (kind === 'runs' && version !== undefined && seen !== null) seen = `${seen.split(':')[0]}:${version}`;
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
