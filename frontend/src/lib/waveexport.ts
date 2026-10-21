// A waveform figure in an exported report: the same plot as the viewer's (WaveformPlot.svelte), drawn
// with uPlot from the WAV in the figure's <audio> element and the signals in the <script> next to it.

import type uPlot from 'uplot';
import type { waveformKit } from './waveform';

type Kit = ReturnType<typeof waveformKit>;

/**
 * Draw the exported waveform figure in `box`: accurate at every zoom (M4, as in the viewer), with the
 * values at a sample under the pointer, drag or Ctrl/⌘ + wheel to zoom, Shift + wheel to scroll,
 * double-click or Fit to see it all, and the audio's playhead, set by clicking. It uses nothing from
 * outside itself: the export embeds it as text (`mountWaveform.toString()`).
 */
export function mountWaveform(box: HTMLElement, kit: Kit, UPlot: typeof uPlot): void {
  const meta = JSON.parse(box.dataset.meta || '{}') as { names: string[]; range: [number, number]; samples: number };
  const audio = box.querySelector('audio')!;
  const plotEl = box.querySelector<HTMLElement>('.nbwf-plot')!;
  const read = box.querySelector<HTMLElement>('.nbwf-read')!;
  const hint = read.textContent || '';
  const height = 240;

  const bytes = (b64: string) => {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  };
  const wav = bytes(audio.src.slice(audio.src.indexOf(',') + 1));
  const sig = bytes((box.querySelector('script')!.textContent || '').trim());
  const all = new Uint8Array(wav.length + sig.length);
  all.set(wav);
  all.set(sig, wav.length);
  const data = kit.parseWaveform(all.buffer, wav.length, meta.names, meta.samples);
  const values = [...data.channels, ...data.signals];
  const pyramids = values.map((v) => new kit.Pyramid(v));
  const rate = data.sampleRate;
  const duration = data.channels[0].length / rate;
  const nch = data.channels.length;
  const labels = [...(nch > 1 ? data.channels.map((_, c) => `ch ${c + 1}`) : ['audio']), ...meta.names];
  const own = meta.range[0] !== -1 || meta.range[1] !== 1;
  let view: [number, number] = [0, duration];
  let plot: uPlot | null = null;
  let frame = 0;

  const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const alpha = (color: string, a: string) => (/^#[0-9a-f]{6}$/i.test(color) ? color + a : color);
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

  const viewData = (u: uPlot | null): uPlot.AlignedData => {
    const columns = Math.max(64, Math.round(u ? u.bbox.width : plotEl.clientWidth * devicePixelRatio));
    const [x, ...ys] = kit.decimate(pyramids, view[0] * rate - 1, view[1] * rate + 2, columns);
    return [(x as number[]).map((i) => i / rate), ...ys] as uPlot.AlignedData;
  };
  const refresh = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!plot) return;
      plot.setData(viewData(plot), false);
      plot.setScale('x', { min: view[0], max: view[1] });
    });
  };
  const setView = (a: number, b: number) => {
    const span = Math.min(Math.max(b - a, Math.min(duration, 32 / rate)), duration);
    const start = Math.min(Math.max(a, 0), duration - span);
    view = Number.isFinite(start) ? [start, start + span] : [0, duration];
    refresh();
  };

  const build = () => {
    plot?.destroy();
    const muted = css('--muted');
    const grid = css('--grid');
    const font = `11px ui-monospace, Menlo, monospace`;
    const wave = alpha(css('--text') || '#888888', '88');
    const zoomedIn = (u: uPlot) => (u.scales.x.max! - u.scales.x.min!) * rate < u.bbox.width / devicePixelRatio / 6;
    const series: uPlot.Series[] = [{}];
    labels.forEach((label, k) => {
      const color = k < nch ? wave : css(`--s${((k - nch + 1) % 8) + 1}`) || '#e69f00';
      series.push({
        label,
        scale: k >= nch && own ? 'v' : 'y',
        stroke: color,
        width: k < nch ? 1 : 1.5,
        points: { show: zoomedIn, size: k < nch ? 4 : 5, fill: color, stroke: color },
      });
    });
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
          v: { auto: false, range: [meta.range[0], meta.range[1]] },
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
                read.textContent = hint;
                return;
              }
              const i = Math.min(meta.samples - 1, Math.max(0, Math.round(u.posToVal(left, 'x') * rate)));
              const span = view[1] - view[0];
              const digits = span < 0.02 ? 5 : span < 0.2 ? 4 : span < 5 ? 3 : 2;
              read.textContent = [
                `${clock(i / rate, digits)} · #${i}`,
                ...labels.map((l, k) => `${l} ${value(values[k][i])}`),
              ].join('   ');
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
                ctx.fillStyle = css('--link') || '#0b6bcb';
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
    plot.over.addEventListener(
      'wheel',
      (e: WheelEvent) => {
        if (!plot) return;
        const span = view[1] - view[0];
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          const at = plot.posToVal(e.offsetX, 'x');
          const f = Math.exp(e.deltaY * 0.0025);
          setView(at - (at - view[0]) * f, at + (view[1] - at) * f);
        } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
          e.preventDefault();
          const d = (e.shiftKey ? e.deltaY || e.deltaX : e.deltaX) / (plot.bbox.width / devicePixelRatio);
          setView(view[0] + d * span, view[1] + d * span);
        }
      },
      { passive: false },
    );
    refresh();
  };

  // the playhead follows the audio, a page at a time
  const follow = () => {
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
  box.querySelector('.nbwf-fit')?.addEventListener('click', () => setView(0, duration));
  new ResizeObserver(() => {
    if (plot && plotEl.clientWidth && plotEl.clientWidth !== plot.width) {
      plot.setSize({ width: plotEl.clientWidth, height });
      refresh();
    }
  }).observe(plotEl);
  // the file's light/dark switch
  new MutationObserver(build).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  build();
}
