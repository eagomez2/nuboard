<script lang="ts">
  import { HIST_BOX, fmtTick, histScale, histSvg, loadHist, type HistData } from '../lib/hist';

  // Distributions (`add_histogram`) on one chart; hovering shows each one's bin there.
  let {
    curves,
    height = 240,
    label,
  }: {
    curves: { name: string; color: string; url: string; fill?: boolean; dashed?: boolean }[];
    height?: number;
    label: string;
  } = $props();

  let width = $state(0);
  let loaded = $state<Record<string, HistData | null>>({});
  let hoverX = $state<number | null>(null);

  $effect(() => {
    for (const c of curves) {
      if (c.url in loaded) continue;
      loaded[c.url] = null;
      loadHist(c.url).then((d) => (loaded[c.url] = d));
    }
  });

  const series = $derived(curves.flatMap((c) => (loaded[c.url] ? [{ ...c, data: loaded[c.url]! }] : [])));
  const svg = $derived(width ? histSvg(series, Math.round(width), height) : '');

  const tip = $derived.by(() => {
    if (hoverX === null || !series.length) return null;
    const { lo, hi } = histScale(series);
    const w = width - HIST_BOX.left - HIST_BOX.right;
    const v = lo + ((hoverX - HIST_BOX.left) / w) * (hi - lo);
    if (v < lo || v > hi) return null;
    const rows = series.flatMap((s) => {
      const d = s.data;
      const i = d.edges.findIndex((e, k) => k < d.counts.length && v >= e && v <= d.edges[k + 1]);
      if (i < 0) return [];
      const total = d.counts.reduce((a, b) => a + b, 0) || 1;
      return [{ s, a: d.edges[i], b: d.edges[i + 1], n: d.counts[i], share: d.counts[i] / total }];
    });
    return { v, rows };
  });
  const fmtCount = (v: number) => (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1));
</script>

<div class="hist" bind:clientWidth={width} style="height:{height}px">
  <div
    class="plot"
    role="img"
    aria-label={label}
    onpointermove={(e) => (hoverX = e.clientX - (e.currentTarget as HTMLElement).getBoundingClientRect().left)}
    onpointerleave={() => (hoverX = null)}
  >
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- built by histSvg from numbers and escaped names -->
    {@html svg}
  </div>
  {#if tip && hoverX !== null}
    <span class="rule" style="left:{hoverX}px;top:{HIST_BOX.top}px;bottom:{HIST_BOX.bottom}px"></span>
    <div class="tip" class:left={hoverX > width / 2} style="left:{hoverX}px;top:{HIST_BOX.top + 8}px">
      <span class="mono faint">Value {fmtTick(tip.v)}</span>
      {#each tip.rows as r, i (i)}
        <span class="mono"
          ><i style="background:{r.s.color}"></i>{r.s.name}: {fmtTick(r.a)} to {fmtTick(r.b)} · {fmtCount(r.n)} ({(
            r.share * 100
          ).toFixed(1)}%)</span
        >
      {/each}
    </div>
  {/if}
</div>
{#if series.length}
  <div class="legend">
    {#each series as s, i (i)}
      <span
        ><i class:dashed={s.dashed} style="background:{s.color}"></i>{s.name}
        <span class="mono faint"
          >{s.data.mean != null ? `Mean ${fmtTick(s.data.mean)}` : ''}{s.data.std != null
            ? ` · std ${fmtTick(s.data.std)}`
            : ''}{s.data.mean != null ? ' · ' : ''}n {fmtCount(s.data.count)}{s.data.nonfinite
            ? ` · ${fmtCount(s.data.nonfinite)} NaN/inf`
            : ''}</span
        ></span
      >
    {/each}
  </div>
{/if}

<style>
  .hist {
    position: relative;
    width: 100%;
  }
  .plot {
    width: 100%;
    height: 100%;
    cursor: crosshair;
  }
  .plot :global(svg) {
    display: block;
  }
  .rule {
    position: absolute;
    width: 0;
    border-left: 1px dashed var(--faint);
    pointer-events: none;
  }
  .tip {
    position: absolute;
    transform: translateX(10px);
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 11.5px;
    display: flex;
    flex-direction: column;
    gap: 1px;
    white-space: nowrap;
    pointer-events: none;
    box-shadow: var(--lift);
    z-index: 2;
  }
  .tip.left {
    transform: translateX(calc(-100% - 10px));
  }
  i {
    display: inline-block;
    width: 10px;
    height: 3px;
    border-radius: 2px;
    vertical-align: middle;
    margin-right: 4px;
  }
  i.dashed {
    opacity: 0.6;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    font-size: 11.5px;
    margin-top: 2px;
  }
  .faint {
    color: var(--faint);
  }
</style>
