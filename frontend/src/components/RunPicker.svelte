<script lang="ts">
  // A run picker that tells same-name runs apart (see RunLine): a button that opens a filterable
  // list, newest first. Arrow keys move, Enter picks, Esc closes.
  import { idSuffix, pickMatches, type PickRun } from '../lib/runlabel';
  import RunLine from './RunLine.svelte';

  let {
    runs,
    context,
    value = '',
    placeholder = 'Pick a run…',
    label,
    none = '',
    disabled = false,
    onpick,
  }: {
    runs: PickRun[];
    /** A line under some runs, such as the hypothesis they belong to. */
    context?: Map<string, string>;
    value?: string;
    placeholder?: string;
    label: string;
    /** A first entry that picks nothing (''), such as "No run yet"; none when empty. */
    none?: string;
    disabled?: boolean;
    onpick: (id: string) => void;
  } = $props();

  let open = $state(false);
  let find = $state('');
  let active = $state(0);
  let root = $state<HTMLElement>();
  let box = $state<HTMLInputElement>();
  let list = $state<HTMLElement>();

  const picked = $derived(runs.find((r) => r.id === value));
  const shown = $derived(runs.filter((r) => pickMatches(r, find, context?.get(r.id))));
  // the "none" entry counts as row 0 when there is one
  const offset = $derived(none && !find.trim() ? 1 : 0);
  const count = $derived(shown.length + offset);

  function toggle() {
    open = !open;
    if (open) {
      find = '';
      const at = runs.findIndex((r) => r.id === value);
      active = at >= 0 ? at + (none ? 1 : 0) : 0;
      queueMicrotask(() => list?.querySelector('.on')?.scrollIntoView({ block: 'nearest' }));
      requestAnimationFrame(() => box?.focus());
    }
  }
  function pick(i: number) {
    const id = i < offset ? '' : shown[i - offset]?.id;
    if (id === undefined) return;
    open = false;
    onpick(id);
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!count) return;
      active = (active + (e.key === 'ArrowDown' ? 1 : count - 1)) % count;
      queueMicrotask(() => list?.querySelector('.on')?.scrollIntoView({ block: 'nearest' }));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      pick(active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      open = false;
    }
  }
  function outside(e: PointerEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onpointerdown={outside} />

<div class="rp" bind:this={root}>
  <button
    class="input trigger"
    {disabled}
    aria-label={label}
    aria-haspopup="listbox"
    aria-expanded={open}
    onclick={toggle}
  >
    {#if picked}<span class="mono">{picked.name}</span><span class="mono faint sfx">{idSuffix(picked.id)}</span
      >{:else}<span class="ph">{value ? value : none || placeholder}</span>{/if}
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"
      ><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.6" /></svg
    >
  </button>
  {#if open}
    <div class="pop card">
      <input
        class="input sm"
        bind:this={box}
        bind:value={find}
        oninput={() => (active = 0)}
        onkeydown={keydown}
        placeholder="Filter by name, id, status or tag…"
        aria-label="Filter runs"
      />
      <div class="list" role="listbox" aria-label={label} bind:this={list}>
        {#if offset}
          <button class="opt" class:on={active === 0} role="option" aria-selected={active === 0} onclick={() => pick(0)}
            ><span class="ph">{none}</span></button
          >
        {/if}
        {#each shown as r, i (r.id)}
          <button
            class="opt"
            class:on={active === i + offset}
            role="option"
            aria-selected={active === i + offset}
            onpointermove={() => (active = i + offset)}
            onclick={() => pick(i + offset)}><RunLine run={r} context={context?.get(r.id)} /></button
          >
        {:else}
          <p class="help">No run matches.</p>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .rp {
    position: relative;
    width: 100%;
  }
  .trigger {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    text-align: left;
    cursor: pointer;
  }
  .trigger svg {
    margin-left: auto;
    flex: none;
    color: var(--muted);
  }
  .trigger .sfx {
    font-size: 11px;
  }
  .ph {
    color: var(--muted);
  }
  .pop {
    position: absolute;
    z-index: 40;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: 0 16px 36px -10px rgba(16, 24, 40, 0.35);
  }
  .list {
    max-height: 300px;
    overflow: auto;
    display: flex;
    flex-direction: column;
  }
  .opt {
    display: block;
    width: 100%;
    border: 0;
    background: none;
    padding: 6px 8px;
    border-radius: 7px;
    text-align: left;
    cursor: pointer;
  }
  .opt.on {
    background: var(--accent-soft);
  }
  .help {
    padding: 6px 8px;
    font-size: 12px;
    color: var(--faint);
  }
</style>
