<script lang="ts">
  import Icon from './Icon.svelte';
  import { keyFilter, splitMarked } from '../lib/keyfilter';
  import { groupByPrefix, MANY_VALUES, type ParamInfo } from '../lib/sweep';

  // The Parameters button of the Sweeps page: a searchable list of every differing key, grouped by
  // prefix, with the chosen keys as chips that can be reordered and removed.
  let {
    infos,
    chosen,
    metric,
    hide,
    canHide,
    hidden,
    onpick,
    onhide,
  }: {
    infos: ParamInfo[];
    chosen: string[];
    metric: string;
    /** The project's hide rules, in the settings filter syntax (`!seed !.path`). */
    hide: string;
    /** Whether hide rules can be edited: the runs shown are from one project. */
    canHide: boolean;
    hidden: (key: string) => boolean;
    /** A new choice of keys in order, `[]` for none, or null for the defaults. */
    onpick: (keys: string[] | null) => void;
    onhide: (text: string) => void;
  } = $props();

  let open = $state(false);
  let anchor = $state<HTMLDivElement>();
  let search = $state<HTMLInputElement>();
  let query = $state('');
  let regex = $state(false);
  let showHidden = $state(false);
  let folded = $state<Set<string>>(new Set());
  let hideDraft = $state('');
  let dragKey = $state<string | null>(null);
  // the list is fixed to the window, so a panel that clips its content cannot cut it off
  let place = $state('');
  function position() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, window.innerWidth - 568));
    const below = window.innerHeight - r.bottom - 18;
    // open upwards when there is clearly more room above the button
    place =
      below < 260 && r.top - 18 > below
        ? `bottom:${window.innerHeight - r.top + 6}px;left:${left}px;max-height:${r.top - 18}px`
        : `top:${r.bottom + 6}px;left:${left}px;max-height:${Math.max(120, below)}px`;
  }

  const finder = $derived(keyFilter(query, { regex }));
  const hiddenCount = $derived(infos.filter((p) => hidden(p.key)).length);
  const listed = $derived(infos.filter((p) => (showHidden || !hidden(p.key)) && finder.test(p.key)));
  const groups = $derived(groupByPrefix(listed));
  const byKey = $derived(new Map(infos.map((p) => [p.key, p])));

  $effect(() => {
    if (!open) return;
    // any scrolling container may move the button; follow it
    document.addEventListener('scroll', position, true);
    return () => document.removeEventListener('scroll', position, true);
  });
  function toggleOpen() {
    open = !open;
    if (open) {
      hideDraft = hide;
      position();
      queueMicrotask(() => search?.focus());
    }
  }
  function toggle(key: string) {
    onpick(chosen.includes(key) ? chosen.filter((k) => k !== key) : [...chosen, key]);
  }
  function fold(prefix: string) {
    const next = new Set(folded);
    if (next.has(prefix)) next.delete(prefix);
    else next.add(prefix);
    folded = next;
  }
  function drop(target: string) {
    if (!dragKey || dragKey === target) return;
    const rest = chosen.filter((k) => k !== dragKey);
    rest.splice(rest.indexOf(target), 0, dragKey);
    dragKey = null;
    onpick(rest);
  }
  function saveHide() {
    if (hideDraft.trim() !== hide.trim()) onhide(hideDraft);
  }
  const hideError = $derived(keyFilter(hideDraft).error);
  // the part of a key after its group's prefix, with the search matches marked
  function rest(key: string, prefix: string) {
    const from = prefix ? prefix.length + 1 : 0;
    const ranges = finder
      .highlight(key)
      .filter(([, b]) => b > from)
      .map(([a, b]) => [Math.max(a, from) - from, b - from] as [number, number]);
    return splitMarked(key.slice(from), ranges);
  }
  const short = (key: string) => key.split('.').slice(-2).join('.');
  const typeOf = (p: ParamInfo) => (p.numeric ? 'number' : 'category');
</script>

<svelte:window
  onresize={() => open && position()}
  onpointerdown={(e) => open && anchor && !anchor.contains(e.target as Node) && (open = false)}
  onkeydown={(e) => {
    if (e.key === 'Escape' && open) {
      e.preventDefault();
      open = false;
    }
  }}
/>

<div class="params">
  <div class="anchor" bind:this={anchor}>
    <button class="btn sm" aria-expanded={open} aria-haspopup="dialog" onclick={toggleOpen}>
      <Icon name="search" size={14} /> Parameters
      <span class="faint">{chosen.length} of {infos.length - hiddenCount}</span>
    </button>
    {#if open}
      <div class="card picker" role="dialog" aria-label="Parameters" style={place}>
        <div class="find" class:bad={!!finder.error}>
          <Icon name="search" size={14} />
          <input
            class="mono"
            bind:this={search}
            bind:value={query}
            placeholder="Search  (/regex/, !exclude)"
            aria-label="Search parameters"
            aria-invalid={!!finder.error}
            title={finder.error ?? undefined}
            spellcheck="false"
            autocomplete="off"
          />
          <button
            class="tog mono"
            aria-pressed={regex}
            aria-label="Regular expression"
            title="Every term is a regular expression"
            onclick={() => (regex = !regex)}>.*</button
          >
        </div>
        <div class="list">
          {#each groups as g (g.prefix)}
            <div class="group">
              {#if g.prefix}
                <button
                  class="ghead mono"
                  aria-expanded={!folded.has(g.prefix)}
                  title={g.prefix}
                  onclick={() => fold(g.prefix)}
                  ><span class="caret" class:shut={folded.has(g.prefix)}><Icon name="chevron" size={12} /></span>
                  <span class="trunc">{g.prefix}</span><span class="faint">{g.items.length}</span></button
                >
              {/if}
              {#if !folded.has(g.prefix)}
                {#each g.items as p (p.key)}
                  <label class="row" class:sub={!!g.prefix} class:hid={hidden(p.key)} title={p.key}>
                    <input type="checkbox" checked={chosen.includes(p.key)} onchange={() => toggle(p.key)} />
                    <span class="key mono trunc" aria-label={p.key}
                      >{#each rest(p.key, g.prefix) as part, i (i)}{#if part.mark}<mark>{part.text}</mark
                          >{:else}{part.text}{/if}{/each}</span
                    >
                    <span class="meta">
                      {#if p.many}<span
                          class="flag"
                          title="More than {MANY_VALUES} values: the axis shows the most common">many values</span
                        >{:else if p.unique}<span class="flag" title="A different value in every run">id-like</span
                        >{:else if p.long}<span class="flag">long text</span>{/if}
                      <span class="faint">{typeOf(p)} · {p.distinct} {p.distinct === 1 ? 'value' : 'values'}</span>
                      <span class="imp" title="Rank correlation with {metric}: {p.score?.toFixed(2) ?? 'n/a'}"
                        ><span style="width:{(p.score ?? 0) * 100}%"></span></span
                      >
                    </span>
                  </label>
                {/each}
              {/if}
            </div>
          {:else}
            <p class="none faint">No parameter matches.</p>
          {/each}
        </div>
        <div class="foot">
          <button class="btn btn-ghost sm" onclick={() => onpick([])}>Clear all</button>
          <button class="btn btn-ghost sm" onclick={() => onpick(null)}>Reset to defaults</button>
          <span class="grow"></span>
          {#if hiddenCount}
            <button class="btn btn-ghost sm" aria-pressed={showHidden} onclick={() => (showHidden = !showHidden)}
              >{showHidden ? 'Hide' : 'Show'} {hiddenCount} hidden</button
            >
          {/if}
        </div>
        {#if canHide}
          <div class="hide">
            <label class="label" for="sweep-hide">Hide matching keys</label>
            <input
              id="sweep-hide"
              class="input mono sm"
              bind:value={hideDraft}
              placeholder="!seed !.path !logging."
              aria-invalid={!!hideError}
              title="Keys the filter excludes are hidden for everyone, saved in the project's sweeps.json"
              spellcheck="false"
              autocomplete="off"
              onblur={saveHide}
              onkeydown={(e) => e.key === 'Enter' && saveHide()}
            />
          </div>
        {/if}
      </div>
    {/if}
  </div>
  {#each chosen as key (key)}
    {@const p = byKey.get(key)}
    <span
      class="chip param"
      class:dragging={dragKey === key}
      title="{key}{p?.score != null ? ` · correlation ${p.score.toFixed(2)}` : ''} · drag to reorder"
      draggable="true"
      role="listitem"
      ondragstart={(e) => {
        dragKey = key;
        e.dataTransfer?.setData('text/plain', key);
      }}
      ondragend={() => (dragKey = null)}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        drop(key);
      }}
    >
      <span class="mono trunc">{short(key)}</span>
      {#if p?.score != null}<span class="imp"><span style="width:{p.score * 100}%"></span></span>{/if}
      <button class="x" aria-label="Remove {key}" onclick={() => toggle(key)}>×</button>
    </span>
  {:else}
    <span class="faint">
      {infos.length ? 'No parameters picked.' : 'All runs share the same config; there is nothing to sweep over.'}
    </span>
  {/each}
</div>

<style>
  .params {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    padding: 12px 14px 4px;
  }
  .anchor {
    position: relative;
  }
  .picker {
    position: fixed;
    z-index: 30;
    width: min(560px, calc(100vw - 48px));
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: 0 16px 36px -10px rgba(16, 24, 40, 0.35);
  }
  .find,
  .foot,
  .hide {
    flex: none;
  }
  .find {
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0 6px 0 9px;
    background: var(--panel);
    color: var(--faint);
  }
  .find.bad {
    border-color: var(--err);
  }
  .find input {
    flex: 1;
    min-width: 0;
    border: 0;
    background: none;
    height: 30px;
    color: var(--text);
    outline: none;
    font-size: 13px;
  }
  .tog {
    border: 1px solid transparent;
    background: none;
    border-radius: 6px;
    padding: 1px 6px;
    color: var(--muted);
    font-size: 12px;
  }
  .tog[aria-pressed='true'] {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }
  .list {
    flex: 1 1 auto;
    min-height: 0;
    max-height: 420px;
    overflow: auto;
    display: flex;
    flex-direction: column;
  }
  .ghead {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: 0;
    background: none;
    padding: 5px 4px;
    font-size: 12px;
    color: var(--muted);
    text-align: left;
  }
  .caret {
    display: inline-flex;
    transition: transform 0.12s;
  }
  .caret.shut {
    transform: rotate(-90deg);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
  }
  .row.sub {
    padding-left: 22px;
  }
  .row:hover {
    background: var(--panel-2);
  }
  .row.hid {
    opacity: 0.55;
  }
  .key {
    flex: 1;
    min-width: 0;
  }
  .meta {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    white-space: nowrap;
  }
  .flag {
    color: var(--warn, var(--muted));
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0 6px;
    font-size: 11px;
  }
  mark {
    background: none;
    color: var(--accent);
    font-weight: 650;
  }
  .none {
    margin: 6px;
  }
  .foot {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .grow {
    flex: 1;
  }
  .hide {
    display: flex;
    align-items: center;
    gap: 8px;
    border-top: 1px solid var(--border);
    padding-top: 8px;
  }
  .hide input {
    flex: 1;
  }
  .hide input[aria-invalid='true'] {
    border-color: var(--err);
  }
  .param {
    border: 1px solid transparent;
    background: var(--accent-soft);
    color: var(--accent);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    max-width: 260px;
    min-width: 0;
    cursor: grab;
  }
  .param.dragging {
    opacity: 0.5;
  }
  .x {
    border: 0;
    background: none;
    color: var(--faint);
    padding: 0 0 0 2px;
    font-size: 14px;
    line-height: 1;
  }
  .x:hover {
    color: var(--text);
  }
  .imp {
    width: 34px;
    height: 5px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
    display: inline-block;
    flex: none;
  }
  .imp span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
</style>
