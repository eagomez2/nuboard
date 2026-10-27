<script lang="ts">
  import { prArea, prPoint, prSvg, type PRData } from '../lib/pr';

  // Precision-recall curves (`add_pr_curve`); hovering shows the nearest threshold's counts.
  let {
    curves,
    height = 240,
    label,
  }: { curves: { name: string; color: string; url: string }[]; height?: number; label: string } = $props();

  let width = $state(0);
  let loaded = $state<Record<string, PRData | null>>({});
  let hover = $state<{ s: number; i: number } | null>(null);

  $effect(() => {
    for (const c of curves) {
      if (c.url in loaded) continue;
      loaded[c.url] = null;
      fetch(c.url)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: PRData | null) => (loaded[c.url] = d))
        .catch(() => {});
    }
  });

  const series = $derived(
    curves.flatMap((c) => (loaded[c.url] ? [{ name: c.name, color: c.color, data: loaded[c.url]! }] : [])),
  );
  const svg = $derived(width ? prSvg(series, Math.round(width), height) : '');

  function move(e: PointerEvent) {
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const mx = e.clientX - box.left;
    const my = e.clientY - box.top;
    let best: { s: number; i: number } | null = null;
    let dist = 24 * 24;
    series.forEach((s, si) => {
      for (let i = 0; i < s.data.recall.length; i++) {
        if (s.data.tp[i] + s.data.fp[i] === 0) continue;
        const [x, y] = prPoint(s.data, i, width, height);
        const d = (x - mx) ** 2 + (y - my) ** 2;
        if (d < dist) {
          dist = d;
          best = { s: si, i };
        }
      }
    });
    hover = best;
  }

  const tip = $derived.by(() => {
    if (!hover || !series[hover.s]) return null;
    const s = series[hover.s];
    const d = s.data;
    const i = hover.i;
    const [x, y] = prPoint(d, i, width, height);
    return { s, i, d, x, y };
  });
  const fmt = (v: number) => (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1));
</script>

<div class="pr" bind:clientWidth={width} style="height:{height}px">
  <div class="plot" role="img" aria-label={label} onpointermove={move} onpointerleave={() => (hover = null)}>
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- built by prSvg from numbers and escaped names -->
    {@html svg}
  </div>
  {#if tip}
    <span class="dot" style="left:{tip.x}px;top:{tip.y}px;background:{tip.s.color}"></span>
    <div class="tip" class:left={tip.x > width / 2} style="left:{tip.x}px;top:{tip.y}px">
      <b>{tip.s.name}</b>
      <span class="mono">Threshold {tip.d.thresholds[tip.i].toFixed(3)}</span>
      <span class="mono">Precision {tip.d.precision[tip.i].toFixed(3)} · recall {tip.d.recall[tip.i].toFixed(3)}</span>
      <span class="mono faint"
        >TP {fmt(tip.d.tp[tip.i])} · FP {fmt(tip.d.fp[tip.i])} · TN {fmt(tip.d.tn[tip.i])} · FN {fmt(
          tip.d.fn[tip.i],
        )}</span
      >
    </div>
  {/if}
</div>
{#if series.length}
  <div class="legend">
    {#each series as s, i (i)}
      <span
        ><i style="background:{s.color}"></i>{s.name}
        <span class="mono faint" title="Average precision: the area under the curve"
          >AP {prArea(s.data).toFixed(3)}</span
        ></span
      >
    {/each}
  </div>
{/if}

<style>
  .pr {
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
  .dot {
    position: absolute;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 2px solid var(--panel);
    transform: translate(-50%, -50%);
    pointer-events: none;
  }
  .tip {
    position: absolute;
    transform: translate(10px, -50%);
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
    transform: translate(calc(-100% - 10px), -50%);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    font-size: 11.5px;
    margin-top: 2px;
  }
  .legend i {
    display: inline-block;
    width: 10px;
    height: 3px;
    border-radius: 2px;
    vertical-align: middle;
    margin-right: 4px;
  }
  .faint {
    color: var(--faint);
  }
</style>
