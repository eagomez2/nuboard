<script lang="ts">
  import DOMPurify from 'dompurify';
  import { tick } from 'svelte';
  import { router, type Page } from '../lib/router.svelte';
  import { svgCards } from '../lib/svgcards';

  // A snapshot saved from a page (Sweeps, Timeline), with a button that reopens that view.
  let { view, caption = '', src }: { view: string; caption?: string; src: string } = $props();

  const page = $derived(view.split('?')[0] as Page);
  const params = $derived(Object.fromEntries(new URLSearchParams(view.split('?')[1] ?? '').entries()));
  const label = $derived(page.charAt(0).toUpperCase() + page.slice(1));

  // An SVG snapshot (the Timeline) is drawn inline, so its hover titles work
  let svg = $state('');
  $effect(() => {
    svg = '';
    if (!/\.svg$/i.test(src)) return;
    fetch(src)
      .then((r) => (r.ok ? r.text() : ''))
      .then((t) => (svg = t ? DOMPurify.sanitize(t, { USE_PROFILES: { svg: true } }) : ''))
      .catch(() => {});
  });
  // hover cards on the bars, and a click opens the run
  let box = $state<HTMLDivElement>();
  $effect(() => {
    if (!svg || !box) return;
    let off = () => {};
    const el = box;
    tick().then(() => (off = svgCards(el, (run) => router.go('runs', { cmp: run }))));
    return () => off();
  });
</script>

<figure class="embed">
  {#if svg}
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized by DOMPurify -->
    <div class="svg" bind:this={box}>{@html svg}</div>
  {:else if !/\.svg$/i.test(src)}
    <!-- snapshots are drawn at twice their on-screen size, so they stay sharp on high-DPI screens -->
    <img
      {src}
      alt={caption}
      onload={(e) => {
        const img = e.currentTarget as HTMLImageElement;
        img.style.width = `${img.naturalWidth / 2}px`;
      }}
    />
  {/if}
  <figcaption>
    <span class="cap">{caption}</span>
    <button class="btn btn-ghost sm" onclick={() => router.go(page, params)}>Open in {label}</button>
  </figcaption>
</figure>

<style>
  .embed {
    margin: 0.8em 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 860px;
  }
  .svg {
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid var(--border);
  }
  .svg :global(.nb-card) {
    position: absolute;
    z-index: 5;
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-width: min(380px, 75%);
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.14);
    font-size: 12px;
    pointer-events: none;
    white-space: nowrap;
    text-align: left;
  }
  .svg :global(.nb-card[hidden]) {
    display: none;
  }
  .svg :global(.nb-card .head) {
    font-family: var(--mono);
    font-weight: 600;
  }
  .svg :global(.nb-card .faint) {
    font-family: var(--mono);
    color: var(--faint);
  }
  .svg :global(.nb-card .warn) {
    color: var(--warn);
  }
  .svg :global(svg) {
    display: block;
    max-width: 100%;
    height: auto;
  }
  img {
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid var(--border);
  }
  figcaption {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
  }
  .cap {
    flex: 1;
    min-width: 0;
  }
  .sm {
    height: 26px;
    font-size: 12px;
    flex: none;
  }
  @media print {
    .sm {
      display: none;
    }
  }
</style>
