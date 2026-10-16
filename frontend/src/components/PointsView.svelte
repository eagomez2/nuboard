<script lang="ts">
  import { onMount } from 'svelte';
  import { app } from '../lib/state.svelte';
  import { mountPoints, type PointsView } from '../lib/points';

  // A logged point cloud (`add_point_cloud`), drawn in a view you can rotate.
  let {
    url,
    count,
    colors = false,
    title,
    height = 260,
    axes = null,
  }: {
    url: string;
    count: number;
    colors?: boolean;
    title: string;
    height?: number;
    /** Axis names logged with the cloud; when given, the axes start shown. */
    axes?: string[] | null;
  } = $props();

  // shown as logged until toggled
  let toggled = $state<boolean | null>(null);
  const showAxes = $derived(toggled ?? !!axes);
  const names = () => (showAxes ? (axes ?? ['x', 'y', 'z']) : null);

  let canvas = $state<HTMLCanvasElement | null>(null);
  let view: PointsView | null = null;
  let error = $state('');

  const background = () => getComputedStyle(document.documentElement).getPropertyValue('--panel-2').trim() || '#000';

  onMount(() => {
    let cancelled = false;
    fetch(url)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
      .then((buffer) => {
        if (cancelled || !canvas) return;
        if (buffer.byteLength < count * (colors ? 15 : 12)) throw new Error('the file is shorter than its points');
        view = mountPoints(canvas, buffer, count, colors, background(), names());
      })
      .catch((e) => (error = `Could not load the points: ${e instanceof Error ? e.message : e}`));
    return () => {
      cancelled = true;
      view?.destroy();
    };
  });

  $effect(() => {
    const n = names(); // read first, so the effect follows the toggle before the view exists
    view?.setAxes(n);
  });

  // follow the theme
  $effect(() => {
    void [app.theme, app.themeVersion];
    view?.setBackground(background());
  });
</script>

<div class="points">
  <canvas bind:this={canvas} style="height:{height}px" aria-label={title}></canvas>
  <div class="hint faint">
    <span class="left"
      ><span class="mono">{count.toLocaleString()} points</span>
      <button class="axes" aria-pressed={showAxes} onclick={() => (toggled = !showAxes)}>axes</button></span
    >
    <span>drag to rotate · shift-drag to pan · click, then scroll to zoom · double-click to reset</span>
  </div>
  {#if error}<p class="faint error">{error}</p>{/if}
</div>

<style>
  .points {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  canvas {
    display: block;
    width: 100%;
    border-radius: 8px;
    background: var(--panel-2);
  }
  .hint {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 11.5px;
    overflow: hidden;
    white-space: nowrap;
  }
  .left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }
  .axes {
    border: 1px solid var(--border);
    background: none;
    color: var(--faint);
    border-radius: 6px;
    padding: 0 6px;
    font: inherit;
    cursor: pointer;
  }
  .axes[aria-pressed='true'] {
    color: var(--accent);
    border-color: var(--accent);
  }
  .hint > span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .faint {
    color: var(--faint);
  }
  .error {
    margin: 0;
    font-size: 12px;
  }
</style>
