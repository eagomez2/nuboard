<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy, onMount } from 'svelte';
  import type { ChartData } from '../lib/api';
  import { baselineExtent, baselineLines } from '../lib/baselines';
  import { cssVar, withAlpha } from '../lib/colors';
  import { fmtAxis, fmtDuration } from '../lib/format';
  import { ema, robustRange } from '../lib/smooth';

  export interface CursorValue {
    series: number;
    label: string;
    value: number;
    lo: number | null;
    hi: number | null;
  }

  let {
    data,
    smoothing = 0,
    showRaw = true,
    showBands = true,
    robust = true,
    logY = false,
    height = 360,
    compact = false,
    hidden = new Set<string>(),
    highlight = null,
    colorOf,
    syncKey = 'charts',
    themeVersion = 0,
    onCursor,
    onZoom,
    onPin,
    regions = [],
    markers = false,
    pinned = false,
    baselines = false,
    zoom = null,
  }: {
    data: ChartData | null;
    smoothing?: number;
    showRaw?: boolean;
    /** Shade the ranges (group bands, logged low/high, rank min–max) around each curve. */
    showBands?: boolean;
    robust?: boolean;
    logY?: boolean;
    height?: number;
    compact?: boolean;
    hidden?: Set<string>;
    highlight?: string | null;
    colorOf: (label: string, i: number) => string;
    syncKey?: string;
    themeVersion?: number;
    onCursor?: (x: number | null, values: CursorValue[]) => void;
    onZoom?: (range: [number, number] | null) => void;
    onPin?: () => void;
    /** Shaded x ranges, e.g. health alerts: a spike or a throughput drop. */
    regions?: { x0: number; x1: number; label: string }[];
    /** A dot on each curve at the data point under the cursor (as in TensorBoard). */
    markers?: boolean;
    /** The cursor is pinned: the dots stay where they are. */
    pinned?: boolean;
    /** Draw the baselines set with `add_scalar_baseline` as dashed lines. */
    baselines?: boolean;
    /** The x range the data was fetched for, or null for the whole run. */
    zoom?: [number, number] | null;
  } = $props();
  let dots: HTMLElement[] = [];

  let el: HTMLDivElement;
  let plot: uPlot | null = null;
  let width = $state(600);
  let mains: { idx: number; label: string; series: number; lo: number | null; hi: number | null }[] = [];
  let frame = 0;
  // What the user is looking at. It outlives rebuilds (new data, live updates) so the view
  // never jumps; `zoom` only says which x range the data was fetched for.
  let view: { x: [number, number] | null; y: [number, number] | null } = { x: null, y: null };
  let lastZoom = ''; // the zoom this chart last reported, to tell its own changes from outside ones
  let wheelTimer = 0;
  let panned = false;
  // per drawn series: x and smoothed y, to fit the y-axis to what is in view
  let fitXs: ArrayLike<number>[] = [];
  let fitYs: Float64Array[] = [];

  // Shorten text with an ellipsis so it fits in `max` canvas pixels (long run names would run off the plot).
  function fitText(ctx: CanvasRenderingContext2D, text: string, max: number): string {
    if (max <= 0) return '';
    if (ctx.measureText(text).width <= max) return text;
    let lo = 0;
    let hi = text.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (ctx.measureText(text.slice(0, mid) + '…').width <= max) lo = mid;
      else hi = mid - 1;
    }
    return lo ? text.slice(0, lo) + '…' : '';
  }

  function clean(a: ArrayLike<number>): (number | null)[] {
    const out = new Array<number | null>(a.length);
    for (let i = 0; i < a.length; i++) out[i] = Number.isFinite(a[i]) ? a[i] : null;
    return out;
  }

  function xFormatter(kind: string) {
    if (kind === 'relative' || kind === 'active') return (v: number) => fmtDuration(v);
    return (v: number) => fmtAxis(v);
  }

  function build() {
    plot?.destroy();
    plot = null;
    mains = [];
    if (!el || !data || !data.series.length) return;
    const muted = cssVar('--muted');
    const grid = cssVar('--grid');
    const tables: uPlot.AlignedData[] = [];
    const series: uPlot.Series[] = [{}];
    const bands: uPlot.Band[] = [];
    const nanMarks: { x: number; label: string; color: string }[] = [];
    const yValues: Float64Array[] = [];
    const xValues: ArrayLike<number>[] = [];
    let col = 1;
    data.series.forEach((s, i) => {
      if (hidden.has(s.label) || !s.x.length) return;
      const color = colorOf(s.label, i);
      const dim = highlight !== null && highlight !== s.label;
      const smooth = smoothing > 0 ? ema(s.y, smoothing) : s.y;
      const hasBand =
        showBands && (s.band || (s.n ?? 1) > 1) && s.lo.some((v, k) => Number.isFinite(v) && v !== s.y[k]);
      const cols: (number | null)[][] = [];
      if (showRaw && smoothing > 0) {
        cols.push(clean(s.y));
        series.push({
          label: `${s.label} raw`,
          stroke: withAlpha(color, dim ? 0.08 : 0.28),
          width: 1,
          points: { show: false },
        });
      }
      let loIdx: number | null = null;
      let hiIdx: number | null = null;
      if (hasBand) {
        const lo = smoothing > 0 ? ema(s.lo, smoothing) : s.lo;
        const hi = smoothing > 0 ? ema(s.hi, smoothing) : s.hi;
        cols.push(clean(lo), clean(hi));
        loIdx = col + cols.length - 2;
        hiIdx = col + cols.length - 1;
        series.push({ label: `${s.label} lo`, stroke: 'transparent', width: 0, points: { show: false } });
        series.push({ label: `${s.label} hi`, stroke: 'transparent', width: 0, points: { show: false } });
        bands.push({ series: [hiIdx, loIdx], fill: withAlpha(color, dim ? 0.04 : 0.16) });
      }
      cols.push(clean(smooth));
      series.push({
        label: s.label,
        stroke: dim ? withAlpha(color, 0.3) : color,
        width: highlight === s.label ? 2.6 : compact ? 1.5 : 2,
        points: { show: false },
      });
      mains.push({ idx: col + cols.length - 1, label: s.label, series: i, lo: loIdx, hi: hiIdx });
      yValues.push(smooth instanceof Float64Array ? smooth : Float64Array.from(smooth));
      xValues.push(s.x);
      col += cols.length;
      tables.push([s.x as unknown as number[], ...(cols as unknown as number[][])]);
      if (s.nonfinite) {
        for (let k = 0; k < s.y.length; k++)
          if (!Number.isFinite(s.y[k])) {
            nanMarks.push({ x: s.x[k], label: s.label, color });
            break;
          }
      }
    });
    if (!tables.length) return;
    const joined = tables.length === 1 ? tables[0] : uPlot.join(tables);
    const zkey = zoom ? `${zoom[0]}~${zoom[1]}` : '';
    if (zkey !== lastZoom) {
      // zoom set from outside (the URL, Reset zoom, an alert): show that range
      view = { x: zoom ? [zoom[0], zoom[1]] : null, y: null };
      lastZoom = zkey;
    }
    fitXs = xValues;
    fitYs = yValues;
    const lines = baselines ? baselineLines(data.series, hidden) : [];
    const extent = baselineExtent(lines, logY);
    const xf = xFormatter(data.xKind);
    const errColor = cssVar('--err');

    const opts: uPlot.Options = {
      width,
      height,
      series,
      bands,
      legend: { show: false },
      padding: compact ? [6, 8, 0, 0] : [12, 12, 0, 4],
      scales: {
        x: { time: data.xKind === 'time' },
        y: {
          distr: logY ? 3 : 1,
          range: (u, min, max) => {
            if (view.y) return logY ? [Math.max(view.y[0], 1e-12), view.y[1]] : view.y;
            let range = robust && !logY ? robustRange(inView(u.scales.x.min, u.scales.x.max)) : null;
            if (range && extent && (extent[0] < range[0] || extent[1] > range[1])) {
              // keep the baselines in view, with the same margin the range has
              const pad = (Math.max(range[1], extent[1]) - Math.min(range[0], extent[0])) * 0.06;
              range = [Math.min(range[0], extent[0] - pad), Math.max(range[1], extent[1] + pad)];
            }
            if (range) return range;
            if (extent) {
              min = Math.min(min, extent[0]);
              max = Math.max(max, extent[1]);
            }
            if (logY) return [Math.max(min, 1e-12), max];
            const pad = (max - min || Math.abs(max) || 1) * 0.06;
            return [min - pad, max + pad];
          },
        },
      },
      axes: [
        {
          stroke: muted,
          grid: { stroke: grid, width: 1 },
          ticks: { show: false },
          size: compact ? 28 : 40,
          font: `${compact ? 10 : 12}px ${cssVar('--mono') || 'monospace'}`,
          values: data.xKind === 'time' ? undefined : (u, splits) => splits.map(xf),
        },
        {
          stroke: muted,
          grid: { stroke: grid, width: 1 },
          ticks: { show: false },
          size: compact ? 44 : 56,
          font: `${compact ? 10 : 12}px ${cssVar('--mono') || 'monospace'}`,
          values: (u, splits) => splits.map(fmtAxis),
        },
      ],
      cursor: {
        sync: { key: syncKey, setSeries: false },
        drag: { x: true, y: false, setScale: true },
        points: { show: false },
        bind: {
          dblclick: () => () => {
            resetView();
            return null;
          },
          mousedown: (u, target, handler) => (e: MouseEvent) => {
            if (e.shiftKey && onZoom && e.button === 0) {
              startPan(e);
              return null;
            }
            return handler(e);
          },
          mouseup: (u, target, handler) => (e: MouseEvent) => {
            if (panned) {
              panned = false;
              return null;
            }
            if (u.select.width === 0) onPin?.();
            return handler(e);
          },
        },
      },
      hooks: {
        setSelect: [
          (u) => {
            if (u.select.width > 4) {
              const a = u.posToVal(u.select.left, 'x');
              const b = u.posToVal(u.select.left + u.select.width, 'x');
              view = { x: [a, b], y: null };
              report(0);
            }
          },
        ],
        setCursor: [
          (u) => {
            if (!onCursor && !markers) return;
            const idx = u.cursor.idx;
            const moveDots = markers && !pinned;
            if (idx === null || idx === undefined) {
              if (moveDots) for (const d of dots) d.style.display = 'none';
              return onCursor?.(null, []);
            }
            const x = u.data[0][idx];
            const values: CursorValue[] = [];
            for (const [i, m] of mains.entries()) {
              const col = u.data[m.idx] as (number | null)[];
              let k = idx;
              let found: number | null = col[k] ?? null;
              for (let d = 1; found === null && d < 400; d++) {
                if (col[idx - d] != null) {
                  k = idx - d;
                  found = col[k] as number;
                } else if (col[idx + d] != null) {
                  k = idx + d;
                  found = col[k] as number;
                }
              }
              const dot = dots[i];
              if (moveDots && dot) {
                const left = found === null ? NaN : u.valToPos(u.data[0][k], 'x');
                const top = found === null ? NaN : u.valToPos(found, 'y');
                const inside = left >= 0 && left <= u.bbox.width / devicePixelRatio && top >= 0;
                dot.style.display = inside && top <= u.bbox.height / devicePixelRatio ? 'block' : 'none';
                dot.style.transform = `translate(${left}px, ${top}px)`;
              }
              if (found !== null) {
                values.push({
                  series: m.series,
                  label: m.label,
                  value: found,
                  lo: m.lo !== null ? ((u.data[m.lo] as (number | null)[])[k] ?? null) : null,
                  hi: m.hi !== null ? ((u.data[m.hi] as (number | null)[])[k] ?? null) : null,
                });
              }
            }
            onCursor?.(x, values);
          },
        ],
        draw: [
          (u) => {
            if (!lines.length) return;
            const ctx = u.ctx;
            const dpr = devicePixelRatio;
            const left = u.bbox.left;
            const right = left + u.bbox.width;
            const top = u.bbox.top;
            const bottom = top + u.bbox.height;
            const y = (v: number) => Math.min(Math.max(u.valToPos(v, 'y', true), top), bottom);
            ctx.save();
            for (const line of lines) {
              if (logY && line.value <= 0) continue;
              // one run: its color; shared by several: gray
              const color =
                line.series.length === 1 ? colorOf(line.labels[0], line.series[0]) : cssVar('--muted') || '#888';
              const dim = highlight !== null && !line.labels.includes(highlight);
              if (line.low !== undefined && line.high !== undefined && (!logY || line.low > 0)) {
                const a = y(line.high);
                const b = y(line.low);
                ctx.fillStyle = withAlpha(color, dim ? 0.03 : 0.09);
                ctx.fillRect(left, a, right - left, b - a);
              }
              const py = Math.round(u.valToPos(line.value, 'y', true));
              if (py < top || py > bottom) continue;
              ctx.strokeStyle = withAlpha(color, dim ? 0.25 : 0.9);
              ctx.lineWidth = (highlight !== null && !dim ? 2 : 1.5) * dpr;
              ctx.setLineDash([6 * dpr, 4 * dpr]);
              ctx.beginPath();
              ctx.moveTo(left, py);
              ctx.lineTo(right, py);
              ctx.stroke();
              if (!compact && !dim) {
                ctx.setLineDash([]);
                ctx.fillStyle = color;
                ctx.font = `${11 * dpr}px ${cssVar('--mono') || 'monospace'}`;
                ctx.textAlign = 'right';
                ctx.fillText('Baseline', right - 6 * dpr, py - 5 * dpr);
              }
            }
            ctx.restore();
          },
          (u) => {
            if (!regions.length) return;
            const ctx = u.ctx;
            ctx.save();
            const warn = cssVar('--warn');
            const dpr = devicePixelRatio;
            for (const r of regions) {
              let a = Math.round(u.valToPos(r.x0, 'x', true));
              let b = Math.round(u.valToPos(r.x1, 'x', true));
              const left = u.bbox.left;
              const right = left + u.bbox.width;
              if (b < left || a > right) continue;
              a = Math.max(a, left);
              b = Math.min(Math.max(b, a + 3 * dpr), right);
              ctx.fillStyle = withAlpha(warn, 0.12);
              ctx.fillRect(a, u.bbox.top, b - a, u.bbox.height);
              ctx.fillStyle = warn;
              ctx.fillRect(a, u.bbox.top + u.bbox.height - 3 * dpr, b - a, 3 * dpr);
              if (!compact) {
                ctx.font = `${11 * dpr}px ${cssVar('--mono') || 'monospace'}`;
                ctx.textAlign = 'left';
                ctx.fillText(
                  fitText(ctx, r.label, right - a - 8 * dpr),
                  a + 4 * dpr,
                  u.bbox.top + u.bbox.height - 8 * dpr,
                );
              }
            }
            ctx.restore();
          },
          (u) => {
            if (!nanMarks.length) return;
            const ctx = u.ctx;
            ctx.save();
            for (const mark of nanMarks) {
              const px = Math.round(u.valToPos(mark.x, 'x', true));
              if (px < u.bbox.left || px > u.bbox.left + u.bbox.width) continue;
              ctx.strokeStyle = mark.color;
              ctx.setLineDash([4, 4]);
              ctx.lineWidth = devicePixelRatio;
              ctx.beginPath();
              ctx.moveTo(px, u.bbox.top);
              ctx.lineTo(px, u.bbox.top + u.bbox.height);
              ctx.stroke();
              if (!compact) {
                ctx.setLineDash([]);
                ctx.fillStyle = errColor;
                ctx.font = `${12 * devicePixelRatio}px ${cssVar('--mono') || 'monospace'}`;
                // label to the left of the line, or to the right when the line sits near the left edge
                const gap = 6 * devicePixelRatio;
                const leftRoom = px - gap - u.bbox.left;
                const rightRoom = u.bbox.left + u.bbox.width - px - gap;
                const onLeft = leftRoom >= Math.min(rightRoom, 160 * devicePixelRatio);
                ctx.textAlign = onLeft ? 'right' : 'left';
                ctx.fillText(
                  fitText(ctx, `NaN · ${mark.label}`, onLeft ? leftRoom : rightRoom),
                  onLeft ? px - gap : px + gap,
                  u.bbox.top + 14 * devicePixelRatio,
                );
              }
            }
            ctx.restore();
          },
        ],
      },
    };
    plot = new uPlot(opts, joined, el);
    if (view.x) plot.setScale('x', { min: view.x[0], max: view.x[1] });
    if (onZoom) plot.over.addEventListener('wheel', onWheel, { passive: false });
    dots = markers
      ? mains.map((m) => {
          const d = document.createElement('div');
          d.className = 'nb-dot';
          d.style.background = (series[m.idx].stroke as string) ?? '';
          plot!.over.append(d);
          return d;
        })
      : [];
  }

  /** Smoothed y values whose x is in [lo, hi], per series (all of them without a range). */
  function inView(lo: number | null | undefined, hi: number | null | undefined): Float64Array[] {
    if (lo == null || hi == null) return fitYs;
    return fitYs.map((ys, i) => {
      const xs = fitXs[i];
      let a = 0;
      while (a < xs.length && xs[a] < lo) a++;
      let b = xs.length;
      while (b > a && xs[b - 1] > hi) b--;
      return ys.subarray(a, b);
    });
  }

  // y is zoomed and panned in log space on a log axis
  const toY = (v: number) => (logY ? Math.log10(Math.max(v, 1e-300)) : v);
  const fromY = (v: number) => (logY ? 10 ** v : v);

  /** Show x and y; a null y fits the y-axis to the data in view. */
  function setView(x: [number, number], y: [number, number] | null) {
    const u = plot;
    if (!u) return;
    view = { x, y };
    u.batch(() => {
      u.setScale('x', { min: x[0], max: x[1] });
      if (y) u.setScale('y', { min: y[0], max: y[1] });
    });
  }

  /** Tell the page the x range in view (after `delay` ms of quiet), so it fetches finer data. */
  function report(delay: number) {
    clearTimeout(wheelTimer);
    wheelTimer = window.setTimeout(() => {
      if (!view.x) return;
      let [a, b] = view.x;
      // round to ~5 significant digits of the span, to keep the URL readable
      const digits = Math.min(Math.max(4 - Math.floor(Math.log10(b - a)), 0), 20);
      [a, b] = [Number(a.toFixed(digits)), Number(b.toFixed(digits))];
      lastZoom = `${a}~${b}`;
      onZoom?.([a, b]);
    }, delay);
  }

  function resetView() {
    clearTimeout(wheelTimer);
    view = { x: null, y: null };
    const had = lastZoom !== '';
    lastZoom = '';
    if (had) onZoom?.(null);
    else schedule();
  }

  function currentScales(u: uPlot): [[number, number], [number, number]] | null {
    const { min: x0, max: x1 } = u.scales.x;
    const { min: y0, max: y1 } = u.scales.y;
    if (x0 == null || x1 == null || y0 == null || y1 == null || !(x1 > x0) || !(y1 > y0)) return null;
    return [
      [x0, x1],
      [y0, y1],
    ];
  }

  /**
   * Ctrl/⌘ + wheel (or a trackpad pinch) zooms x around the cursor, past the data if you
   * like, with y fitted to what is in view (unless y was panned or zoomed); Alt + wheel
   * zooms both axes, as in TensorBoard; Shift + wheel pans along x. The view moves at once
   * and the data for the new x range is fetched when the wheel stops.
   */
  function onWheel(e: WheelEvent) {
    const u = plot;
    if (!u) return;
    const zooming = e.ctrlKey || e.metaKey || e.altKey;
    if (!zooming && !e.shiftKey) return;
    const now = currentScales(u);
    if (!now) return;
    e.preventDefault();
    const [[x0, x1], [y0, y1]] = now;
    const delta = (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1) * (e.deltaY || e.deltaX);
    if (zooming) {
      const f = Math.min(Math.max(Math.exp(delta * 0.002), 0.5), 2);
      const ax = u.posToVal(e.offsetX, 'x');
      const x: [number, number] = [ax - (ax - x0) * f, ax + (x1 - ax) * f];
      if (e.altKey) {
        const ay = toY(u.posToVal(e.offsetY, 'y'));
        const [ly0, ly1] = [toY(y0), toY(y1)];
        setView(x, [fromY(ay - (ay - ly0) * f), fromY(ay + (ly1 - ay) * f)]);
      } else setView(x, view.y);
    } else {
      const shift = (x1 - x0) * Math.min(Math.max(delta * 0.001, -0.25), 0.25);
      setView([x0 + shift, x1 + shift], view.y);
    }
    report(250);
  }

  /** Shift + drag pans the view on both axes. */
  function startPan(e: MouseEvent) {
    const u = plot;
    const now = u && currentScales(u);
    if (!u || !now) return;
    const [[x0, x1], [y0, y1]] = now;
    const [ly0, ly1] = [toY(y0), toY(y1)];
    const w = u.over.clientWidth || 1;
    const h = u.over.clientHeight || 1;
    const sx = e.clientX;
    const sy = e.clientY;
    panned = false;
    const move = (ev: MouseEvent) => {
      const dx = ((ev.clientX - sx) / w) * (x1 - x0);
      const dy = ((ev.clientY - sy) / h) * (ly1 - ly0);
      if (dx || dy) panned = true;
      setView([x0 - dx, x1 - dx], [fromY(ly0 + dy), fromY(ly1 + dy)]);
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      u.over.style.cursor = '';
      if (panned) report(0);
    };
    u.over.style.cursor = 'grabbing';
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }

  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(build);
  }

  $effect(() => {
    // Rebuild when anything that changes series styling or data changes.
    void [
      data,
      smoothing,
      showRaw,
      showBands,
      robust,
      logY,
      height,
      hidden.size,
      [...hidden].join('|'),
      highlight,
      themeVersion,
      regions,
      markers,
      baselines,
    ];
    schedule();
  });

  $effect(() => {
    const size = { width, height }; // read first: `plot` is not reactive, so the effect must depend on these
    if (plot && size.width > 0) plot.setSize(size);
  });

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => (width = Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  });
  onDestroy(() => {
    cancelAnimationFrame(frame);
    clearTimeout(wheelTimer);
    plot?.destroy();
  });
</script>

<div class="chart" bind:this={el} style="min-height:{height}px"></div>

<style>
  .chart :global(.nb-dot) {
    display: none;
    position: absolute;
    left: -5px;
    top: -5px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid var(--panel);
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.15);
    pointer-events: none;
    z-index: 2;
  }
  .chart {
    width: 100%;
    position: relative;
  }
  .chart :global(.u-over) {
    cursor: crosshair;
  }
</style>
