<script lang="ts">
  import HistChart from './HistChart.svelte';
  import { api, type MediaItem } from '../lib/api';
  import { HIST_BOX, QUANTILES, bandsSvg, fmtTick, loadHist, quantile, type StepQuantiles } from '../lib/hist';
  import { HIST_MIME } from '../lib/media';
  import { runMedia } from '../lib/tables';

  // A logged distribution (`add_histogram`): the chosen step against the one
  // logged before it, or how it moves over every step.
  let {
    runKey,
    runName,
    item,
    color,
    height = 220,
  }: { runKey: string; runName: string; item: MediaItem; color: string; height?: number } = $props();

  /** Most steps drawn over time; longer histories are sampled evenly. */
  const MAX_STEPS = 150;

  let over = $state(false);
  let history = $state<MediaItem[]>([]);
  let bands = $state<StepQuantiles[] | null>(null);
  let width = $state(0);
  let hover = $state<number | null>(null);

  $effect(() => {
    const key = item.key;
    runMedia(runKey).then((all) => {
      history = all.filter((m) => m.key === key && m.mime === HIST_MIME).sort((a, b) => a.step - b.step);
    });
  });

  const previous = $derived([...history].reverse().find((m) => m.step < item.step && m.index !== undefined));

  const curves = $derived([
    ...(previous
      ? [
          {
            name: `step ${previous.step.toLocaleString()}`,
            color: 'var(--faint)',
            url: api.mediaUrl(runKey, previous.index!),
            dashed: true,
          },
        ]
      : []),
    { name: `step ${item.step.toLocaleString()}`, color, url: api.mediaUrl(runKey, item.index!), fill: true },
  ]);

  $effect(() => {
    if (!over || !history.length) return;
    const every = Math.max(1, Math.ceil(history.length / MAX_STEPS));
    const picked = history.filter((_, i) => i % every === 0 || i === history.length - 1);
    let cancelled = false;
    Promise.all(picked.map((m) => loadHist(api.mediaUrl(runKey, m.index!)))).then((all) => {
      if (cancelled) return;
      bands = all.flatMap((d, i) => (d ? [{ step: picked[i].step, q: QUANTILES.map((q) => quantile(d, q)) }] : []));
    });
    return () => (cancelled = true);
  });

  const svg = $derived(width && bands ? bandsSvg(bands, color, Math.round(width), height, item.step) : '');

  // nearest drawn step under the pointer
  const tip = $derived.by(() => {
    if (hover === null || !bands?.length) return null;
    const steps = bands.map((b) => b.step);
    const s0 = Math.min(...steps);
    const s1 = Math.max(...steps);
    const w = width - HIST_BOX.left - HIST_BOX.right;
    const at = s0 + ((hover - HIST_BOX.left) / w) * (s1 - s0 || 1);
    const row = bands.reduce((a, b) => (Math.abs(b.step - at) < Math.abs(a.step - at) ? b : a));
    const x = HIST_BOX.left + ((row.step - s0) / (s1 - s0 || 1)) * w;
    return { row, x };
  });
</script>

<div class="hv">
  <div class="modes" role="group" aria-label="Distribution view">
    <button aria-pressed={!over} onclick={() => (over = false)}>at step</button>
    <button aria-pressed={over} disabled={history.length < 2} onclick={() => (over = true)}>over steps</button>
  </div>
  {#if over}
    <div class="bands" bind:clientWidth={width} style="height:{height}px">
      <div
        class="plot"
        role="img"
        aria-label="Distribution of {runName} {item.key} over steps"
        onpointermove={(e) => (hover = e.clientX - (e.currentTarget as HTMLElement).getBoundingClientRect().left)}
        onpointerleave={() => (hover = null)}
      >
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- built by bandsSvg from numbers -->
        {@html svg}
      </div>
      {#if tip}
        <span class="rule" style="left:{tip.x}px;top:{HIST_BOX.top}px;bottom:{HIST_BOX.bottom}px"></span>
        <div class="tip" class:left={tip.x > width / 2} style="left:{tip.x}px;top:{HIST_BOX.top + 8}px">
          <b>step {tip.row.step.toLocaleString()}</b>
          <span class="mono">median {fmtTick(tip.row.q[3])}</span>
          <span class="mono">16–84% {fmtTick(tip.row.q[2])} to {fmtTick(tip.row.q[4])}</span>
          <span class="mono faint">min {fmtTick(tip.row.q[0])} · max {fmtTick(tip.row.q[6])}</span>
        </div>
      {/if}
    </div>
    <div class="faint small">
      Median line; bands hold 68%, 86% and all of the values.
      {#if bands && history.length > bands.length}{bands.length} of {history.length} steps shown.{/if}
    </div>
  {:else}
    <HistChart {curves} {height} label="Distribution of {runName} {item.key} at step {item.step}" />
  {/if}
</div>

<style>
  .hv {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .modes {
    display: flex;
    gap: 4px;
    align-self: flex-end;
  }
  .modes button {
    border: 1px solid var(--border);
    background: none;
    color: var(--faint);
    border-radius: 6px;
    padding: 0 7px;
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .modes button[aria-pressed='true'] {
    color: var(--accent);
    border-color: var(--accent);
  }
  .modes button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .bands {
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
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 11.5px;
  }
</style>
