<script lang="ts">
  import { router, type Page } from '../lib/router.svelte';

  // A snapshot saved from a page (Sweeps, Timeline), with a button that reopens that view.
  let { view, caption = '', src }: { view: string; caption?: string; src: string } = $props();

  const page = $derived(view.split('?')[0] as Page);
  const params = $derived(Object.fromEntries(new URLSearchParams(view.split('?')[1] ?? '').entries()));
  const label = $derived(page.charAt(0).toUpperCase() + page.slice(1));
</script>

<figure class="embed">
  <!-- snapshots are drawn at twice their on-screen size, so they stay sharp on high-DPI screens -->
  <img
    {src}
    alt={caption}
    onload={(e) => {
      const img = e.currentTarget as HTMLImageElement;
      img.style.width = `${img.naturalWidth / 2}px`;
    }}
  />
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
