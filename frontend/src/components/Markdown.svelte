<script lang="ts">
  import { mount, unmount } from 'svelte';
  import ChartEmbed from './ChartEmbed.svelte';
  import MediaEmbed from './MediaEmbed.svelte';
  import ViewEmbed from './ViewEmbed.svelte';
  import { api } from '../lib/api';
  import { renderMarkdown } from '../lib/markdown';

  // Rendered Markdown. Items embedded with `media:` references and chart snapshots are drawn in place.
  // `files` resolves report-local images (`files/...`), which only reports have.
  let { text, project = null, files = false }: { text: string; project?: string | null; files?: boolean } = $props();

  let el = $state<HTMLDivElement>();
  const html = $derived(renderMarkdown(text, files && project ? api.reportFileUrl(project, '') : ''));

  $effect(() => {
    void html;
    if (!el) return;
    const mounted = [
      ...[...el.querySelectorAll<HTMLElement>('.nb-embed')].map((slot) =>
        mount(MediaEmbed, {
          target: slot,
          props: { project, ref: slot.dataset.ref ?? '', caption: slot.dataset.caption ?? '' },
        }),
      ),
      ...[...el.querySelectorAll<HTMLElement>('.nb-chart')].map((slot) =>
        mount(ChartEmbed, {
          target: slot,
          props: { spec: slot.dataset.spec ?? '', caption: slot.dataset.caption ?? '', src: slot.dataset.src ?? '' },
        }),
      ),
      ...[...el.querySelectorAll<HTMLElement>('.nb-view')].map((slot) =>
        mount(ViewEmbed, {
          target: slot,
          props: { view: slot.dataset.view ?? '', caption: slot.dataset.caption ?? '', src: slot.dataset.src ?? '' },
        }),
      ),
    ];
    return () => mounted.forEach((m) => unmount(m));
  });
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized by DOMPurify -->
<div class="md" bind:this={el}>{@html html}</div>

<style>
  .md {
    font-size: 14.5px;
    line-height: 1.6;
    overflow-wrap: anywhere;
    min-width: 0;
  }
  .md :global(h1) {
    font-size: 24px;
    letter-spacing: -0.02em;
    margin: 0.2em 0 0.6em;
  }
  .md :global(h2) {
    font-size: 19px;
    margin: 1.4em 0 0.5em;
  }
  .md :global(h3) {
    font-size: 16px;
    margin: 1.2em 0 0.4em;
  }
  .md :global(p),
  .md :global(ul),
  .md :global(ol) {
    margin: 0.6em 0;
  }
  .md :global(ul) {
    list-style: disc;
    padding-left: 1.4em;
  }
  .md :global(ol) {
    list-style: decimal;
    padding-left: 1.4em;
  }
  .md :global(li) {
    margin: 0.2em 0;
  }
  .md :global(a) {
    color: var(--accent);
  }
  .md :global(code) {
    font-family: var(--mono);
    font-size: 0.9em;
    background: var(--panel-2);
    border-radius: 5px;
    padding: 1px 5px;
  }
  .md :global(pre) {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 10px 12px;
    overflow: auto;
  }
  .md :global(pre code) {
    background: none;
    padding: 0;
  }
  .md :global(blockquote) {
    margin: 0.8em 0;
    padding: 2px 14px;
    border-left: 3px solid var(--border);
    color: var(--muted);
  }
  .md :global(table) {
    border-collapse: collapse;
    margin: 0.8em 0;
    font-size: 13.5px;
  }
  .md :global(th),
  .md :global(td) {
    border: 1px solid var(--border);
    padding: 5px 10px;
    text-align: left;
  }
  .md :global(th) {
    background: var(--panel-2);
  }
  .md :global(img) {
    max-width: 100%;
    border-radius: 8px;
  }
  .md :global(hr) {
    border: 0;
    border-top: 1px solid var(--border);
    margin: 1.4em 0;
  }
  .md :global(.nb-embed),
  .md :global(.nb-chart),
  .md :global(.nb-view) {
    display: block;
    margin: 1em 0;
  }
</style>
