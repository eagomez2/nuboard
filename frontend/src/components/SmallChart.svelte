<script lang="ts">
  import { onMount } from 'svelte';
  import LineChart, { type CursorValue } from './LineChart.svelte';
  import { api, type ChartData } from '../lib/api';
  import { fmtDuration, fmtNum, lowerIsBetter } from '../lib/format';

  let {
    metric,
    runs,
    x,
    group,
    agg,
    smoothing,
    showRaw,
    showBands,
    robust,
    baselines,
    hidden,
    highlight,
    colorOf,
    themeVersion,
    tick,
    onFocus,
    markers = true,
    pinX = null,
    fullName = false,
  }: {
    metric: string;
    runs: string[];
    x: string;
    group: string | null;
    agg: string;
    smoothing: number;
    showRaw: boolean;
    showBands: boolean;
    robust: boolean;
    baselines: boolean;
    hidden: Set<string>;
    highlight: string | null;
    colorOf: (label: string, i: number) => string;
    themeVersion: number;
    tick: number;
    onFocus: () => void;
    /** A dot on each curve at the point under the cursor (or the pinned step). */
    markers?: boolean;
    /** The x pinned on the main chart: a line there, and the values at it on hover. */
    pinX?: number | null;
    /** The full metric name as a caption under the chart. */
    fullName?: boolean;
  } = $props();

  // A tooltip with each run's value under the cursor (or at the pinned step), best first.
  const TIP_ROWS = 8;
  let at = $state<{ x: number; w: number } | null>(null);
  let cursorX = $state<number | null>(null);
  let cursorValues = $state<CursorValue[]>([]);
  let pinValues = $state<CursorValue[]>([]);
  const tipX = $derived(pinX ?? cursorX);
  const rows = $derived.by(() => {
    const lower = lowerIsBetter(metric);
    return [...(pinX != null ? pinValues : cursorValues)].sort((a, b) =>
      lower ? a.value - b.value : b.value - a.value,
    );
  });
  function fmtX(v: number) {
    if (x === 'time') return new Date(v * 1000).toLocaleString();
    if (x === 'relative' || x === 'active') return fmtDuration(v);
    if (x.startsWith('metric:')) return `${x.slice(7)} ${fmtNum(v)}`;
    return `Step ${Math.round(v).toLocaleString()}`;
  }
  function track(e: PointerEvent) {
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
    at = { x: e.clientX - box.left, w: box.width };
  }

  let el: HTMLElement;
  let visible = $state(false);
  let data = $state<ChartData | null>(null);
  let error = $state<string | null>(null);

  onMount(() => {
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting), { rootMargin: '300px' });
    io.observe(el);
    return () => io.disconnect();
  });

  $effect(() => {
    if (!visible || !runs.length) return;
    void tick;
    const ctrl = new AbortController();
    api
      .chart({ runs, metric, x, group, agg, points: 320, signal: ctrl.signal })
      .then((d) => {
        data = d;
        error = null;
      })
      .catch((e) => {
        if (e.name !== 'AbortError') error = String(e);
      });
    return () => ctrl.abort();
  });

  const note = $derived(
    group
      ? agg === 'minmax'
        ? 'mean · min–max'
        : agg === 'none'
          ? 'mean'
          : agg === 'median'
            ? 'median'
            : 'mean ± std'
      : '',
  );
</script>

<div class="card small" bind:this={el}>
  <button class="title" onclick={onFocus} title="{metric}: click to bring into focus">
    <span class="mono name">{metric}</span>
    <span class="note">{note}</span>
  </button>
  {#if error}
    <p class="err">{error}</p>
  {:else if !data}
    <!-- loads when scrolled near the viewport -->
    <div class="loading">Loading…</div>
  {:else}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="plot" onpointermove={track} onpointerleave={() => (at = null)}>
      <LineChart
        {data}
        {smoothing}
        {showRaw}
        {showBands}
        {robust}
        {baselines}
        {hidden}
        {highlight}
        {colorOf}
        {themeVersion}
        height={150}
        compact
        {markers}
        {pinX}
        onCursor={(cx, v) => {
          cursorX = cx;
          cursorValues = v;
        }}
        onPinValues={(_, v) => (pinValues = v)}
      />
      {#if at && tipX !== null && rows.length}
        <div
          class="tip"
          class:pinned={pinX != null}
          role="status"
          aria-label="Values of {metric}"
          style={at.x > at.w / 2 ? `right:${at.w - at.x + 12}px` : `left:${at.x + 12}px`}
        >
          <div class="tx mono">{fmtX(tipX)}{pinX != null ? ' · pinned' : ''}</div>
          {#each rows.slice(0, TIP_ROWS) as v (v.label)}
            <div class="trow">
              <i style="background:{colorOf(v.label, v.series)}"></i>
              <span class="mono trunc tl">{v.label}</span>
              <span class="mono tv">{fmtNum(v.value)}</span>
            </div>
          {/each}
          {#if rows.length > TIP_ROWS}<div class="faint more">+{rows.length - TIP_ROWS} more</div>{/if}
        </div>
      {/if}
    </div>
  {/if}
  {#if fullName}<div class="fullname mono">{metric}</div>{/if}
</div>

<style>
  .plot {
    position: relative;
  }
  .tip {
    position: absolute;
    top: 4px;
    z-index: 5;
    min-width: 150px;
    max-width: min(300px, 80%);
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
    font-size: 11.5px;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .tip.pinned {
    border-color: var(--accent);
  }
  .tx {
    font-weight: 600;
    margin-bottom: 1px;
  }
  .trow {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .trow i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .tl {
    flex: 1;
    min-width: 0;
  }
  .tv {
    flex: none;
  }
  .more {
    font-size: 11px;
  }
  .fullname {
    font-size: 11px;
    color: var(--muted);
    overflow-wrap: anywhere;
    padding: 2px 0 2px;
  }
  .loading {
    height: 150px;
    display: grid;
    place-items: center;
    color: var(--faint);
    font-size: 12px;
  }
  .small {
    padding: 10px 12px 6px;
    min-width: 0;
  }
  .title {
    display: flex;
    align-items: baseline;
    gap: 8px;
    width: 100%;
    border: 0;
    background: none;
    padding: 0 0 4px;
    text-align: left;
  }
  .name {
    font-weight: 600;
    font-size: 13px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .title:hover .name {
    color: var(--accent);
  }
  .note {
    margin-left: auto;
    color: var(--faint);
    font-size: 12px;
    white-space: nowrap;
    flex: none;
  }
  .err {
    color: var(--err);
    font-size: 12px;
  }
</style>
