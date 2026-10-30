<script lang="ts">
  import Icon from './Icon.svelte';
  import { fmtBytes } from '../lib/format';

  // A text file attached to a report: a collapsible block with its content and a download link.
  let { src, name }: { src: string; name: string } = $props();

  const SHOWN = 200_000; // characters shown; the download has the rest
  let text = $state<string | null>(null);
  let failed = $state(false);

  $effect(() => {
    let live = true;
    text = null;
    failed = false;
    fetch(src)
      .then((res) => (res.ok ? res.text() : Promise.reject()))
      .then((t) => live && (text = t))
      .catch(() => live && (failed = true));
    return () => {
      live = false;
    };
  });
  const size = $derived(text === null ? '' : fmtBytes(new TextEncoder().encode(text).length));
</script>

<details class="nb-attachment">
  <summary>
    <Icon name="file" size={14} />
    <span class="name mono">{name}</span>
    {#if size}<span class="size">{size}</span>{/if}
    <a class="dl" href={src} download={name} title="Download {name}" onclick={(e) => e.stopPropagation()}
      ><Icon name="download" size={13} /> Download</a
    >
  </summary>
  {#if failed}
    <p class="missing">This file is missing from <span class="mono">reports/files/</span>.</p>
  {:else if text === null}
    <p class="missing">Loading…</p>
  {:else}
    <pre class="mono">{text.slice(0, SHOWN)}{#if text.length > SHOWN}<span class="more"
          >{`\n… ${(text.length - SHOWN).toLocaleString()} more characters in the download`}</span
        >{/if}</pre>
  {/if}
</details>

<style>
  .nb-attachment {
    display: block;
    margin: 0.8em 0;
    border: 1px solid var(--border);
    border-radius: 9px;
    background: var(--panel-2);
  }
  summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    cursor: pointer;
    font-size: 13.5px;
    list-style-position: inside;
  }
  .name {
    font-weight: 600;
  }
  .size {
    color: var(--faint);
    font-size: 12px;
  }
  .dl {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12.5px;
  }
  pre {
    margin: 0;
    border-top: 1px solid var(--border);
    padding: 10px 12px;
    max-height: 420px;
    overflow: auto;
    font-size: 12.5px;
    white-space: pre;
  }
  .more {
    color: var(--faint);
  }
  .missing {
    margin: 0;
    padding: 8px 12px;
    color: var(--faint);
    font-size: 13px;
  }
</style>
