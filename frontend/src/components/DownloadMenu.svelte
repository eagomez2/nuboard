<script lang="ts" module>
  /** One way to download an item: its format, and a few words on what it holds where needed. */
  export interface DownloadOption {
    /** The format, such as "WAV" or "JSON data". */
    label: string;
    /** A few words on what the file holds, only where the format alone does not say it. */
    hint?: string;
    /** The file name it is saved as. */
    filename: string;
    /** A URL to save from, or a function that makes the bytes. */
    href?: string;
    make?: () => Promise<Blob>;
  }
</script>

<script lang="ts">
  import Icon from './Icon.svelte';

  // The Download button of a media card: a small menu of the formats an item can be saved as, one
  // row per format, even when there is only one (so every download looks and works the same).
  let { options, label = 'Download' }: { options: DownloadOption[]; label?: string } = $props();

  let open = $state(false);
  let wrap: HTMLSpanElement;
  let error = $state('');

  function outside(e: PointerEvent) {
    if (!wrap.contains(e.target as Node)) open = false;
  }
  $effect(() => {
    if (!open) return;
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  });

  async function save(o: DownloadOption) {
    error = '';
    let url = o.href ?? '';
    try {
      if (o.make) url = URL.createObjectURL(await o.make());
    } catch (e) {
      error = `Could not make the ${o.label} file: ${e instanceof Error ? e.message : e}`;
      return;
    }
    const a = document.createElement('a');
    a.href = url;
    a.download = o.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (o.make) setTimeout(() => URL.revokeObjectURL(url), 1000);
    open = false;
  }
</script>

<span class="dl" bind:this={wrap}>
  <button
    class="icon"
    title={label}
    aria-label={label}
    aria-haspopup="menu"
    aria-expanded={open}
    onclick={() => (open = !open)}
    onkeydown={(e) => e.key === 'Escape' && open && (e.stopPropagation(), (open = false))}
    ><Icon name="download" size={14} /></button
  >
  {#if open}
    <span class="menu" role="menu" aria-label="Download as">
      {#each options as o (o.label)}
        <button role="menuitem" onclick={() => save(o)}
          >{o.label}{#if o.hint}<span class="hint">{o.hint}</span>{/if}</button
        >
      {/each}
      {#if error}<span class="err" role="alert">{error}</span>{/if}
    </span>
  {/if}
</span>

<style>
  .dl {
    position: relative;
    display: inline-flex;
  }
  .icon {
    display: inline-grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    border: 0;
    background: none;
    color: var(--muted);
  }
  .icon:hover,
  .icon[aria-expanded='true'] {
    background: var(--panel-2);
    color: var(--accent);
  }
  .menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 6;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 88px;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.15);
  }
  .menu button {
    border: 0;
    background: none;
    border-radius: 6px;
    padding: 4px 8px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
    white-space: nowrap;
    font-size: 12.5px;
    font-weight: 550;
    color: var(--text);
  }
  .hint {
    font-size: 11.5px;
    font-weight: 400;
    color: var(--faint);
  }
  .menu button:hover {
    background: var(--panel-2);
    color: var(--accent);
  }
  .menu button:hover .hint {
    color: var(--muted);
  }
  .err {
    max-width: 220px;
    padding: 4px 8px;
    font-size: 12px;
    color: var(--err);
  }
</style>
