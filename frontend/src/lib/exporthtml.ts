// Export a report as one self-contained HTML file that needs no network: images, audio and chart
// snapshots inlined as data URLs, logged text and HTML inlined, and interactive figures drawn from
// their spec by the Plotly or Vega libraries embedded once in the file (only those it uses).

import { api, type MediaItem } from './api';
import { renderMarkdown } from './markdown';

type Lib = 'plotly' | 'vega' | 'bokeh';

// The UMD builds the viewer already ships, loaded as text only when a report is exported.
const VENDOR: Record<'plotly' | 'vega', () => Promise<string[]>> = {
  plotly: async () => [(await import('../../node_modules/plotly.js-dist-min/plotly.min.js?raw')).default],
  vega: async () =>
    Promise.all([
      import('../../node_modules/vega/build/vega.min.js?raw').then((m) => m.default),
      import('../../node_modules/vega-lite/build/vega-lite.min.js?raw').then((m) => m.default),
      import('../../node_modules/vega-embed/build/vega-embed.min.js?raw').then((m) => m.default),
    ]),
};

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

/** Script text that cannot end or confuse the `<script>` element holding it. */
const scriptSafe = (js: string) => js.replace(/<\/(script)/gi, '<\\/$1').replace(/<!--/g, '<\\!--');

async function dataUrl(url: string): Promise<string> {
  const blob = await (await fetch(url)).blob();
  return new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => fail(r.error);
    r.readAsDataURL(blob);
  });
}

/** A sandboxed frame with its own document, sized by `height`. */
function frame(doc: string, title: string, height: number): string {
  return `<iframe class="frame" title="${esc(title)}" sandbox="allow-scripts" style="height:${height}px" srcdoc="${esc(doc)}"></iframe>`;
}

/** What one export needs: the figure libraries used, and the BokehJS version if any. */
interface Needs {
  libs: Set<Lib>;
  bokeh?: string;
}

/** A placeholder drawn by the script at the end of the file, with its spec next to it. */
function figureHtml(mime: string, json: string, needs: Needs): string {
  const lib: Lib | null = mime.includes('plotly')
    ? 'plotly'
    : mime.includes('vega')
      ? 'vega'
      : mime.includes('bokeh')
        ? 'bokeh'
        : null;
  if (!lib) return `<p class="missing">Unsupported figure type ${esc(mime)}</p>`;
  let spec: { layout?: { height?: number }; version?: string; doc?: { version?: string } };
  try {
    spec = JSON.parse(json);
  } catch {
    return `<p class="missing">This figure's spec could not be read</p>`;
  }
  if (lib === 'bokeh') {
    const v = spec.version ?? spec.doc?.version;
    if (!v || (needs.bokeh && needs.bokeh !== v))
      return `<p class="missing">Bokeh figures of more than one version cannot share a file; this one was left out</p>`;
    needs.bokeh = v;
  }
  needs.libs.add(lib);
  const height = lib === 'plotly' ? Number(spec.layout?.height) || 440 : 0;
  const style = height ? ` style="height:${height}px"` : '';
  return `<div class="nbfig" data-lib="${lib}"${style}></div><script type="application/json">${json.replace(/</g, '\\u003c')}</script>`;
}

/** BokehJS must match the version that wrote the figure; it is fetched once, when exporting. */
async function bokehScripts(version: string): Promise<string[] | null> {
  const base = `https://cdn.bokeh.org/bokeh/release/bokeh-${version}.min.js`;
  try {
    const res = await fetch(base);
    if (!res.ok) return null;
    return [await res.text()];
  } catch {
    return null;
  }
}

const DRAW = `for (const el of document.querySelectorAll('.nbfig')) {
  try {
    const spec = JSON.parse(el.nextElementSibling.textContent);
    const lib = el.dataset.lib;
    if (lib === 'plotly') Plotly.newPlot(el, spec.data || [], spec.layout || {}, { responsive: true, displaylogo: false });
    else if (lib === 'vega') vegaEmbed(el, spec, { actions: false, renderer: 'svg' });
    else if (lib === 'bokeh' && window.Bokeh) { el.id = el.id || 'nbfig' + Math.random().toString(36).slice(2); Bokeh.embed.embed_item(spec, el.id); }
    else el.textContent = 'This figure could not be drawn because its library is not in the file.';
  } catch (e) {
    el.textContent = 'This figure could not be drawn: ' + e;
  }
}`;

async function mediaHtml(project: string, ref: string, caption: string, needs: Needs): Promise<string> {
  let found: { run: string; run_name: string; item: MediaItem };
  try {
    found = await api.mediaRef(project, ref);
  } catch {
    return `<p class="missing">Missing item: ${esc(decodeURIComponent(ref))}</p>`;
  }
  const { item } = found;
  const url = item.index === undefined ? '' : api.mediaUrl(found.run, item.index);
  const meta = `${found.run_name} · ${item.key} · step ${item.step}`;
  let body: string;
  if (item.kind === 'text') body = `<pre>${esc(item.text ?? '')}</pre>`;
  else if (item.mime.startsWith('image/')) body = `<img src="${await dataUrl(url)}" alt="${esc(caption)}">`;
  else if (item.kind === 'audio' || item.mime.startsWith('audio/'))
    body = `<audio controls src="${await dataUrl(url)}"></audio>`;
  else if (item.mime === 'text/html') body = frame(await (await fetch(url)).text(), item.key, 360);
  else if (/plotly|vega|bokeh/.test(item.mime)) body = figureHtml(item.mime, await (await fetch(url)).text(), needs);
  else body = `<p class="missing">${esc(item.mime)} items are not exported</p>`;
  return `<figure>${body}<figcaption>${caption ? `<span>${esc(caption)}</span>` : ''}<small>${esc(meta)}</small></figcaption></figure>`;
}

const STYLE = `
body{margin:0;background:#f4f6f9;color:#1b2430;font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:900px;margin:32px auto;padding:32px 40px;background:#fff;border-radius:14px;box-shadow:0 1px 3px rgb(0 0 0/.08)}
h1{font-size:28px;letter-spacing:-.02em;margin:.2em 0 .6em}h2{font-size:21px;margin:1.4em 0 .5em}h3{font-size:17px}
a{color:#0b6bcb}code{font:.9em ui-monospace,Menlo,monospace;background:#f0f2f5;border-radius:5px;padding:1px 5px}
pre{background:#f0f2f5;border:1px solid #e3e7ed;border-radius:9px;padding:10px 12px;overflow:auto;font:12.5px/1.5 ui-monospace,Menlo,monospace}
pre code{background:none;padding:0}table{border-collapse:collapse;margin:.8em 0}th,td{border:1px solid #e3e7ed;padding:5px 10px}
blockquote{margin:.8em 0;padding:.1em 1em;border-left:3px solid #e3e7ed;color:#5b6675}
img{max-width:100%;border-radius:8px}figure{margin:1.2em 0}figcaption{display:flex;flex-direction:column;font-size:13px;margin-top:6px}
figcaption small{color:#8a94a3;font-family:ui-monospace,Menlo,monospace;font-size:12px}audio{width:100%}
.nbfig{width:100%;min-height:120px}.frame{width:100%;border:1px solid #e3e7ed;border-radius:8px;background:#fff}.missing{color:#8a94a3;font-style:italic}
footer{max-width:900px;margin:0 auto 32px;color:#8a94a3;font-size:12px;text-align:center}
@media print{body{background:#fff}main{box-shadow:none;margin:0;padding:0}}`;

/** Build the standalone HTML of a report. */
export async function reportHtml(project: string, title: string, text: string): Promise<string> {
  const files = api.reportFileUrl(project, '');
  const doc = new DOMParser().parseFromString(`<main>${renderMarkdown(text, files)}</main>`, 'text/html');
  const main = doc.querySelector('main')!;
  const swap = async (el: Element, html: string | Promise<string>) => {
    const tpl = doc.createElement('template');
    tpl.innerHTML = await html;
    el.replaceWith(tpl.content);
  };
  const snapshot = async (src: string, caption: string, half: boolean) => {
    const data = await dataUrl(src);
    let width = '';
    if (half) {
      // view snapshots are drawn at twice their on-screen size
      const img = new Image();
      img.src = data;
      await img.decode().catch(() => {});
      if (img.naturalWidth) width = ` width="${Math.round(img.naturalWidth / 2)}"`;
    }
    return `<figure><img src="${data}"${width} alt="${esc(caption)}">${caption ? `<figcaption><span>${esc(caption)}</span></figcaption>` : ''}</figure>`;
  };
  const needs: Needs = { libs: new Set() };
  const jobs: Promise<void>[] = [];
  for (const el of main.querySelectorAll<HTMLElement>('.nb-embed'))
    jobs.push(swap(el, mediaHtml(project, el.dataset.ref ?? '', el.dataset.caption ?? '', needs)));
  for (const el of main.querySelectorAll<HTMLElement>('.nb-chart, .nb-view'))
    jobs.push(swap(el, snapshot(el.dataset.src ?? '', el.dataset.caption ?? '', el.classList.contains('nb-view'))));
  for (const img of main.querySelectorAll<HTMLImageElement>('img'))
    if (img.getAttribute('src')?.startsWith(files))
      jobs.push(dataUrl(img.getAttribute('src')!).then((d) => img.setAttribute('src', d)));
  await Promise.all(jobs);
  const scripts: string[] = [];
  if (needs.libs.has('plotly')) scripts.push(...(await VENDOR.plotly()));
  if (needs.libs.has('vega')) scripts.push(...(await VENDOR.vega()));
  if (needs.bokeh) {
    const bokeh = await bokehScripts(needs.bokeh);
    if (bokeh) scripts.push(...bokeh);
  }
  if (needs.libs.size) scripts.push(DRAW);
  const tail = scripts.map((js) => `<script>${scriptSafe(js)}</script>`).join('\n');
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title><style>${STYLE}</style></head>
<body>${main.outerHTML}<footer>Exported from ${esc(project)}/reports on ${new Date().toLocaleString()}</footer>
${tail}</body></html>
`;
}

/** Download the report as `<name>.html`. */
export async function downloadReportHtml(project: string, name: string, title: string, text: string) {
  const html = await reportHtml(project, title, text);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  a.download = `${name}.html`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
