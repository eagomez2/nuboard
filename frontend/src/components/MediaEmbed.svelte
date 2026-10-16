<script lang="ts">
  import MediaView from './MediaView.svelte';
  import { api, type MediaItem } from '../lib/api';

  // A logged item embedded in Markdown with `![caption](media:<run id>/<key>@<step>)`.
  let { project, ref, caption = '' }: { project: string | null; ref: string; caption?: string } = $props();

  let found = $state<{ run: string; run_name: string; item: MediaItem } | null>(null);
  let error = $state('');

  $effect(() => {
    found = null;
    error = '';
    if (!project) {
      error = 'media references work in reports';
      return;
    }
    api
      .mediaRef(project, ref)
      .then((res) => (found = res))
      .catch(() => (error = `not found: ${decodeURIComponent(ref)}`));
  });
</script>

<figure class="embed">
  {#if found}
    <MediaView runKey={found.run} runName={found.run_name} item={found.item} player="wave" />
    <figcaption>
      {#if caption}<span class="cap">{caption}</span>{/if}
      <span class="faint mono">{found.run_name} · {found.item.key} · step {found.item.step.toLocaleString()}</span>
    </figcaption>
  {:else if error}
    <div class="missing faint mono">{error}</div>
  {:else}
    <div class="missing faint">Loading…</div>
  {/if}
</figure>

<style>
  .embed {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 760px;
  }
  figcaption {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
  }
  .cap {
    color: var(--text);
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
