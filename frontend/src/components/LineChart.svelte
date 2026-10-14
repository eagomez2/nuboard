<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy, onMount } from 'svelte';
  import type { ChartData } from '../lib/api';
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
  }: {
    data: ChartData | null;
    smoothing?: number;
    showRaw?: boolean;
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
  } = $props();

  let el: HTMLDivElement;
  let plot: uPlot | null = null;
  let width = $state(600);
  let mains: { idx: number; label: string; series: number; lo: number | null; hi: number | null }[] = [];
  let frame = 0;

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
    let col = 1;
    data.series.forEach((s, i) => {
      if (hidden.has(s.label) || !s.x.length) return;
      const color = colorOf(s.label, i);
      const dim = highlight !== null && highlight !== s.label;
      const smooth = smoothing > 0 ? ema(s.y, smoothing) : s.y;
      const hasBand = s.lo.some((v, k) => Number.isFinite(v) && v !== s.y[k]) && (s.n ?? 1) > 1;
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
    const range = robust ? robustRange(yValues) : null;
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
            if (range && !logY) return range;
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
            onZoom?.(null);
            return null;
          },
          mouseup: (u, target, handler) => (e: MouseEvent) => {
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
              onZoom?.([a, b]);
            }
          },
        ],
        setCursor: [
          (u) => {
            if (!onCursor) return;
            const idx = u.cursor.idx;
            if (idx === null || idx === undefined) return onCursor(null, []);
            const x = u.data[0][idx];
            const values: CursorValue[] = [];
            for (const m of mains) {
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
            onCursor(x, values);
          },
        ],
        draw: [
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
                ctx.textAlign = 'right';
                ctx.fillText(`NaN · ${mark.label}`, px - 6 * devicePixelRatio, u.bbox.top + 14 * devicePixelRatio);
              }
            }
            ctx.restore();
          },
        ],
      },
    };
    plot = new uPlot(opts, joined, el);
  }

  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(build);
  }

  $effect(() => {
    // Rebuild when anything that changes series styling or data changes.
    void [data, smoothing, showRaw, robust, logY, height, hidden.size, [...hidden].join('|'), highlight, themeVersion];
    schedule();
  });

  $effect(() => {
    if (plot && width > 0) plot.setSize({ width, height });
  });

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => (width = Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  });
  onDestroy(() => {
    cancelAnimationFrame(frame);
    plot?.destroy();
  });
</script>

<div class="chart" bind:this={el} style="min-height:{height}px"></div>

<style>
  .chart {
    width: 100%;
    position: relative;
  }
  .chart :global(.u-over) {
    cursor: crosshair;
  }
</style>
