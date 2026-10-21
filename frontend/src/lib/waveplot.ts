// A waveform figure (`add_figure(key, nb.WaveformFigure(...))`), drawn the same way in the viewer
// (WaveformPlot.svelte) and in an HTML export of a report, with the rules in waveplot.css: what you
// see in the viewer is what the exported file shows.

import type uPlot from 'uplot';
import type { waveformKit } from './waveform';

type Kit = ReturnType<typeof waveformKit>;

export interface WaveformInput {
  /** The item's bytes: the WAV, then `samples` float32 values per signal. */
  buffer: ArrayBuffer;
  /** Bytes of the WAV at the start of `buffer`. */
  offset: number;
  names: string[];
  /** The values at the bottom and top of the plot; -1 and 1 share the waveform's axis. */
  range: [number, number];
  samples: number;
  /** What the audio plays from: a blob URL in the viewer, a data URL in an export. */
  audioSrc: string;
  caption?: string | null;
  height?: number;
}

/**
 * Draw a waveform figure in `box`: the samples with each signal over them, accurate at every zoom
 * (M4, see lib/waveform.ts), with the values at a sample under the pointer. Drag or Ctrl/⌘ + wheel
 * zooms, Shift + wheel scrolls, − / + / Fit and double-click change the zoom, the overview below moves
 * the view, and the play button plays the clip from where the plot was clicked. It uses nothing from
 * outside itself, so an export embeds it as text (`mountWaveform.toString()`).
 */
export function mountWaveform(
  box: HTMLElement,
  kit: Kit,
  UPlot: typeof uPlot,
  input: WaveformInput,
): { restyle: () => void; destroy: () => void } {
  const data = kit.parseWaveform(input.buffer, input.offset, input.names, input.samples);
  const values = [...data.channels, ...data.signals];
  const pyramids = values.map((v) => new kit.Pyramid(v));
  const rate = data.sampleRate;
  const duration = data.channels[0].length / rate;
  const nch = data.channels.length;
  const labels = [...(nch > 1 ? data.channels.map((_, c) => `ch ${c + 1}`) : ['audio']), ...input.names];
  const own = input.range[0] !== -1 || input.range[1] !== 1;
  const height = input.height ?? 240;
  let view: [number, number] = [0, duration];
  let plot: uPlot | null = null;
  let frame = 0;
  let dots: HTMLElement[] = [];

  // the widget: toolbar, plot, overview, legend and caption, and the audio it plays
  const el = (tag: string, cls?: string, text?: string) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const icon = (cls: string, d: string) =>
    `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
  const root = el('div', 'nbwf');
  const bar = el('div', 'nbwf-bar');
  const play = el('button', 'nbwf-play') as HTMLButtonElement;
  play.type = 'button';
  play.setAttribute('aria-label', 'Play');
  play.title = 'Play / pause (click the plot to set where)';
  play.innerHTML = icon('nbwf-go', 'M8 5.5v13l10.5-6.5z') + icon('nbwf-pause', 'M7 5h3.5v14H7zM13.5 5H17v14h-3.5z');
  const time = el('span', 'nbwf-time');
  const read = el('span', 'nbwf-read');
  const zoomBox = el('span', 'nbwf-zoom');
  const button = (text: string, label: string, onclick: () => void) => {
    const b = el('button', '', text) as HTMLButtonElement;
    b.type = 'button';
    if (text !== label) b.setAttribute('aria-label', label);
    b.title = label;
    b.addEventListener('click', onclick);
    zoomBox.appendChild(b);
  };
  const plotEl = el('div', 'nbwf-plot');
  const overview = el('canvas', 'nbwf-overview') as HTMLCanvasElement;
  overview.setAttribute('aria-label', 'Overview of the clip; drag to move the view');
  const cap = el('div', 'nbwf-cap');
  const audio = el('audio') as HTMLAudioElement;
  audio.preload = 'auto';
  audio.hidden = true;
  audio.src = input.audioSrc;
  bar.append(play, time, read, zoomBox);
  root.append(bar, plotEl, overview, cap, audio);
  box.replaceChildren(root);

  const css = (name: string) => getComputedStyle(root).getPropertyValue(name).trim();
  const alpha = (color: string, a: string) => (/^#[0-9a-f]{6}$/i.test(color) ? color + a : color);
  const colorOf = (k: number) => (k < nch ? 'var(--muted)' : `var(--s${((k - nch + 1) % 8) + 1})`);
  const swatch = (k: number) => {
    const i = el('i', 'nbwf-sw');
    i.style.background = colorOf(k);
    return i;
  };
  const clock = (t: number, digits: number) => {
    const m = Math.floor(t / 60 + 1e-9);
    const s = Math.max(0, t - m * 60)
      .toFixed(digits)
      .padStart(digits ? digits + 3 : 2, '0');
    return `${m}:${s}`;
  };
  const tick = (t: number, step: number) => clock(t, Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9))));
  const value = (v: number) => {
    if (!Number.isFinite(v)) return '–';
    const a = Math.abs(v);
    return a !== 0 && (a < 1e-3 || a >= 1e5) ? v.toExponential(3) : String(Number(v.toPrecision(5)));
  };
  const showTime = () => (time.textContent = `${clock(audio.currentTime, 3)} / ${clock(duration, 3)}`);
  const hint = () =>
    read.replaceChildren(
      el('span', 'nbwf-hint', 'Drag to zoom · Ctrl/⌘ + wheel zooms · Shift + wheel scrolls · double-click shows all'),
    );

  // the legend and the caption, with the clip's length and rate
  input.names.forEach((name, k) => {
    const s = el('span', 'nbwf-sig');
    s.append(swatch(nch + k), name);
    cap.append(s);
  });
  cap.append([input.caption, `${duration.toFixed(2)} s`, `${rate / 1000} kHz`].filter(Boolean).join(' · '));

  const viewData = (u: uPlot | null): uPlot.AlignedData => {
    const columns = Math.max(64, Math.round(u ? u.bbox.width : plotEl.clientWidth * devicePixelRatio));
    const [x, ...ys] = kit.decimate(pyramids, view[0] * rate - 1, view[1] * rate + 2, columns);
    return [(x as number[]).map((i) => i / rate), ...ys] as uPlot.AlignedData;
  };

  // the whole clip under the plot, with the part in view highlighted; its waveform is drawn once per
  // size and theme, then only the view box moves
  let overviewBase: HTMLCanvasElement | null = null;
  let overviewKey = '';
  const drawOverview = () => {
    if (!plot) return;
    const dpr = devicePixelRatio;
    const width = overview.clientWidth;
    const left = plot.bbox.left / dpr;
    const w = plot.bbox.width / dpr;
    const h = 28;
    const key = `${width} ${w} ${dpr} ${css('--text')}`;
    if (!overviewBase || key !== overviewKey) {
      overviewKey = key;
      overviewBase = document.createElement('canvas');
      overviewBase.width = Math.round(width * dpr);
      overviewBase.height = Math.round(h * dpr);
      const base = overviewBase.getContext('2d')!;
      base.scale(dpr, dpr);
      base.fillStyle = alpha(css('--text') || '#888888', '59');
      const columns = Math.max(1, Math.round(w * dpr));
      const n = data.channels[0].length;
      for (let c = 0; c < columns; c++) {
        const a = Math.floor((n * c) / columns);
        const b = Math.max(a + 1, Math.floor((n * (c + 1)) / columns));
        let lo = Infinity;
        let hi = -Infinity;
        for (let k = 0; k < nch; k++) {
          const [min, max] = pyramids[k].extent(a, b);
          if (min < lo) lo = min;
          if (max > hi) hi = max;
        }
        if (!(lo <= hi)) continue;
        base.fillRect(left + c / dpr, h / 2 - hi * (h / 2), 1 / dpr, Math.max(1 / dpr, (hi - lo) * (h / 2)));
      }
    }
    overview.width = overviewBase.width;
    overview.height = overviewBase.height;
    const ctx = overview.getContext('2d')!;
    ctx.drawImage(overviewBase, 0, 0);
    ctx.scale(dpr, dpr);
    const a = left + (view[0] / duration) * w;
    const b = left + (view[1] / duration) * w;
    const accent = css('--nbwf-accent');
    ctx.fillStyle = alpha(accent, '29');
    ctx.fillRect(a, 0, Math.max(2, b - a), h);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(a + 0.5, 0.5, Math.max(2, b - a) - 1, h - 1);
  };

  const refresh = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!plot) return;
      plot.setData(viewData(plot), false);
      plot.setScale('x', { min: view[0], max: view[1] });
      drawOverview();
    });
  };
  const setView = (a: number, b: number) => {
    const span = Math.min(Math.max(b - a, Math.min(duration, 32 / rate)), duration);
    const start = Math.min(Math.max(a, 0), duration - span);
    view = Number.isFinite(start) ? [start, start + span] : [0, duration];
    refresh();
  };
  const zoom = (factor: number, at = (view[0] + view[1]) / 2) =>
    setView(at - (at - view[0]) * factor, at + (view[1] - at) * factor);

  const build = () => {
    plot?.destroy();
    const muted = css('--muted');
    const grid = css('--grid');
    const font = `11px ${css('--nbwf-mono')}`;
    const wave = alpha(css('--text') || '#888888', '88');
    const colors = labels.map((_, k) => (k < nch ? wave : css(`--s${((k - nch + 1) % 8) + 1}`) || '#e69f00'));
    const zoomedIn = (u: uPlot) => (u.scales.x.max! - u.scales.x.min!) * rate < u.bbox.width / devicePixelRatio / 6;
    const series: uPlot.Series[] = [{}];
    labels.forEach((label, k) =>
      series.push({
        label,
        scale: k >= nch && own ? 'v' : 'y',
        stroke: colors[k],
        width: k < nch ? 1 : 1.5,
        points: { show: zoomedIn, size: k < nch ? 4 : 5, fill: colors[k], stroke: colors[k] },
      }),
    );
    const axis = (scale: string, side: number): uPlot.Axis => ({
      scale,
      side,
      stroke: muted,
      grid: { show: side === 3, stroke: grid, width: 1 },
      ticks: { show: false },
      size: 50,
      font,
      values: (u, splits) => splits.map((v) => String(Number(v.toPrecision(3)))),
    });
    plot = new UPlot(
      {
        width: plotEl.clientWidth || 600,
        height,
        series,
        legend: { show: false },
        padding: [10, own ? 0 : 28, 0, 0],
        scales: {
          x: { time: false, auto: false, range: () => view },
          y: { auto: false, range: [-1, 1] },
          v: { auto: false, range: [input.range[0], input.range[1]] },
        },
        axes: [
          {
            stroke: muted,
            grid: { stroke: grid, width: 1 },
            ticks: { show: false },
            size: 32,
            space: 110,
            font,
            values: (u, splits, _axis, _space, step) => splits.map((v) => tick(v, step)),
          },
          axis('y', 3),
          ...(own ? [axis('v', 1)] : []),
        ],
        cursor: {
          y: false,
          drag: { x: true, y: false, setScale: false },
          points: { show: false },
          bind: {
            dblclick: () => () => {
              setView(0, duration);
              return null;
            },
            mouseup: (u, _target, handler) => (e: MouseEvent) => {
              if (u.select.width === 0 && u.cursor.left !== undefined && u.cursor.left >= 0) {
                audio.currentTime = u.posToVal(u.cursor.left, 'x');
                showTime();
                u.redraw(false, false);
              }
              return handler(e);
            },
          },
        },
        hooks: {
          setSelect: [
            (u) => {
              if (u.select.width > 4)
                setView(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x'));
              u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            },
          ],
          setCursor: [
            (u) => {
              const left = u.cursor.left;
              if (left === undefined || left < 0) {
                hint();
                for (const d of dots) d.style.display = 'none';
                return;
              }
              const i = Math.min(input.samples - 1, Math.max(0, Math.round(u.posToVal(left, 'x') * rate)));
              const span = view[1] - view[0];
              const digits = span < 0.02 ? 5 : span < 0.2 ? 4 : span < 5 ? 3 : 2;
              // the time and sample, then each series' value at it, with a dot where its line goes through it
              const parts: Node[] = [el('span', 'nbwf-at', `${clock(i / rate, digits)} · #${i}`)];
              const x = u.valToPos(i / rate, 'x');
              labels.forEach((label, k) => {
                const v = el('span', 'nbwf-val');
                v.append(swatch(k), `${label} `, el('b', '', value(values[k][i])));
                parts.push(v);
                const y = u.valToPos(values[k][i], k >= nch && own ? 'v' : 'y');
                const inside = Number.isFinite(y) && y >= 0 && y <= u.bbox.height / devicePixelRatio;
                dots[k].style.display = inside ? 'block' : 'none';
                dots[k].style.transform = `translate(${x}px, ${y}px)`;
              });
              read.replaceChildren(...parts);
            },
          ],
          draw: [
            (u) => {
              // the zero line and the playhead
              const ctx = u.ctx;
              const { left, top, width, height: h } = u.bbox;
              ctx.save();
              ctx.fillStyle = alpha(muted, '59');
              ctx.fillRect(left, Math.round(u.valToPos(0, 'y', true)), width, devicePixelRatio);
              const px = Math.round(u.valToPos(audio.currentTime, 'x', true));
              if (audio.currentTime > 0 && px >= left && px <= left + width) {
                ctx.fillStyle = css('--nbwf-accent');
                ctx.fillRect(px, top, 1.5 * devicePixelRatio, h);
              }
              ctx.restore();
            },
          ],
        },
      },
      viewData(null),
      plotEl,
    );
    dots = colors.map((color) => {
      const dot = el('div', 'nbwf-dot');
      dot.style.background = color;
      plot!.over.appendChild(dot);
      return dot;
    });
    plot.over.addEventListener(
      'wheel',
      (e: WheelEvent) => {
        if (!plot) return;
        const span = view[1] - view[0];
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          zoom(Math.exp(e.deltaY * 0.0025), plot.posToVal(e.offsetX, 'x'));
        } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
          e.preventDefault();
          const d = (e.shiftKey ? e.deltaY || e.deltaX : e.deltaX) / (plot.bbox.width / devicePixelRatio);
          setView(view[0] + d * span, view[1] + d * span);
        }
      },
      { passive: false },
    );
    overviewBase = null;
    refresh();
  };

  button('−', 'Zoom out', () => zoom(2));
  button('+', 'Zoom in', () => zoom(0.5));
  button('Fit', 'Fit', () => setView(0, duration));

  // the playhead follows the audio, a page at a time
  const follow = () => {
    showTime();
    root.classList.toggle('playing', !audio.paused);
    play.setAttribute('aria-label', audio.paused ? 'Play' : 'Pause');
    if (!plot) return;
    const t = audio.currentTime;
    const span = view[1] - view[0];
    if (!audio.paused && (t > view[1] || t < view[0]) && span < duration) setView(t, t + span);
    plot.redraw(false, false);
    if (!audio.paused) requestAnimationFrame(follow);
  };
  audio.addEventListener('play', follow);
  audio.addEventListener('pause', follow);
  audio.addEventListener('seeked', follow);
  play.addEventListener('click', () => {
    if (!audio.paused) return audio.pause();
    if (audio.currentTime >= duration - 1e-3) audio.currentTime = 0;
    void audio.play();
  });

  // pressing or dragging on the overview centers the view there
  const onOverview = (e: PointerEvent) => {
    if (!plot || !(e.buttons & 1)) return;
    overview.setPointerCapture(e.pointerId);
    const t = ((e.offsetX - plot.bbox.left / devicePixelRatio) / (plot.bbox.width / devicePixelRatio)) * duration;
    const span = view[1] - view[0];
    setView(t - span / 2, t + span / 2);
  };
  overview.addEventListener('pointerdown', onOverview);
  overview.addEventListener('pointermove', onOverview);
  const resize = new ResizeObserver(() => {
    if (plot && plotEl.clientWidth && plotEl.clientWidth !== plot.width) {
      plot.setSize({ width: plotEl.clientWidth, height });
      refresh();
    }
  });
  resize.observe(plotEl);
  // new colors when the light/dark theme changes
  const theme = new MutationObserver(build);
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  showTime();
  hint();
  build();
  return {
    restyle: build,
    destroy: () => {
      audio.pause();
      resize.disconnect();
      theme.disconnect();
      cancelAnimationFrame(frame);
      plot?.destroy();
      plot = null;
      box.replaceChildren();
    },
  };
}
