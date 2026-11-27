<script lang="ts">
  import { router } from '../lib/router.svelte';
  import { SCOPED_PAGES } from '../lib/scoped';
  import { app } from '../lib/state.svelte';

  // Shown on the pages in SCOPED_PAGES while they are limited to runs picked on the Runs
  // page (`sel` in the URL): says so, switches page keeping them, and Show all goes back to the query.
  const keys = $derived(router.list('sel'));
  const found = $derived(keys.filter((k) => app.runByKey(k)).length);
</script>

<div class="card banner" role="status">
  <span>
    Showing <b>{found || keys.length}</b> selected run{(found || keys.length) === 1 ? '' : 's'}
    {#if app.runs && found < keys.length}<span class="faint">({keys.length - found} no longer exist)</span>{/if}
  </span>
  <span class="grow"></span>
  {#each SCOPED_PAGES.filter((p) => p.page !== router.page) as p (p.page)}
    <button class="btn btn-ghost sm" onclick={() => router.go(p.page)}>{p.label}</button>
  {/each}
  <button class="btn sm" onclick={() => router.set({ sel: null })}>Show all</button>
</div>

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px 6px 14px;
    margin-bottom: 12px;
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
    background: var(--accent-soft);
    font-size: 13.5px;
  }
  .grow {
    flex: 1;
  }
  .faint {
    color: var(--faint);
  }
</style>
