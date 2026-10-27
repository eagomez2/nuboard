<script lang="ts">
  import HistChart from './HistChart.svelte';
  import PrChart from './PrChart.svelte';
  import { resolveOverlay, type Overlay } from '../lib/overlay';
  import { router } from '../lib/router.svelte';

  // Every run's PR curve or distribution on one chart, as on the Media page, drawn live in a report.
  // `src` is the PNG saved with it, shown when the items cannot be found.
  let {
    project,
    refs,
    caption = '',
    src = '',
  }: { project: string | null; refs: string; caption?: string; src?: string } = $props();

  let overlay = $state<Overlay | null>(null);
  let error = $state('');

  $effect(() => {
    overlay = null;
    error = '';
    if (!project) {
      error = 'media references work in reports';
      return;
    }
    resolveOverlay(project, refs)
      .then((o) => (overlay = o))
      .catch((e) => (error = String(e.message ?? e)));
  });

  function open() {
    if (!overlay || !project) return;
    router.go('media', { project, mfind: `^${overlay.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$` });
  }
</script>

<figure class="embed">
  {#if overlay}
    {#if overlay.kind === 'pr'}
      <PrChart curves={overlay.curves} height={300} label="Precision-recall curves of {overlay.key} for all runs" />
    {:else}
      <HistChart curves={overlay.curves} height={260} label="Distributions of {overlay.key} for all runs" />
    {/if}
    <figcaption>
      <span class="cap">{caption}</span>
      <button class="btn btn-ghost sm" onclick={open}>Open in Media</button>
    </figcaption>
    {#if overlay.missing.length}
      <span class="faint mono">not found: {overlay.missing.join(', ')}</span>
    {/if}
  {:else if error}
    {#if src}<img {src} alt={caption} />{/if}
    <div class="missing faint mono">{error}</div>
  {:else}
    <div class="missing faint">Loading…</div>
  {/if}
</figure>

<style>
  .embed {
    margin: 0.8em 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 760px;
  }
  figcaption {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 13px;
  }
  .cap {
    color: var(--text);
  }
  img {
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid var(--border);
  }
  .faint {
    color: var(--faint);
    font-size: 12px;
  }
  .missing {
    padding: 14px;
    border: 1px dashed var(--border);
    border-radius: 9px;
  }
</style>
