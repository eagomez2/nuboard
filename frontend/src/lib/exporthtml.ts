// Export a report as one self-contained HTML file that needs no network: images, audio and chart
// snapshots inlined as data URLs, logged text and HTML inlined, and interactive figures drawn from
// their spec by the Plotly or Vega libraries embedded once in the file (only those it uses).

import { api, type AudioNote, type MediaItem } from './api';
import { DISPLAY_NAME } from './brand';
import { decodeSpec } from './chartspec';
import { baselineExtent, baselineLines } from './baselines';
import { HIST_MIME, POINTS_MIME, PR_MIME, TABLE_MIME, WAVEFORM_MIME } from './media';
import { lowerIsBetter } from './format';
import { tableHtml, type TableData } from './tables';
import { fmtTick, histSvg, type HistData, type HistSeries } from './hist';
import { mountPoints } from './points';
import { mountWaveform } from './waveexport';
import { waveformKit } from './waveform';
import { prArea, prSvg, type PRData } from './pr';
import { renderMarkdown } from './markdown';
import { ema, robustRange } from './smooth';
import LOGO from '../../public/logo.svg?raw';
import AUDIO_PAGE from '../../audio.html?raw';
import PLAYER_CSS from '../audio/player.css?raw';
import UPLOT_CSS from '../../node_modules/uplot/dist/uPlot.min.css?raw';

type Lib = 'plotly' | 'vega' | 'bokeh' | 'uplot';

// The UMD builds the viewer already ships, loaded as text only when a report is exported.
const VENDOR: Record<'plotly' | 'vega' | 'uplot' | 'player', () => Promise<string[]>> = {
  uplot: async () => [(await import('../../node_modules/uplot/dist/uPlot.iife.min.js?raw')).default],
  plotly: async () => [(await import('../../node_modules/plotly.js-dist-min/plotly.min.js?raw')).default],
  // the waveform player: wavesurfer.js and its plugins, then the player itself
  player: async () =>
    Promise.all([
      import('../../node_modules/wavesurfer.js/dist/wavesurfer.min.js?raw').then((m) => m.default),
      import('../../node_modules/wavesurfer.js/dist/plugins/regions.min.js?raw').then((m) => m.default),
      import('../../node_modules/wavesurfer.js/dist/plugins/hover.min.js?raw').then((m) => m.default),
      import('../../node_modules/wavesurfer.js/dist/plugins/minimap.min.js?raw').then((m) => m.default),
      import('../audio/player.js?raw').then((m) => m.default),
    ]),
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
  /** An audio item has notes, so the script that plays a note's section is added. */
  notes?: boolean;
  /** A point cloud is embedded, so its renderer is added. */
  points?: boolean;
  /** Audio is drawn with the waveform player, so the player is embedded once. */
  wave?: boolean;
  /** A waveform figure is embedded, so its plot is added (with uPlot). */
  waveform?: boolean;
}

/** How audio is exported: the waveform and spectrogram player, or the browser's own. */
export type AudioPlayer = 'wave' | 'simple';

/** `m:ss.s` for a time in seconds, as the audio player shows it. */
function clock(t: number): string {
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, '0')}`;
}

/** An audio item's notes as a plain list, under a waveform player that also draws them. */
function notesList(notes: AudioNote[]): string {
  if (!notes.length) return '';
  const rows = notes
    .map((n) => `<li><span class="nbtime">${clock(n.start)} – ${clock(n.end)}</span> ${esc(n.text)}</li>`)
    .join('');
  return `<ol class="nbnotes">${rows}</ol>`;
}

/** An audio item's notes, each playing its section when clicked. */
function notesHtml(notes: AudioNote[], needs: Needs): string {
  if (!notes.length) return '';
  needs.notes = true;
  const rows = notes
    .map(
      (n) =>
        `<li><button type="button" class="nbnote" data-start="${n.start}" data-end="${n.end}" title="Play this section">${clock(n.start)} – ${clock(n.end)}</button> ${esc(n.text)}</li>`,
    )
    .join('');
  return `<ol class="nbnotes">${rows}</ol>`;
}

// Draws each embedded point cloud and keeps its background on the page's theme.
const POINTS_JS = `var mountPoints=(${mountPoints.toString()});
document.querySelectorAll('.nbpoints').forEach(function(box){
var c=box.querySelector('canvas'),s=box.querySelector('script'),bin=atob(s.textContent.trim()),u=new Uint8Array(bin.length);
for(var i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
var bg=function(){return getComputedStyle(document.documentElement).getPropertyValue('--code').trim()};
var v=mountPoints(c,u.buffer,+box.dataset.count,box.dataset.colors==='1',bg(),box.dataset.axes?JSON.parse(box.dataset.axes):null);
new MutationObserver(function(){v.setBackground(bg())}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
});`;

// Draws each waveform figure from the WAV in its <audio> and the signals in its <script>, with the
// same decimation as the viewer.
const WAVEFORM_JS = `var waveformKit=(${waveformKit.toString()});
var mountWaveform=(${mountWaveform.toString()});
var kit=waveformKit();
document.querySelectorAll('.nbwavefig').forEach(function(box){mountWaveform(box,kit,uPlot)});`;

/** Base64 of `bytes`, a chunk at a time (a spread of millions of arguments would overflow the stack). */
function base64(bytes: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// Puts the waveform player in each audio frame: the player's page and scripts are stored once in
// #nbplayer, and the frame's own data goes in before them as NB_AUDIO_EMBED. The frames follow
// the page's light or dark theme.
const WAVE_JS = `(function(){
var P=JSON.parse(document.getElementById('nbplayer').textContent);
var v=function(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()};
var theme=function(){return{base:document.documentElement.dataset.theme==='dark'?'dark':'light',textColor:v('--text'),backgroundColor:v('--panel'),secondaryBackgroundColor:v('--code'),primaryColor:v('--link'),font:'system-ui,-apple-system,"Segoe UI",sans-serif',fontMono:'ui-monospace,Menlo,monospace'}};
var end='</'+'script>';
var frames=[];
document.querySelectorAll('.nbwave').forEach(function(box){
var f=box.querySelector('iframe'),boot=JSON.stringify({args:JSON.parse(box.dataset.args),theme:theme()}).replace(/</g,'\\u003c');
f.srcdoc='<!doctype html><html><head><meta charset="utf-8"><style>'+P.css+'</style></head><body>'+P.body+'<script>window.NB_AUDIO_EMBED='+boot+end+P.js.map(function(j){return '<script>'+j+end}).join('')+'</body></html>';
frames.push(f);
});
var follow=function(){var t=theme();frames.forEach(function(f){try{f.contentWindow.nbAudioTheme&&f.contentWindow.nbAudioTheme(t)}catch(e){}})};
document.addEventListener('nbtheme',follow);
})();`;

// Clicking a note plays its section of the audio just above it.
const NOTES_JS = `document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.nbnote');if(!b)return;var a=b.closest('figure').querySelector('audio');if(!a)return;var end=+b.dataset.end;a.currentTime=+b.dataset.start;a.play();a.ontimeupdate=function(){if(a.currentTime>=end){a.pause();a.ontimeupdate=null}}});`;

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

const round = (a: ArrayLike<number>) => Array.from(a, (v) => (Number.isFinite(v) ? Number(v.toPrecision(6)) : null));

/**
 * A chart saved from the Charts page, drawn live in the file (uPlot) from its data as of the export,
 * so it follows the file's theme. Null when the data cannot be loaded (the snapshot is used then).
 */
async function chartHtml(specText: string, caption: string, needs: Needs): Promise<string | null> {
  const spec = decodeSpec(specText);
  if (!spec) return null;
  let data;
  try {
    data = await api.chart({
      runs: spec.runs,
      metric: spec.metric,
      x: spec.x,
      group: spec.group,
      agg: spec.agg,
      points: 900,
      xmin: spec.zoom?.[0],
      xmax: spec.zoom?.[1],
    });
  } catch {
    return null;
  }
  const hidden = new Set(spec.hidden);
  const smooth = (a: ArrayLike<number>) => (spec.smooth > 0 ? ema(a, spec.smooth) : a);
  const ys: Float64Array[] = [];
  const series = data.series.flatMap((x, i) => {
    if (hidden.has(x.label) || !x.x.length) return [];
    const y = smooth(x.y);
    ys.push(Float64Array.from(y));
    const band = (x.band || (x.n ?? 1) > 1) && x.lo.some((v, k) => Number.isFinite(v) && v !== x.y[k]);
    return [
      {
        label: x.label,
        c: i % 8,
        x: Array.from(x.x),
        y: round(y),
        raw: spec.raw && spec.smooth > 0 ? round(x.y) : undefined,
        lo: band ? round(smooth(x.lo)) : undefined,
        hi: band ? round(smooth(x.hi)) : undefined,
      },
    ];
  });
  if (!series.length) return null;
  needs.libs.add('uplot');
  const lines = spec.base ? baselineLines(data.series, hidden) : [];
  const extent = baselineExtent(lines, spec.log);
  let range = spec.robust && !spec.log ? robustRange(ys) : null;
  if (range && extent) range = [Math.min(range[0], extent[0]), Math.max(range[1], extent[1])];
  const baselines = lines.map((l) => ({
    value: l.value,
    low: l.low ?? null,
    high: l.high ?? null,
    c: l.series.length === 1 ? l.series[0] % 8 : null,
  }));
  const json = JSON.stringify({ xKind: data.xKind, log: spec.log, zoom: spec.zoom, range, extent, baselines, series });
  const sub = spec.group ? `grouped by ${spec.group}` : `${spec.runs.length} runs`;
  const legend = series
    .map((x) => `<span><i style="background:var(--s${x.c + 1})"></i>${esc(x.label)}</span>`)
    .join('');
  return `<figure><div class="nbchart"><div class="nbchart-head"><b>${esc(spec.metric)}</b><span>${esc(sub)}</span></div><div class="nbplot"></div><script type="application/json">${json.replace(/</g, '\\u003c')}</script><div class="nblegend">${legend}</div></div>${caption ? `<figcaption><span>${esc(caption)}</span></figcaption>` : ''}</figure>`;
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

// Draws every figure for the page's theme, and again when a switchable page changes theme.
const DRAW = `const nbDrawn = new Map();
function nbDraw() {
  const dark = document.documentElement.dataset.theme === 'dark';
  for (const el of document.querySelectorAll('.nbfig')) {
    try {
      const spec = JSON.parse(el.nextElementSibling.textContent);
      const lib = el.dataset.lib;
      if (lib === 'plotly') {
        const layout = Object.assign({}, spec.layout || {}, { paper_bgcolor: 'rgba(0,0,0,0)' });
        if (dark) {
          layout.plot_bgcolor = 'rgba(0,0,0,0)';
          layout.font = Object.assign({}, layout.font || {}, { color: '#e6eaf0' });
          const keys = Object.keys(layout).filter((k) => /^[xy]axis\\d*$/.test(k));
          for (const k of keys.length ? keys : ['xaxis', 'yaxis'])
            layout[k] = Object.assign({ gridcolor: 'rgba(255,255,255,0.1)', zerolinecolor: 'rgba(255,255,255,0.2)' }, layout[k] || {});
        }
        Plotly.react(el, spec.data || [], layout, { responsive: true, displaylogo: false });
      } else if (lib === 'vega') {
        if (nbDrawn.has(el)) nbDrawn.get(el).finalize();
        el.innerHTML = '';
        vegaEmbed(el, spec, { actions: false, renderer: 'svg', theme: dark ? 'dark' : undefined, config: { background: 'transparent' } })
          .then((r) => nbDrawn.set(el, r));
      } else if (lib === 'bokeh' && window.Bokeh) {
        if (nbDrawn.has(el)) continue;
        el.id = el.id || 'nbfig' + Math.random().toString(36).slice(2);
        Bokeh.embed.embed_item(spec, el.id);
        nbDrawn.set(el, true);
      } else el.textContent = 'This figure could not be drawn because its library is not in the file.';
    } catch (e) {
      el.textContent = 'This figure could not be drawn: ' + e;
    }
  }
}
function nbCharts() {
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  const alpha = (hex, a) => {
    let h = hex.replace('#', '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  };
  for (const el of document.querySelectorAll('.nbplot')) {
    try {
      const d = JSON.parse(el.nextElementSibling.textContent);
      const tables = [];
      const series = [{}];
      const bands = [];
      let col = 1;
      const hidden = { stroke: 'transparent', width: 0, points: { show: false } };
      for (const s of d.series) {
        const color = v('--s' + (s.c + 1)) || '#0072b2';
        const cols = [];
        if (s.raw) {
          cols.push(s.raw);
          series.push({ label: s.label + ' raw', stroke: alpha(color, 0.28), width: 1, points: { show: false } });
        }
        if (s.lo) {
          cols.push(s.lo, s.hi);
          series.push(Object.assign({ label: s.label + ' lo' }, hidden), Object.assign({ label: s.label + ' hi' }, hidden));
          bands.push({ series: [col + cols.length - 1, col + cols.length - 2], fill: alpha(color, 0.16) });
        }
        cols.push(s.y);
        series.push({ label: s.label, stroke: color, width: 2, points: { show: false } });
        col += cols.length;
        tables.push([s.x].concat(cols));
      }
      const axis = { stroke: v('--muted'), grid: { stroke: v('--grid'), width: 1 }, ticks: { show: false }, font: '12px ui-monospace,Menlo,monospace' };
      const y = { distr: d.log ? 3 : 1 };
      if (d.range) y.range = () => d.range;
      else if (d.extent) y.range = (u, min, max) => {
        min = Math.min(min, d.extent[0]);
        max = Math.max(max, d.extent[1]);
        if (d.log) return [Math.max(min, 1e-12), max];
        const pad = (max - min || Math.abs(max) || 1) * 0.06;
        return [min - pad, max + pad];
      };
      const drawBaselines = (u) => {
        const ctx = u.ctx;
        const dpr = devicePixelRatio;
        const left = u.bbox.left, right = left + u.bbox.width, top = u.bbox.top, bottom = top + u.bbox.height;
        const clamp = (p) => Math.min(Math.max(p, top), bottom);
        ctx.save();
        for (const b of d.baselines || []) {
          if (d.log && b.value <= 0) continue;
          const color = b.c === null ? v('--muted') || '#888' : v('--s' + (b.c + 1)) || '#0072b2';
          if (b.low !== null && b.high !== null && (!d.log || b.low > 0)) {
            const a = clamp(u.valToPos(b.high, 'y', true));
            ctx.fillStyle = alpha(color, 0.09);
            ctx.fillRect(left, a, right - left, clamp(u.valToPos(b.low, 'y', true)) - a);
          }
          const py = Math.round(u.valToPos(b.value, 'y', true));
          if (py < top || py > bottom) continue;
          ctx.strokeStyle = alpha(color, 0.9);
          ctx.lineWidth = 1.5 * dpr;
          ctx.setLineDash([6 * dpr, 4 * dpr]);
          ctx.beginPath();
          ctx.moveTo(left, py);
          ctx.lineTo(right, py);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = color;
          ctx.font = 11 * dpr + 'px ui-monospace,Menlo,monospace';
          ctx.textAlign = 'right';
          ctx.fillText('Baseline', right - 6 * dpr, py - 5 * dpr);
        }
        ctx.restore();
      };
      if (nbDrawn.has(el)) nbDrawn.get(el).destroy();
      el.innerHTML = '';
      const u = new uPlot({
        width: el.clientWidth || 800, height: 300, series, bands, legend: { show: false }, padding: [12, 12, 0, 4],
        scales: { x: { time: d.xKind === 'time' }, y },
        axes: [Object.assign({ size: 40 }, axis), Object.assign({ size: 56 }, axis)],
        cursor: { drag: { x: true, y: false }, points: { show: false } },
        hooks: { draw: [drawBaselines] },
      }, tables.length === 1 ? tables[0] : uPlot.join(tables), el);
      if (d.zoom) u.setScale('x', { min: d.zoom[0], max: d.zoom[1] });
      nbDrawn.set(el, u);
    } catch (e) {
      el.textContent = 'This chart could not be drawn: ' + e;
    }
  }
}
nbDraw();
nbCharts();
document.addEventListener('nbtheme', () => { nbDraw(); nbCharts(); });
let nbResize = 0;
addEventListener('resize', () => { clearTimeout(nbResize); nbResize = setTimeout(nbCharts, 150); });`;

async function mediaHtml(
  project: string,
  ref: string,
  caption: string,
  needs: Needs,
  player: AudioPlayer = 'simple',
): Promise<string> {
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
  else if (item.mime.startsWith('video/'))
    body = `<video src="${await dataUrl(url)}" controls loop muted playsinline></video>`;
  else if (item.mime.startsWith('image/')) body = `<img src="${await dataUrl(url)}" alt="${esc(caption)}">`;
  else if ((item.kind === 'audio' || item.mime.startsWith('audio/')) && player === 'wave') {
    // drawn by the waveform player, which the script at the end puts in the frame
    needs.wave = true;
    const args = {
      url: await dataUrl(url),
      sampleRate: item.sample_rate ?? 0,
      channels: item.channels ?? 1,
      duration: item.duration ?? 0,
      group: `export-${ref}`,
      link: false,
      scale: 'linear',
      fftSize: 1024,
      colormap: 'theme',
      waveHeight: 72,
      spectrogramHeight: 140,
      normalize: false,
      notes: false,
      annotations: item.notes ?? [],
      header: {},
    };
    body = `<div class="nbwave" data-args="${esc(JSON.stringify(args))}"><iframe title="${esc(item.key)}"></iframe></div>${notesList(item.notes ?? [])}`;
  } else if (item.kind === 'audio' || item.mime.startsWith('audio/'))
    body = `<audio controls src="${await dataUrl(url)}"></audio>${notesHtml(item.notes ?? [], needs)}`;
  else if (item.mime === TABLE_MIME) {
    const table = (await (await fetch(url)).json()) as TableData;
    // compared with the same table at the step before, as the viewer does by default
    const { items } = await api.media(found.run);
    const prev = items
      .filter((m) => m.key === item.key && m.mime === TABLE_MIME && m.step < item.step && m.index !== undefined)
      .pop();
    const base = prev ? ((await (await fetch(api.mediaUrl(found.run, prev.index!))).json()) as TableData) : null;
    const since = prev ? `<small class="nbmore">Colors show the change since step ${prev.step}.</small>` : '';
    body = tableHtml(table, base, lowerIsBetter) + since;
  } else if (item.mime === PR_MIME) {
    const data = (await (await fetch(url)).json()) as PRData;
    const curve = prSvg([{ name: found.run_name, color: 'var(--s1)', data }], 640, 300);
    body = `<div class="nbpr">${curve}<small>AP ${prArea(data).toFixed(3)}</small></div>`;
  } else if (item.mime === HIST_MIME) {
    // the step against the one logged before it, as the viewer shows it
    const data = (await (await fetch(url)).json()) as HistData;
    const { items } = await api.media(found.run);
    const prev = items
      .filter((m) => m.key === item.key && m.mime === HIST_MIME && m.step < item.step && m.index !== undefined)
      .pop();
    const series: HistSeries[] = [{ name: `Step ${item.step}`, color: 'var(--s1)', data, fill: true }];
    if (prev) {
      const old = (await (await fetch(api.mediaUrl(found.run, prev.index!))).json()) as HistData;
      series.push({ name: `Step ${prev.step}`, color: 'var(--faint)', data: old, dashed: true });
    }
    const stats = [
      data.mean != null ? `mean ${fmtTick(data.mean)}` : '',
      data.std != null ? `std ${fmtTick(data.std)}` : '',
      `n ${data.count.toLocaleString()}`,
      prev ? `Dashed: step ${prev.step}` : '',
    ].filter(Boolean);
    body = `<div class="nbpr">${histSvg(series, 640, 280)}<small>${esc(stats.join(' · '))}</small></div>`;
  } else if (item.mime === POINTS_MIME) {
    needs.points = true;
    const base64 = (await dataUrl(url)).replace(/^data:[^,]*,/, '');
    body = `<div class="nbpoints" data-count="${item.points ?? 0}" data-colors="${item.colors ? 1 : 0}"${item.axes ? ` data-axes="${esc(JSON.stringify(item.axes))}"` : ''}><canvas aria-label="${esc(item.key)}"></canvas><script type="application/octet-stream">${base64}</script><small>${(item.points ?? 0).toLocaleString()} points · drag to rotate, shift-drag to pan, click then scroll to zoom, double-click to reset</small></div>`;
  } else if (item.mime === 'text/html') body = frame(await (await fetch(url)).text(), item.key, 360);
  else if (item.mime === WAVEFORM_MIME) {
    // the audio plays from its own data URL; the plot reads the same bytes, then the signals after them
    needs.libs.add('uplot');
    needs.waveform = true;
    const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
    const offset = item.audio_bytes ?? 0;
    const names = item.signals ?? [];
    const info = { names, range: item.range ?? [-1, 1], samples: item.samples ?? 0 };
    const legend = names
      .map((n, i) => `<span><i style="background:var(--s${((i + 1) % 8) + 1})"></i>${esc(n)}</span>`)
      .join('');
    body =
      `<div class="nbwavefig" data-meta="${esc(JSON.stringify(info))}">` +
      `<div class="nbwf-bar"><span class="nbwf-read">Drag to zoom · Ctrl/⌘ + wheel zooms · Shift + wheel scrolls · double-click shows all · click to set the playhead</span><button type="button" class="nbwf-fit">Fit</button></div>` +
      `<div class="nbwf-plot"></div><audio controls preload="auto" src="data:audio/wav;base64,${base64(bytes.subarray(0, offset))}"></audio>` +
      `<script type="application/octet-stream">${base64(bytes.subarray(offset))}</script>` +
      `<div class="nblegend">${legend}</div></div>`;
  } else if (/plotly|vega|bokeh/.test(item.mime)) body = figureHtml(item.mime, await (await fetch(url)).text(), needs);
  else body = `<p class="missing">${esc(item.mime)} items are not exported</p>`;
  return `<figure>${body}<figcaption>${caption ? `<span>${esc(caption)}</span>` : ''}<small>${esc(meta)}</small></figcaption></figure>`;
}

// Light and dark colors, including the series palette, mirror app.css.
const STYLE = `
:root{--bg:#f4f6f9;--panel:#fff;--text:#1b2430;--muted:#5b6675;--faint:#8a94a3;--border:#e3e7ed;--code:#f0f2f5;--link:#0b6bcb;--grid:#e9edf2;color-scheme:light;
--s1:#0072b2;--s2:#e69f00;--s3:#cc79a7;--s4:#009e73;--s5:#d55e00;--s6:#56b4e9;--s7:#8a7a00;--s8:#6a4c93}
:root[data-theme=dark]{--bg:#0f1318;--panel:#171c23;--text:#e6eaf0;--muted:#a3adba;--faint:#75808e;--border:#2a313b;--code:#1f252e;--link:#6cb0ff;--grid:#232a35;color-scheme:dark;
--s1:#56b4e9;--s2:#e69f00;--s3:#e08fbd;--s4:#2bbf95;--s5:#ff8c42;--s6:#9ad0f0;--s7:#f0e442;--s8:#b39ddb}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:900px;margin:32px auto;padding:32px 40px;background:var(--panel);border:1px solid var(--border);border-radius:14px;box-shadow:0 1px 3px rgb(0 0 0/.08)}
h1{font-size:28px;letter-spacing:-.02em;margin:.2em 0 .6em}h2{font-size:21px;margin:1.4em 0 .5em}h3{font-size:17px}
a{color:var(--link)}code{font:.9em ui-monospace,Menlo,monospace;background:var(--code);border-radius:5px;padding:1px 5px}
pre{background:var(--code);border:1px solid var(--border);border-radius:9px;padding:10px 12px;overflow:auto;font:12.5px/1.5 ui-monospace,Menlo,monospace}
pre code{background:none;padding:0}table{border-collapse:collapse;margin:.8em 0}th,td{border:1px solid var(--border);padding:5px 10px}
blockquote{margin:.8em 0;padding:.1em 1em;border-left:3px solid var(--border);color:var(--muted)}
img,video{max-width:100%;border-radius:8px}figure{margin:1.2em 0}.nbtable{overflow:auto;max-height:560px;border:1px solid var(--border);border-radius:8px}.nbtable table{margin:0;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}.nbtable th{position:sticky;top:0;background:var(--panel);text-align:left}.nbtable .n{text-align:right;white-space:nowrap}.nbtable td small{color:var(--muted);margin-left:6px;font-size:11px}.nbtable .m{color:var(--faint)}.nbmore{color:var(--faint);font-size:12px}
.nbpr svg{display:block;max-width:100%;height:auto}.nbpr small{color:var(--faint);font-size:12px}
.nbpoints canvas{display:block;width:100%;height:420px;border-radius:8px;background:var(--code)}.nbpoints small{color:var(--faint);font-size:12px}
.nbnotes{margin:6px 0 0;padding-left:1.4em;font-size:13.5px}.nbtime{font:12px ui-monospace,Menlo,monospace;color:var(--muted);margin-right:4px}.nbwave iframe{display:block;width:100%;height:300px;border:0;background:transparent}.nbnote{font:12px ui-monospace,Menlo,monospace;color:var(--link);background:var(--code);border:1px solid var(--border);border-radius:6px;padding:1px 6px;cursor:pointer;margin-right:4px}
figcaption{display:flex;flex-direction:column;font-size:13px;margin-top:6px}
figcaption small{color:var(--faint);font-family:ui-monospace,Menlo,monospace;font-size:12px}audio{width:100%}
.nbfig{width:100%;min-height:120px}.frame{width:100%;border:1px solid var(--border);border-radius:8px;background:#fff}.missing{color:var(--faint);font-style:italic}
.nbchart{border:1px solid var(--border);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.nbwavefig{display:flex;flex-direction:column;gap:6px}.nbwavefig audio{width:100%}
.nbwf-bar{display:flex;gap:10px;align-items:center;font:12px ui-monospace,Menlo,monospace;color:var(--muted)}.nbwf-read{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.nbwf-fit{font:12px system-ui,sans-serif;padding:3px 10px;border:1px solid var(--border);border-radius:6px;background:var(--panel);color:var(--text);cursor:pointer}
.nbchart-head{display:flex;gap:10px;align-items:baseline;font-size:13px}.nbchart-head b{font-family:ui-monospace,Menlo,monospace}.nbchart-head span{color:var(--faint);font-size:12px}
.nblegend{display:flex;flex-wrap:wrap;gap:4px 12px;font:12px ui-monospace,Menlo,monospace;color:var(--muted)}.nblegend i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
footer{max-width:900px;margin:0 auto 32px;padding:0 16px;color:var(--faint);font-size:12px;text-align:center}
.nbtheme{position:fixed;top:14px;right:14px;width:36px;height:36px;display:grid;place-items:center;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--muted);cursor:pointer}
.nbtheme:hover{color:var(--text)}.nbtheme svg{width:18px;height:18px}
:root[data-theme=dark] .nbtheme .sun,:root:not([data-theme=dark]) .nbtheme .moon{display:none}
@media (max-width:640px){main{margin:16px;padding:20px 16px}}
@media print{:root{--bg:#fff;--panel:#fff}main{box-shadow:none;border:0;margin:0;padding:0}.nbtheme{display:none}}`;

// A switchable page starts in the reader's system theme (or the one they picked last) and has a
// button that flips it.
const THEME_START = `(()=>{let t;try{t=localStorage.getItem('nuboard-report-theme')}catch{}
document.documentElement.dataset.theme=t||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')})()`;
const THEME_BUTTON = `<button class="nbtheme" type="button" aria-label="Switch between light and dark theme" title="Light or dark theme"
onclick="const r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem('nuboard-report-theme',r.dataset.theme)}catch{}document.dispatchEvent(new Event('nbtheme'))">
<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>`;

export type ExportTheme = 'light' | 'dark' | 'switch';

/** How a report is exported: its theme, the footer text, and whether the logo is the tab icon. */
export interface ExportOptions {
  theme: ExportTheme;
  footer: string;
  logo: boolean;
  /** How audio is drawn; the waveform player unless set. */
  audioPlayer?: AudioPlayer;
}

/** Whether a report embeds any audio, so the export can offer a choice of player. */
export async function reportHasAudio(project: string, text: string): Promise<boolean> {
  const doc = new DOMParser().parseFromString(renderMarkdown(text, ''), 'text/html');
  const refs = [...doc.querySelectorAll<HTMLElement>('.nb-embed')].map((el) => el.dataset.ref ?? '');
  const items = await Promise.all(refs.map((ref) => api.mediaRef(project, ref).catch(() => null)));
  return items.some((f) => f && (f.item.kind === 'audio' || f.item.mime.startsWith('audio/')));
}

/** The footer a report gets unless it is changed when exporting. */
export function defaultFooter(project: string, version = ''): string {
  const name = version ? `${DISPLAY_NAME} ${version}` : DISPLAY_NAME;
  return `Exported with ${name} from ${project}/reports on ${new Date().toLocaleString()}`;
}

/** Build the standalone HTML of a report. */
export async function reportHtml(
  project: string,
  title: string,
  text: string,
  opts: ExportOptions = { theme: 'light', footer: defaultFooter(project), logo: true },
): Promise<string> {
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
    jobs.push(
      swap(el, mediaHtml(project, el.dataset.ref ?? '', el.dataset.caption ?? '', needs, opts.audioPlayer ?? 'wave')),
    );
  for (const el of main.querySelectorAll<HTMLElement>('.nb-chart')) {
    const { spec = '', caption = '', src = '' } = el.dataset;
    jobs.push(
      swap(
        el,
        chartHtml(spec, caption, needs).then((html) => html ?? snapshot(src, caption, false)),
      ),
    );
  }
  for (const el of main.querySelectorAll<HTMLElement>('.nb-view'))
    jobs.push(swap(el, snapshot(el.dataset.src ?? '', el.dataset.caption ?? '', true)));
  for (const img of main.querySelectorAll<HTMLImageElement>('img'))
    if (img.getAttribute('src')?.startsWith(files))
      jobs.push(dataUrl(img.getAttribute('src')!).then((d) => img.setAttribute('src', d)));
  await Promise.all(jobs);
  const scripts: string[] = [];
  if (needs.libs.has('plotly')) scripts.push(...(await VENDOR.plotly()));
  if (needs.libs.has('vega')) scripts.push(...(await VENDOR.vega()));
  if (needs.libs.has('uplot')) scripts.push(...(await VENDOR.uplot()));
  if (needs.bokeh) {
    const bokeh = await bokehScripts(needs.bokeh);
    if (bokeh) scripts.push(...bokeh);
  }
  if (needs.libs.size) scripts.push(DRAW);
  if (needs.notes) scripts.push(NOTES_JS);
  if (needs.points) scripts.push(POINTS_JS);
  if (needs.waveform) scripts.push(WAVEFORM_JS);
  let player = '';
  if (needs.wave) {
    const page = new DOMParser().parseFromString(AUDIO_PAGE, 'text/html');
    page.querySelectorAll('script').forEach((el) => el.remove());
    const source = { css: PLAYER_CSS, body: page.body.innerHTML, js: (await VENDOR.player()).map(scriptSafe) };
    player = `<script type="application/json" id="nbplayer">${JSON.stringify(source).replace(/</g, '\\u003c')}</script>`;
    scripts.push(WAVE_JS);
  }
  const tail = player + scripts.map((js) => `<script>${scriptSafe(js)}</script>`).join('\n');
  const switchable = opts.theme === 'switch';
  const theme = switchable ? `<script>${THEME_START}</script>` : '';
  const icon = opts.logo
    ? `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,${encodeURIComponent(LOGO)}">`
    : '';
  const footer = opts.footer.trim() ? `<footer>${esc(opts.footer.trim())}</footer>` : '';
  return `<!doctype html>
<html lang="en"${switchable ? '' : ` data-theme="${opts.theme}"`}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>${icon}${theme}<style>${STYLE}${needs.libs.has('uplot') ? UPLOT_CSS : ''}</style></head>
<body>${switchable ? THEME_BUTTON : ''}${main.outerHTML}${footer}
${tail}</body></html>
`;
}

/** Download the report as `<name>.html`. */
export async function downloadReportHtml(
  project: string,
  name: string,
  title: string,
  text: string,
  opts: ExportOptions,
) {
  const html = await reportHtml(project, title, text, opts);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  a.download = `${name}.html`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
