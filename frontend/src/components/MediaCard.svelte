<script lang="ts">
  import Icon from './Icon.svelte';
  import MediaView from './MediaView.svelte';
  import type { MediaItem, RunBrief } from '../lib/api';
  import { api } from '../lib/api';
  import type { AudioOptions } from '../lib/media';

  // One run's items under one key, with its own step slider (as in TensorBoard).
  let {
    run,
    items,
    target,
    nearest = false,
    title,
    color,
    player,
    audioOptions,
    onsave,
    onzoom,
    selecting = false,
    isSelected = () => false,
    onselect = () => {},
  }: {
    run: RunBrief;
    items: MediaItem[];
    target: number | null; // null: the latest step
    nearest?: boolean; // closest step to `target` (best-step mode) instead of the last one before it
    title: string;
    color: string;
    player: string;
    audioOptions: AudioOptions;
    onsave: (it: MediaItem) => void;
    onzoom: (it: MediaItem) => void;
    selecting?: boolean; // show a checkbox to pick the shown item for a report
    isSelected?: (it: MediaItem) => boolean;
    onselect?: (it: MediaItem, on: boolean) => void;
  } = $props();

  // A step picked on this card's own slider; cleared whenever the page-wide step changes.
  let own = $state<number | null>(null);
  $effect(() => {
    void target;
    own = null;
  });

  const steps = $derived(items.map((i) => i.step));
  const shownIdx = $derived.by(() => {
    if (!items.length) return -1;
    const want = own ?? target;
    if (want === null) return items.length - 1;
    if (nearest && own === null) {
      let best = 0;
      for (let i = 1; i < items.length; i++)
        if (Math.abs(items[i].step - want) < Math.abs(items[best].step - want)) best = i;
      return best;
    }
    let idx = 0;
    for (let i = 0; i < items.length; i++) if (items[i].step <= want) idx = i;
    return idx;
  });
  const it = $derived(shownIdx >= 0 ? items[shownIdx] : null);
  const zoomable = $derived(!!it && it.kind !== 'audio' && !it.mime.startsWith('audio/'));
</script>

<figure class="card cell" class:picked={selecting && !!it && isSelected(it)}>
  <figcaption>
    {#if selecting && it}
      <input
        type="checkbox"
        class="pick"
        aria-label="Select {title} at step {it.step}"
        checked={isSelected(it)}
        onchange={(e) => onselect(it, e.currentTarget.checked)}
      />
    {/if}
    <i class="dot" style="background:{color}"></i>
    <span class="mono name" title="{run.name}&#10;{run.path}">{title}</span>
    {#if it}<span class="faint mono step">Step {it.step.toLocaleString()}</span>{/if}
    {#if it}
      <span class="acts">
        {#if zoomable}
          <button class="icon" title="Open large" aria-label="Open large" onclick={() => onzoom(it)}
            ><Icon name="search" size={14} /></button
          >
        {/if}
        {#if it.index !== undefined}
          <a
            class="icon"
            title="Download"
            aria-label="Download"
            href={api.mediaUrl(run.key, it.index)}
            download="{run.name}-{it.key.replaceAll('/', '_')}-{it.step}"><Icon name="download" size={14} /></a
          >
        {/if}
        <button class="icon" title="Add to a report" aria-label="Add to a report" onclick={() => onsave(it)}
          ><Icon name="bookmark" size={14} /></button
        >
      </span>
    {/if}
  </figcaption>
  {#if !it}
    <div class="none faint">Nothing logged under this key</div>
  {:else}
    <MediaView runKey={run.key} runName={run.name} item={it} {player} {audioOptions} group={it.key} {color} />
  {/if}
  {#if steps.length > 1}
    <label class="slider">
      <input
        type="range"
        min="0"
        max={steps.length - 1}
        value={shownIdx}
        aria-label="Step of {title}"
        oninput={(e) => (own = steps[Number(e.currentTarget.value)])}
      />
      <span class="faint mono">{shownIdx + 1}/{steps.length}</span>
    </label>
  {/if}
</figure>

<style>
  .cell {
    margin: 0;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .picked {
    outline: 2px solid var(--accent);
    outline-offset: -1px;
  }
  .pick {
    margin: 0;
    accent-color: var(--accent);
    flex: none;
  }
  figcaption {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    min-width: 0;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    flex: 1;
  }
  .step {
    flex: none;
    font-size: 11.5px;
  }
  .acts {
    display: inline-flex;
    gap: 2px;
    flex: none;
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
  .icon:hover {
    background: var(--panel-2);
    color: var(--accent);
  }
  .faint {
    color: var(--faint);
  }
  .none {
    padding: 24px 8px;
    text-align: center;
    font-size: 13px;
  }
  .slider {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
  }
  .slider input {
    flex: 1;
    min-width: 0;
    accent-color: var(--accent);
  }
</style>
