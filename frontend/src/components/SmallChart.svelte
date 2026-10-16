<script lang="ts">
  import { onMount } from 'svelte';
  import LineChart from './LineChart.svelte';
  import { api, type ChartData } from '../lib/api';

  let {
    metric,
    runs,
    x,
    group,
    agg,
    smoothing,
    showRaw,
    robust,
    hidden,
    highlight,
    colorOf,
    themeVersion,
    tick,
    onFocus,
  }: {
    metric: string;
    runs: string[];
    x: string;
    group: string | null;
    agg: string;
    smoothing: number;
    showRaw: boolean;
    robust: boolean;
    hidden: Set<string>;
    highlight: string | null;
    colorOf: (label: string, i: number) => string;
    themeVersion: number;
    tick: number;
    onFocus: () => void;
  } = $props();

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
    <LineChart
      {data}
      {smoothing}
      {showRaw}
      {robust}
      {hidden}
      {highlight}
      {colorOf}
      {themeVersion}
      height={150}
      compact
    />
  {/if}
</div>

<style>
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
