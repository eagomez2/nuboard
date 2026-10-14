/**
 * Renders one logged figure (Plotly, Vega-Lite or Bokeh) inside a sandboxed
 * iframe. The viewer posts the spec in; this page posts its height back. The
 * renderers are separate chunks, loaded only when a figure of that kind is shown.
 */

type Theme = 'light' | 'dark';
interface Request {
  type: 'render';
  mime: string;
  data: string;
  theme: Theme;
}

const root = document.getElementById('root')!;
const post = (msg: object) => parent.postMessage(msg, '*');

function message(text: string) {
  root.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'msg';
  div.textContent = text;
  root.append(div);
}

async function plotly(spec: { data?: unknown[]; layout?: Record<string, unknown> }, theme: Theme) {
  const Plotly = (await import('plotly.js-dist-min')).default;
  const dark = theme === 'dark';
  const layout = {
    ...(spec.layout ?? {}),
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: dark ? 'rgba(0,0,0,0)' : (spec.layout?.plot_bgcolor ?? undefined),
    font: { ...((spec.layout?.font as object) ?? {}), color: dark ? '#e8ecf2' : undefined },
  };
  if (dark) {
    // Plotly's default grid is near-white; soften it on dark backgrounds.
    const keys = Object.keys(layout).filter((k) => /^[xy]axis\d*$/.test(k));
    for (const k of keys.length ? keys : ['xaxis', 'yaxis']) {
      const axis = (layout as Record<string, unknown>)[k] as Record<string, unknown> | undefined;
      (layout as Record<string, unknown>)[k] = {
        gridcolor: 'rgba(255,255,255,0.1)',
        zerolinecolor: 'rgba(255,255,255,0.2)',
        ...(axis ?? {}),
      };
    }
  }
  root.innerHTML = '';
  root.style.height = `${Number(spec.layout?.height) || 440}px`;
  await Plotly.newPlot(root, spec.data ?? [], layout, { responsive: true, displaylogo: false });
}

async function vegaLite(spec: Record<string, unknown>, theme: Theme) {
  const { default: embed } = await import('vega-embed');
  root.innerHTML = '';
  await embed(root, spec as never, {
    actions: { export: true, source: false, compiled: false, editor: false },
    theme: theme === 'dark' ? 'dark' : undefined,
    config: { background: 'transparent' },
    renderer: 'svg',
  });
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(src));
    document.head.append(s);
  });
}

async function bokeh(item: { version?: string; doc?: { version?: string } }) {
  // BokehJS must match the Python version that wrote the figure, so it comes from
  // Bokeh's CDN for that exact version (the only renderer that needs a network).
  const version = item.version ?? item.doc?.version;
  if (!version) throw new Error('the figure does not say which Bokeh version wrote it');
  const base = `https://cdn.bokeh.org/bokeh/release`;
  try {
    await loadScript(`${base}/bokeh-${version}.min.js`);
  } catch {
    message(
      `Bokeh figures need BokehJS ${version} from cdn.bokeh.org, which could not be reached. Download the spec instead.`,
    );
    return;
  }
  await Promise.allSettled(
    [`${base}/bokeh-widgets-${version}.min.js`, `${base}/bokeh-tables-${version}.min.js`].map(loadScript),
  );
  root.innerHTML = '';
  const Bokeh = (
    window as unknown as { Bokeh: { embed: { embed_item: (i: unknown, id: string) => Promise<unknown> } } }
  ).Bokeh;
  await Bokeh.embed.embed_item(item, 'root');
}

async function render(req: Request) {
  // A frame whose color scheme differs from the page's gets an opaque backdrop.
  document.documentElement.style.colorScheme = req.theme;
  try {
    const spec = JSON.parse(req.data);
    if (req.mime.includes('plotly')) await plotly(spec, req.theme);
    else if (req.mime.includes('vega')) await vegaLite(spec, req.theme);
    else if (req.mime.includes('bokeh')) await bokeh(spec);
    else message(`Unsupported figure type ${req.mime}`);
  } catch (e) {
    message(`Could not render this figure: ${e instanceof Error ? e.message : String(e)}`);
  }
}

new ResizeObserver(() => post({ type: 'height', height: Math.ceil(document.body.scrollHeight) })).observe(
  document.body,
);
window.addEventListener('message', (e) => {
  if (e.source === parent && e.data?.type === 'render') render(e.data as Request);
});
post({ type: 'ready' });
