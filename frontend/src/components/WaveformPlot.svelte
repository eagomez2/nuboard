<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy, onMount } from 'svelte';
  import { cssVar, seriesColor, withAlpha } from '../lib/colors';
  import { app } from '../lib/state.svelte';
  import { decimate, parseWaveform, Pyramid, type WaveformData } from '../lib/waveform';

  /**
   * A waveform figure: the audio with its signals over it, drawn with M4 decimation (see
   * lib/waveform.ts) so every zoom shows the samples as they are, down to single samples. Drag to zoom
   * in, Ctrl/⌘ + wheel to zoom around the pointer, Shift + wheel to scroll, double-click to see it
   * all. The overview below shows where the view is in the file. Clicking sets the playhead.
   */
  let {
    url,
    title,
    names,
    range = [-1, 1],
    offset,
    samples,
    height = 260,
  }: {
    url: string;
    title: string;
    names: string[];
    /** The values at the bottom and top of the plot. */
    range?: [number, number];
    /** Bytes of the WAV at the start of the item, then `samples` float32 values per signal. */
    offset: number;
    samples: number;
    height?: number;
  } = $props();

  let box: HTMLDivElement;
  let overview: HTMLCanvasElement;
  let audio: HTMLAudioElement;
  let plot: uPlot | null = null;
  let width = $state(600);
  let data = $state.raw<WaveformData | null>(null);
  let pyramids: Pyramid[] = [];
  let error = $state('');
  let duration = $state(0);
  let view = $state<[number, number]>([0, 0]);
  let playing = $state(false);
  let now = $state(0);
  let audioUrl = $state('');
  // the values under the pointer: time, sample and one value per series
  let hover = $state<{ t: number; i: number; values: number[] } | null>(null);
  let dots: HTMLElement[] = [];
  let refreshFrame = 0;

  const channelNames = $derived(
    data ? (data.channels.length > 1 ? data.channels.map((_, c) => `ch ${c + 1}`) : ['audio']) : [],
  );

  function fmtTime(t: number, span = 10): string {
    const digits = span < 0.02 ? 5 : span < 0.2 ? 4 : span < 5 ? 3 : 2;
    const m = Math.floor(t / 60);
    const s = (t - m * 60).toFixed(digits).padStart(digits + 3, '0');
    return `${m}:${s}`;
  }

  /** An axis label: as many decimals as the step between labels needs. */
  function fmtTick(t: number, step: number): string {
    const digits = Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)));
    const m = Math.floor(t / 60 + 1e-9);
    const s = Math.max(0, t - m * 60)
      .toFixed(digits)
      .padStart(digits ? digits + 3 : 2, '0');
    return `${m}:${s}`;
  }

  function fmtValue(v: number): string {
    if (!Number.isFinite(v)) return '–';
    const a = Math.abs(v);
    return a !== 0 && (a < 1e-3 || a >= 1e5) ? v.toExponential(3) : String(Number(v.toPrecision(5)));
  }

  /** The data for the current view, decimated to one bucket per device pixel column. */
  function viewData(u: uPlot | null): uPlot.AlignedData {
    if (!data) return [[]];
    const rate = data.sampleRate;
    const columns = Math.max(64, Math.round(u ? u.bbox.width : width * devicePixelRatio));
    // one sample either side, so the line runs to the edges
    const [x, ...ys] = decimate(pyramids, view[0] * rate - 1, view[1] * rate + 2, columns);
    return [(x as number[]).map((i) => i / rate), ...ys] as uPlot.AlignedData;
  }

  function refresh() {
    if (refreshFrame) return;
    refreshFrame = requestAnimationFrame(() => {
      refreshFrame = 0;
      if (!plot) return;
      plot.setData(viewData(plot), false);
      plot.setScale('x', { min: view[0], max: view[1] });
      drawOverview();
    });
  }

  function setView(a: number, b: number) {
    const min = data ? Math.min(duration, 32 / data.sampleRate) : 0;
    let span = Math.min(Math.max(b - a, min), duration);
    let start = Math.min(Math.max(a, 0), duration - span);
    if (!Number.isFinite(start)) [start, span] = [0, duration];
    view = [start, start + span];
    refresh();
  }

  function zoom(factor: number, at = (view[0] + view[1]) / 2) {
    const [a, b] = view;
    setView(at - (at - a) * factor, at + (b - at) * factor);
  }

  function build() {
    plot?.destroy();
    plot = null;
    if (!box || !data) return;
    const muted = cssVar('--muted');
    const grid = cssVar('--grid');
    const font = `11px ${cssVar('--mono') || 'monospace'}`;
    const own = range[0] !== -1 || range[1] !== 1;
    const wave = withAlpha(cssVar('--text') || '#888', app.theme === 'dark' ? 0.55 : 0.5);
    const series: uPlot.Series[] = [{}];
    const zoomedIn = (u: uPlot) => {
      const n = (u.scales.x.max! - u.scales.x.min!) * data!.sampleRate;
      return n < u.bbox.width / devicePixelRatio / 6;
    };
    channelNames.forEach((label) =>
      series.push({ label, stroke: wave, width: 1, points: { show: zoomedIn, size: 4, fill: wave, stroke: wave } }),
    );
    names.forEach((label, k) => {
      const color = seriesColor(k + 1);
      series.push({
        label,
        scale: own ? 'v' : 'y',
        stroke: color,
        width: 1.5,
        points: { show: zoomedIn, size: 5, fill: color, stroke: color },
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

    const opts: uPlot.Options = {
      title: undefined,
      width,
      height,
      series,
      legend: { show: false },
      padding: [10, own ? 0 : 28, 0, 0],
      scales: {
        x: { time: false, auto: false, range: () => view },
        y: { auto: false, range: [-1, 1] },
        v: { auto: false, range: [range[0], range[1]] },
      },
      axes: [
        {
          stroke: muted,
          grid: { stroke: grid, width: 1 },
          ticks: { show: false },
          size: 32,
          space: 110,
          font,
          values: (u, splits, _axis, _space, step) => splits.map((v) => fmtTick(v, step)),
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
          mouseup: (u, target, handler) => (e: MouseEvent) => {
            if (u.select.width === 0 && hover && audio) {
              audio.currentTime = hover.t;
              now = hover.t;
              u.redraw(false, false);
            }
            return handler(e);
          },
        },
      },
      hooks: {
        setSelect: [
          (u) => {
            if (u.select.width > 4) {
              setView(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x'));
            }
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
          },
        ],
        setCursor: [
          (u) => {
            const left = u.cursor.left;
            if (!data || left === undefined || left < 0) {
              hover = null;
              for (const d of dots) d.style.display = 'none';
              return;
            }
            const t = u.posToVal(left, 'x');
            const i = Math.min(samples - 1, Math.max(0, Math.round(t * data.sampleRate)));
            const all = [...data.channels, ...data.signals];
            hover = { t: i / data.sampleRate, i, values: all.map((s) => s[i]) };
            // a dot on each series at the sample, where the line goes through it
            const x = u.valToPos(i / data.sampleRate, 'x');
            all.forEach((s, k) => {
              const dot = dots[k];
              if (!dot) return;
              const y = u.valToPos(s[i], k < data!.channels.length ? 'y' : own ? 'v' : 'y');
              const inside = Number.isFinite(y) && y >= 0 && y <= u.bbox.height / devicePixelRatio;
              dot.style.display = inside ? 'block' : 'none';
              dot.style.transform = `translate(${x}px, ${y}px)`;
            });
          },
        ],
        draw: [
          (u) => {
            // the zero line and the playhead
            const ctx = u.ctx;
            const { left, top, width: w, height: h } = u.bbox;
            ctx.save();
            const zero = Math.round(u.valToPos(0, 'y', true));
            ctx.fillStyle = withAlpha(muted, 0.35);
            ctx.fillRect(left, zero, w, devicePixelRatio);
            const px = Math.round(u.valToPos(now, 'x', true));
            if (px >= left && px <= left + w && (now > 0 || playing)) {
              ctx.fillStyle = cssVar('--accent');
              ctx.fillRect(px, top, 1.5 * devicePixelRatio, h);
            }
            ctx.restore();
          },
        ],
      },
    };
    plot = new uPlot(opts, viewData(null), box);
    dots = [...channelNames.map(() => wave), ...names.map((_, k) => seriesColor(k + 1))].map((color) => {
      const dot = document.createElement('div');
      dot.className = 'wfdot';
      dot.style.background = color;
      plot!.over.appendChild(dot);
      return dot;
    });
    plot.over.addEventListener('wheel', onWheel, { passive: false });
    refresh();
  }

  // Ctrl/⌘ + wheel (and trackpad pinch) zooms around the pointer, Shift + wheel or a sideways swipe
  // scrolls; a plain wheel scrolls the page
  function onWheel(e: WheelEvent) {
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
  }

  // the overview's waveform, drawn once per size and theme; only the view box moves
  let overviewBase: HTMLCanvasElement | null = null;
  let overviewKey = '';

  /** The whole file (each channel's range per pixel column) with the part in view highlighted. */
  function drawOverview() {
    if (!overview || !data || !plot) return;
    const dpr = devicePixelRatio;
    const left = plot.bbox.left / dpr;
    const w = plot.bbox.width / dpr;
    const h = 28;
    const key = `${width} ${w} ${dpr} ${app.theme} ${app.themeVersion}`;
    if (!overviewBase || key !== overviewKey) {
      overviewKey = key;
      overviewBase = document.createElement('canvas');
      overviewBase.width = Math.round(width * dpr);
      overviewBase.height = Math.round(h * dpr);
      const base = overviewBase.getContext('2d')!;
      base.scale(dpr, dpr);
      const columns = Math.max(1, Math.round(w * dpr));
      const n = data.channels[0].length;
      base.fillStyle = withAlpha(cssVar('--text') || '#888', 0.35);
      for (let c = 0; c < columns; c++) {
        const a = Math.floor((n * c) / columns);
        const b = Math.max(a + 1, Math.floor((n * (c + 1)) / columns));
        let lo = Infinity;
        let hi = -Infinity;
        for (const p of pyramids.slice(0, data.channels.length)) {
          const [min, max] = p.extent(a, b);
          if (min < lo) lo = min;
          if (max > hi) hi = max;
        }
        if (!(lo <= hi)) continue;
        const y0 = h / 2 - hi * (h / 2);
        base.fillRect(left + c / dpr, y0, 1 / dpr, Math.max(1 / dpr, (hi - lo) * (h / 2)));
      }
    }
    overview.width = overviewBase.width;
    overview.height = overviewBase.height;
    overview.style.height = `${h}px`;
    const ctx = overview.getContext('2d')!;
    ctx.drawImage(overviewBase, 0, 0);
    ctx.scale(dpr, dpr);
    const a = left + (view[0] / duration) * w;
    const b = left + (view[1] / duration) * w;
    ctx.fillStyle = withAlpha(cssVar('--accent') || '#0072b2', 0.16);
    ctx.fillRect(a, 0, Math.max(2, b - a), h);
    ctx.strokeStyle = cssVar('--accent');
    ctx.lineWidth = 1;
    ctx.strokeRect(a + 0.5, 0.5, Math.max(2, b - a) - 1, h - 1);
  }

  // drag on the overview moves the view there
  function onOverview(e: PointerEvent) {
    if (!plot || !(e.buttons & 1)) return;
    overview.setPointerCapture(e.pointerId);
    const left = plot.bbox.left / devicePixelRatio;
    const t = ((e.offsetX - left) / (plot.bbox.width / devicePixelRatio)) * duration;
    const span = view[1] - view[0];
    setView(t - span / 2, t + span / 2);
  }

  function togglePlay() {
    if (!audio) return;
    if (audio.paused) {
      if (now >= duration - 1e-3) audio.currentTime = 0;
      void audio.play();
    } else audio.pause();
  }

  // follow the playhead, a page at a time
  let playFrame = 0;
  function tick() {
    playFrame = 0;
    if (!audio || !plot) return;
    now = audio.currentTime;
    const span = view[1] - view[0];
    if (playing && (now > view[1] || now < view[0]) && span < duration) setView(now, now + span);
    plot.redraw(false, false);
    if (playing) playFrame = requestAnimationFrame(tick);
  }

  onMount(() => {
    const ro = new ResizeObserver(() => {
      const w = Math.floor(box?.clientWidth ?? 0);
      if (w > 0 && w !== width) {
        width = w;
        plot?.setSize({ width, height });
        refresh();
      }
    });
    ro.observe(box);
    return () => ro.disconnect();
  });

  // load the item: a new one (the step slider) starts at the whole file
  $effect(() => {
    const target = url;
    error = '';
    fetch(target)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then((buffer) => {
        if (target !== url) return;
        const parsed = parseWaveform(buffer, offset, names, samples);
        data = parsed;
        pyramids = [...parsed.channels, ...parsed.signals].map((v) => new Pyramid(v));
        overviewBase = null;
        duration = parsed.channels[0].length / parsed.sampleRate;
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        audioUrl = URL.createObjectURL(new Blob([buffer.slice(0, offset)], { type: 'audio/wav' }));
        now = 0;
        view = [0, duration];
        width = Math.floor(box?.clientWidth || width);
        // the effect below builds the plot
      })
      .catch((e) => (error = `Could not load the waveform: ${e instanceof Error ? e.message : e}`));
  });

  // a new item, or new colors with the theme
  $effect(() => {
    void [app.theme, app.themeVersion, height];
    if (data) build();
  });

  onDestroy(() => {
    plot?.destroy();
    cancelAnimationFrame(refreshFrame);
    cancelAnimationFrame(playFrame);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  });
</script>

<div class="wf">
  <div class="bar">
    <button
      class="play"
      aria-label={playing ? 'Pause' : 'Play'}
      title="{playing ? 'Pause' : 'Play'} (click the plot to set where)"
      onclick={togglePlay}
      disabled={!audioUrl}
    >
      {#if playing}
        <svg viewBox="0 0 24 24"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" /></svg>
      {:else}
        <svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z" /></svg>
      {/if}
    </button>
    <span class="mono time">{fmtTime(now, 1)} / {fmtTime(duration, 1)}</span>
    <span class="readout mono" aria-live="off">
      {#if hover}
        <span class="faint">{fmtTime(hover.t, view[1] - view[0])} · #{hover.i}</span>
        {#each [...channelNames, ...names] as name, k (name)}
          <span class="val">
            <i
              style="background:{k < channelNames.length
                ? 'var(--muted)'
                : `var(--s${((k - channelNames.length + 1) % 8) + 1})`}"
            ></i>
            {name} <b>{fmtValue(hover.values[k])}</b>
          </span>
        {/each}
      {:else}
        <span class="faint">Drag to zoom · Ctrl/⌘ + wheel zooms · Shift + wheel scrolls · double-click shows all</span>
      {/if}
    </span>
    <span class="zoom">
      <button aria-label="Zoom out" title="Zoom out" onclick={() => zoom(2)}>−</button>
      <button aria-label="Zoom in" title="Zoom in" onclick={() => zoom(0.5)}>+</button>
      <button title="Show the whole file" onclick={() => setView(0, duration)}>Fit</button>
    </span>
  </div>
  {#if error}<div class="faint err">{error}</div>{/if}
  <div class="plot" bind:this={box} role="img" aria-label={title}></div>
  <canvas
    class="overview"
    bind:this={overview}
    onpointerdown={onOverview}
    onpointermove={onOverview}
    aria-label="Overview of {title}; drag to move the view"
  ></canvas>
  <audio
    bind:this={audio}
    src={audioUrl || undefined}
    preload="auto"
    onplay={() => {
      playing = true;
      tick();
    }}
    onpause={() => {
      playing = false;
      tick();
    }}
    onended={() => (playing = false)}
  ></audio>
</div>

<style>
  .wf {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 30px;
    font-size: 12px;
  }
  .play {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    padding: 0;
    display: grid;
    place-items: center;
    background: var(--accent);
    border: 0;
    color: var(--panel);
    flex: none;
  }
  .play svg {
    width: 16px;
    height: 16px;
    fill: currentColor;
  }
  .time {
    flex: none;
  }
  .readout {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .val {
    margin-left: 10px;
  }
  .val i {
    display: inline-block;
    width: 10px;
    height: 3px;
    border-radius: 2px;
    margin-right: 4px;
    vertical-align: middle;
  }
  .zoom {
    display: flex;
    gap: 4px;
    flex: none;
  }
  .zoom button {
    height: 26px;
    min-width: 26px;
    padding: 0 8px;
    font-size: 12px;
  }
  .plot {
    min-width: 0;
  }
  .plot :global(.wfdot) {
    position: absolute;
    left: -4px;
    top: -4px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 1.5px solid var(--panel);
    pointer-events: none;
    display: none;
  }
  .overview {
    width: 100%;
    display: block;
    cursor: grab;
    touch-action: none;
  }
  .faint {
    color: var(--faint);
  }
  .err {
    padding: 12px 0;
  }
  audio {
    display: none;
  }
</style>
