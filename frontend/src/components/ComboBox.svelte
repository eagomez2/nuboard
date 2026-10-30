<script lang="ts">
  import type { ComboOption } from '../lib/dialog.svelte';
  import { comboMatches, highlight } from '../lib/combo';

  // A text box with a list of choices that opens on focus and narrows as you type (ARIA combobox).
  // The value is what is typed or picked; `preselect` is highlighted first but not typed in.
  let {
    id,
    value = $bindable(),
    options,
    preselect = '',
    placeholder = '',
    newLabel = 'New',
    describedby,
    limit = 50,
  }: {
    id: string;
    value?: string; // undefined until the dialog fills its values in
    options: ComboOption[];
    preselect?: string;
    placeholder?: string;
    newLabel?: string;
    describedby?: string;
    /** Options listed at most; the rest are counted, and typing narrows to them. */
    limit?: number;
  } = $props();

  let open = $state(false);
  let active = $state(-1);
  let list = $state<HTMLUListElement>();

  const matches = $derived(comboMatches(options, value ?? ''));
  // the first `limit` matches, plus the preselected option when it is further down
  const shown = $derived.by(() => {
    const first = matches.slice(0, limit);
    const pre = matches.find((o) => o.value === preselect);
    return pre && !first.includes(pre) ? [...first, pre] : first;
  });
  const more = $derived(matches.length - shown.length);
  const typed = $derived((value ?? '').trim());
  const isNew = $derived(!!typed && !options.some((o) => o.value.toLowerCase() === typed.toLowerCase()));
  const count = $derived(shown.length + (isNew ? 1 : 0));

  function openList() {
    open = true;
    const pre = shown.findIndex((o) => o.value === preselect);
    active = typed ? (shown.length || isNew ? 0 : -1) : pre;
  }

  function pick(i: number) {
    value = i < shown.length ? shown[i].value : typed;
    open = false;
  }

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) return openList();
      if (!count) return;
      if (e.key === 'ArrowDown') active = (active + 1) % count;
      else active = active <= 0 ? count - 1 : active - 1;
      queueMicrotask(() => list?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }));
    } else if (e.key === 'Enter' && open && active >= 0 && active < count) {
      e.preventDefault(); // pick, and let a second Enter submit the form
      pick(active);
    } else if (e.key === 'Escape' && open) {
      e.preventDefault();
      e.stopPropagation(); // close the list, not the dialog
      open = false;
    }
  }
</script>

<div class="combo">
  <input
    {id}
    class="input"
    type="text"
    role="combobox"
    aria-expanded={open}
    aria-controls="{id}-list"
    aria-autocomplete="list"
    aria-activedescendant={open && active >= 0 ? `${id}-opt-${active}` : undefined}
    aria-describedby={describedby}
    autocomplete="off"
    spellcheck="false"
    {placeholder}
    bind:value
    onfocus={openList}
    onclick={() => !open && openList()}
    oninput={() => {
      open = true;
      active = shown.length || isNew ? 0 : -1;
    }}
    onblur={() => (open = false)}
    {onkeydown}
  />
  {#if open && count}
    <ul class="list card" id="{id}-list" role="listbox" bind:this={list}>
      {#each shown as o, i (o.value)}
        <!-- svelte-ignore a11y_click_events_have_key_events (the text box handles the keys) -->
        <li
          id="{id}-opt-{i}"
          role="option"
          aria-selected={i === active}
          onmousedown={(e) => e.preventDefault()}
          onclick={() => pick(i)}
          onmousemove={() => (active = i)}
        >
          <span class="title">
            {#each highlight(o.label, typed) as part, j (j)}{#if part.hit}<mark>{part.text}</mark
                >{:else}{part.text}{/if}{/each}
          </span>
          {#if o.detail}
            <span class="detail mono">
              {#each highlight(o.detail, typed) as part, j (j)}{#if part.hit}<mark>{part.text}</mark
                  >{:else}{part.text}{/if}{/each}
            </span>
          {/if}
          {#if o.value === preselect}<span class="tag">last used</span>{/if}
        </li>
      {/each}
      {#if more > 0}
        <li class="more" role="presentation">and {more.toLocaleString()} more, type to narrow</li>
      {/if}
      {#if isNew}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <li
          id="{id}-opt-{shown.length}"
          role="option"
          class="new"
          aria-selected={active === shown.length}
          onmousedown={(e) => e.preventDefault()}
          onclick={() => pick(shown.length)}
          onmousemove={() => (active = shown.length)}
        >
          {newLabel} “{typed}”
        </li>
      {/if}
    </ul>
  {/if}
</div>

<style>
  .combo {
    position: relative;
  }
  .combo .input {
    width: 100%;
  }
  .list {
    position: absolute;
    z-index: 20;
    left: 0;
    right: 0;
    top: calc(100% + 4px);
    margin: 0;
    padding: 4px;
    list-style: none;
    max-height: 240px;
    overflow: auto;
    box-shadow: 0 12px 28px -8px rgba(16, 24, 40, 0.35);
  }
  li {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 6px 8px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13.5px;
  }
  li[aria-selected='true'] {
    background: var(--accent-soft);
  }
  .title {
    flex: 0 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .detail {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--faint);
    font-size: 12px;
  }
  .tag {
    margin-left: auto;
    color: var(--faint);
    font-size: 11.5px;
    white-space: nowrap;
  }
  .more {
    cursor: default;
    color: var(--faint);
    font-size: 12.5px;
  }
  .new {
    color: var(--accent);
    font-weight: 550;
  }
  mark {
    background: none;
    color: var(--accent);
    font-weight: 650;
  }
</style>
