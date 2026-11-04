/** One shared EventSource for live updates from the server. */
type Handler = (changed: string[]) => void;
const handlers = { runs: new Set<Handler>(), data: new Set<Handler>(), directions: new Set<Handler>() };
let source: EventSource | null = null;

function connect() {
  if (source) return;
  source = new EventSource('/api/stream');
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
