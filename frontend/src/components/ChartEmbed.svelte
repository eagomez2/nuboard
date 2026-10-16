<script lang="ts">
  import LineChart from './LineChart.svelte';
  import { api, type ChartData } from '../lib/api';
  import { chartsParams, decodeSpec } from '../lib/chartspec';
  import { seriesColor } from '../lib/colors';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  // A chart saved from the Charts page into a report, drawn live; the snapshot is the fallback.
  let { spec, caption = '', src = '' }: { spec: string; caption?: string; src?: string } = $props();

  const s = $derived(decodeSpec(spec));
  let data = $state<ChartData | null>(null);
  let failed = $state(false);

  $effect(() => {
    const c = s;
    data = null;
    failed = !c;
    if (!c) return;
    const ctrl = new AbortController();
    api
      .chart({
        runs: c.runs,
        metric: c.metric,
        x: c.x,
        group: c.group,
        agg: c.agg,
        points: 900,
        xmin: c.zoom?.[0],
        xmax: c.zoom?.[1],
        signal: ctrl.signal,
      })
      .then((d) => {
        data = d;
        failed = !d.series.length;
      })
      .catch((e) => {
        if (e.name !== 'AbortError') failed = true;
      });
    return () => ctrl.abort();
  });

  const index = $derived(new Map((data?.series ?? []).map((x, i) => [x.label, i])));
  const colorOf = (label: string, i: number) => seriesColor(index.get(label) ?? i);
  const hidden = $derived(new Set(s?.hidden ?? []));
  const shown = $derived((data?.series ?? []).filter((x) => !hidden.has(x.label)));
</script>

<figure class="embed">
  {#if s && data && !failed}
    <div class="head">
      <span class="mono metric" title={s.metric}>{s.metric}</span>
      <span class="faint small">{s.group ? `grouped by ${s.group}` : `${s.runs.length} runs`} · live</span>
      <button class="btn btn-ghost sm" onclick={() => router.go('charts', chartsParams(s))}>Open in Charts</button>
    </div>
    <LineChart
      {data}
      smoothing={s.smooth}
      showRaw={s.raw}
      robust={s.robust}
      logY={s.log}
      {hidden}
      {colorOf}
      syncKey="report"
      themeVersion={app.themeVersion}
      height={300}
    />
    <div class="legend">
      {#each shown as x (x.label)}
        <span class="chip-l"
          ><i style="background:{colorOf(x.label, 0)}"></i><span class="mono trunc" title={x.label}>{x.label}</span
          ></span
        >
      {/each}
    </div>
  {:else if failed && src}
    <img {src} alt={caption} />
  {:else if failed}
    <div class="missing faint mono">chart unavailable</div>
  {:else}
    <div class="missing faint">Loading…</div>
  {/if}
  {#if caption}<figcaption>{caption}</figcaption>{/if}
</figure>

<style>
  .embed {
    margin: 0.8em 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 860px;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    background: var(--panel);
  }
  .head {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .metric {
    font-weight: 600;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .head .btn {
    margin-left: auto;
    height: 26px;
    font-size: 12px;
    flex: none;
  }
  .small {
    font-size: 12px;
    flex: none;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    font-size: 12px;
  }
  .chip-l {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    max-width: 260px;
  }
  .chip-l i {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
  }
  .trunc {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  img {
    max-width: 100%;
    border-radius: 8px;
  }
  figcaption {
    font-size: 13px;
  }
  .faint {
    color: var(--faint);
  }
  .missing {
    padding: 20px;
    text-align: center;
    font-size: 13px;
  }
  @media print {
    .head .btn {
      display: none;
    }
  }
</style>
