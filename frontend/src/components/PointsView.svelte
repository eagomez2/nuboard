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
  }: { url: string; count: number; colors?: boolean; title: string; height?: number } = $props();

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
        view = mountPoints(canvas, buffer, count, colors, background());
      })
      .catch((e) => (error = `Could not load the points: ${e instanceof Error ? e.message : e}`));
    return () => {
      cancelled = true;
      view?.destroy();
    };
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
    <span class="mono">{count.toLocaleString()} points</span>
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
  .hint span:last-child {
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
