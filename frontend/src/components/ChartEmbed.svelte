<script lang="ts">
  import LineChart, { type CursorValue } from './LineChart.svelte';
  import { api, type ChartData } from '../lib/api';
  import { chartsParams, decodeSpec } from '../lib/chartspec';
  import { seriesColor } from '../lib/colors';
  import { fmtDuration, fmtNum, lowerIsBetter } from '../lib/format';
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

  // The values under the cursor, as the Charts inspector shows them; a click pins them.
  let cursorX = $state<number | null>(null);
  let values = $state<CursorValue[]>([]);
  let pinned = $state(false);
  let at = $state<{ x: number; y: number; w: number } | null>(null);
  const rows = $derived.by(() => {
    const lower = lowerIsBetter(s?.metric ?? '');
    return [...values].sort((a, b) => (lower ? a.value - b.value : b.value - a.value));
  });
  function fmtX(x: number): string {
    const kind = s?.x ?? 'step';
    if (kind === 'time') return new Date(x * 1000).toLocaleString();
    if (kind === 'relative' || kind === 'active') return fmtDuration(x);
    if (kind.startsWith('metric:')) return `${kind.slice(7)} ${fmtNum(x)}`;
    return `Step ${Math.round(x).toLocaleString()}`;
  }
  function track(e: PointerEvent) {
    if (pinned) return;
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
    at = { x: e.clientX - box.left, y: e.clientY - box.top, w: box.width };
  }
</script>

<figure class="embed">
  {#if s && data && !failed}
    <div class="head">
      <span class="mono metric" title={s.metric}>{s.metric}</span>
      <span class="faint small">{s.group ? `grouped by ${s.group}` : `${s.runs.length} runs`} · live</span>
      <button class="btn btn-ghost sm" onclick={() => router.go('charts', chartsParams(s))}>Open in Charts</button>
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="plot"
      onpointermove={track}
      onpointerleave={() => {
        if (!pinned) at = null;
      }}
    >
      <LineChart
        {data}
        smoothing={s.smooth}
        showRaw={s.raw}
        showBands={s.bands}
        zoom={s.zoom}
        robust={s.robust}
        logY={s.log}
        baselines={s.base}
        {hidden}
        {colorOf}
        syncKey="report"
        themeVersion={app.themeVersion}
        height={300}
        markers
        {pinned}
        onCursor={(x, v) => {
          if (pinned) return;
          cursorX = x;
          values = v;
        }}
        onPin={() => (pinned = !pinned && cursorX !== null)}
      />
      {#if at && cursorX !== null && rows.length}
        <div
          class="tip"
          class:pinned
          role="status"
          aria-label="Values at the cursor"
          style={at.x > at.w / 2 ? `right:${at.w - at.x + 14}px` : `left:${at.x + 14}px`}
        >
          <div class="tx mono">{fmtX(cursorX)}{pinned ? ' · pinned' : ''}</div>
          {#each rows.slice(0, 12) as v (v.label)}
            <div class="trow">
              <i style="background:{colorOf(v.label, v.series)}"></i>
              <span class="mono trunc tl" title={v.label}>{v.label}</span>
              <span class="mono tv">{fmtNum(v.value)}</span>
              {#if s.group && v.lo !== null && v.hi !== null && s.agg === 'std'}<span class="mono faint"
                  >±{fmtNum((v.hi - v.lo) / 2, 2)}</span
                >{/if}
            </div>
          {/each}
          {#if rows.length > 12}<div class="faint more">+{rows.length - 12} more</div>{/if}
        </div>
      {/if}
    </div>
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
    <div class="missing faint mono">Chart unavailable</div>
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
  .plot {
    position: relative;
  }
  .tip {
    position: absolute;
    top: 8px;
    z-index: 5;
    min-width: 180px;
    max-width: min(360px, 70%);
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
    font-size: 12px;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .tip.pinned {
    border-color: var(--accent);
  }
  .tx {
    font-weight: 600;
    margin-bottom: 2px;
  }
  .trow {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .trow i {
    width: 9px;
    height: 9px;
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
  @media print {
    .tip {
      display: none;
    }
    .head .btn {
      display: none;
    }
  }
</style>
