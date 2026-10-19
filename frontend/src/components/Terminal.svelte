<script lang="ts">
  import { ansiToHtml, showEscapes } from '../lib/ansi';

  // Console output drawn as a terminal shows it (colors, styles, progress bars on one
  // line), or `raw`: the text as stored, escape characters shown as ␛.
  let { text, raw = false, follow = false }: { text: string; raw?: boolean; follow?: boolean } = $props();

  let pre = $state<HTMLPreElement | null>(null);
  const html = $derived(raw ? '' : ansiToHtml(text));
  // A log is read from its end, like a terminal
  $effect(() => {
    void html;
    void raw;
    if (pre && follow) pre.scrollTop = pre.scrollHeight;
  });
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -- built by ansiToHtml, which escapes the text -->
<pre class="term mono" class:raw bind:this={pre}>{#if raw}{showEscapes(text)}{:else}{@html html}{/if}</pre>

<style>
  .term {
    font-size: 12.5px;
    max-height: 520px;
    overflow: auto;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .term.raw {
    white-space: pre;
    overflow-wrap: normal;
  }
</style>
