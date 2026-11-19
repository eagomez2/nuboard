<script lang="ts">
  import Icon from './Icon.svelte';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import { api } from '../lib/api';
  import { ask, confirmAction, notice } from '../lib/dialog.svelte';
  import { forgetRecent, recentQueries, rememberQuery, type SavedQuery } from '../lib/queries';

  let text = $state(router.get('q'));
  let input: HTMLInputElement;
  let focused = $state(false);

  $effect(() => {
    const q = router.get('q');
    if (!focused) text = q;
  });

  const KEYWORDS = /\b(where|and|or|not|group by|agg|order by|asc|desc|has|in|limit|exists)\b/g;
  const highlighted = $derived(text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(KEYWORDS, '<b>$1</b>'));

  function submit(e: Event) {
    e.preventDefault();
    router.set({ q: text.trim() || null });
  }

  function onKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      input?.focus();
      input?.select();
    }
  }

  // A query that ran without an error is remembered as recent in this browser.
  $effect(() => {
    const q = router.get('q');
    if (q && app.runs && !app.loading && !app.runs.error) rememberQuery(q);
  });

  // The ▾ menu: saved queries (shared through the workspace folder), recent ones, and saving this one.
  let menu = $state(false);
  let saved = $state<SavedQuery[]>([]);
  let recent = $state<string[]>([]);
  let menuError = $state('');
  let box: HTMLElement;

  const current = $derived(text.trim());
  const isSaved = $derived(saved.some((q) => q.query === current));

  async function openMenu() {
    menu = !menu;
    if (!menu) return;
    recent = recentQueries();
    menuError = '';
    try {
      saved = await api.queries();
    } catch (e) {
      menuError = `Could not load the saved queries: ${(e as Error).message}`;
    }
  }

  function use(query: string) {
    text = query;
    menu = false;
    router.set({ q: query.trim() || null });
  }

  async function saveCurrent() {
    const query = current;
    menu = false;
    const res = await ask('Save this query', [{ label: 'Name', value: '', hint: query }], {
      message: 'Saved queries are kept in queries.json in the workspace folder, so every browser sees them.',
      confirm: 'Save',
    });
    if (!res) return;
    try {
      saved = await api.saveQuery(res[0].trim() || query, query);
    } catch (e) {
      await notice('The query was not saved', (e as Error).message);
    }
  }

  async function remove(q: SavedQuery) {
    menu = false;
    const ok = await confirmAction(`Delete the saved query "${q.name}"?`, 'Runs and views are not touched.', {
      confirm: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      saved = await api.deleteQuery(q.query);
    } catch (e) {
      await notice('The query was not deleted', (e as Error).message);
    }
  }

  function outside(e: PointerEvent) {
    if (menu && box && !box.contains(e.target as Node)) menu = false;
  }

  const examples = [
    'where status != crashed order by started desc',
    'where tags has "sweep" group by config.optim.lr agg mean±std',
    'train/loss.min < 2.4 order by train/loss.min',
    'where project = "vit-ablations" group by config.augment',
  ];
</script>

<svelte:window onkeydown={onKey} onpointerdown={outside} />

<form class="cmd" class:err={!!app.runs?.error} onsubmit={submit} bind:this={box}>
  <Icon name="search" size={17} />
  <div class="field">
    <div class="hl mono" aria-hidden="true">{@html highlighted}&nbsp;</div>
    <input
      bind:this={input}
      bind:value={text}
      class="mono"
      spellcheck="false"
      autocomplete="off"
      placeholder="where status != crashed group by config.lr"
      aria-label="Run query"
      onfocus={() => (focused = true)}
      onblur={() => (focused = false)}
      list="query-examples"
    />
    <datalist id="query-examples">
      {#each examples as ex (ex)}<option value={ex}></option>{/each}
    </datalist>
  </div>
  {#if text}
    <button
      type="button"
      class="clear"
      aria-label="Clear query"
      onclick={() => {
        text = '';
        router.set({ q: null });
      }}
    >
      <Icon name="x" size={14} />
    </button>
  {/if}
  <kbd>⌘K</kbd>
  <button
    type="button"
    class="more"
    aria-label="Saved and recent queries"
    title="Saved and recent queries"
    aria-haspopup="menu"
    aria-expanded={menu}
    onclick={openMenu}
  >
    <Icon name="chevron" size={14} />
  </button>
  {#if menu}
    <div
      class="menu card"
      role="menu"
      tabindex="-1"
      onkeydown={(e) => {
        if (e.key === 'Escape') {
          menu = false;
          input?.focus();
        }
      }}
    >
      <div class="msec">Saved</div>
      {#each saved as q (q.query)}
        <div class="mrow">
          <button type="button" class="mitem" role="menuitem" title={q.query} onclick={() => use(q.query)}>
            <span class="mname">{q.name}</span>
            {#if q.name !== q.query}<span class="mq mono">{q.query}</span>{/if}
          </button>
          <button
            type="button"
            class="mdel"
            aria-label="Delete the saved query {q.name}"
            title="Delete"
            onclick={() => remove(q)}><Icon name="x" size={13} /></button
          >
        </div>
      {:else}
        <p class="mnone">None yet. Write a query, then save it here.</p>
      {/each}
      {#if recent.length}
        <div class="msec">
          Recent in this browser
          <button
            type="button"
            class="mclear"
            onclick={() => {
              forgetRecent();
              recent = [];
            }}>Clear</button
          >
        </div>
        {#each recent as q (q)}
          <button type="button" class="mitem" role="menuitem" title={q} onclick={() => use(q)}>
            <span class="mq mono strong">{q}</span>
          </button>
        {/each}
      {/if}
      {#if menuError}<p class="merr">{menuError}</p>{/if}
      <div class="mfoot">
        <button
          type="button"
          class="btn"
          disabled={!current || isSaved}
          title={!current
            ? 'Write a query first'
            : isSaved
              ? 'This query is saved already'
              : 'Save the query in the bar'}
          onclick={saveCurrent}>Save this query…</button
        >
      </div>
    </div>
  {/if}
</form>
{#if app.runs?.error}
  <div class="qerr" role="alert">{app.runs.error}</div>
{/if}

<style>
  .cmd {
    position: relative;
    flex: 1 1 360px;
    max-width: 680px;
    margin-left: auto;
    height: 40px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: var(--panel);
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px;
    color: var(--muted);
    box-shadow: var(--lift);
    min-width: 0;
  }
  .cmd:focus-within {
    border-color: var(--accent);
  }
  .cmd.err {
    border-color: var(--err);
  }
  .field {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 100%;
  }
  .field input,
  .hl {
    position: absolute;
    inset: 0;
    font-size: 12.5px;
    line-height: 38px;
    white-space: pre;
    overflow: hidden;
    padding: 0;
  }
  .field input {
    border: 0;
    outline: 0;
    background: transparent;
    color: transparent;
    caret-color: var(--text);
    width: 100%;
  }
  .field input::placeholder {
    color: var(--faint);
  }
  .hl {
    color: var(--text);
    pointer-events: none;
    text-overflow: ellipsis;
  }
  .hl :global(b) {
    color: var(--accent);
    font-weight: 500;
  }
  .clear {
    border: 0;
    background: none;
    color: var(--faint);
    padding: 2px;
    display: grid;
  }
  .more {
    flex: none;
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    margin-right: -4px;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--muted);
    cursor: pointer;
  }
  .more:hover,
  .more[aria-expanded='true'] {
    background: var(--panel-2, var(--border));
    color: var(--text);
  }
  .menu {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 40;
    width: min(520px, calc(100vw - 32px));
    max-height: min(480px, 70vh);
    overflow-y: auto;
    padding: 6px;
    display: grid;
    gap: 1px;
    color: var(--text);
    box-shadow: var(--lift);
  }
  .msec {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 8px 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--faint);
  }
  .mclear {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    letter-spacing: 0;
    text-transform: none;
    font-weight: 500;
    color: var(--muted);
    cursor: pointer;
  }
  .mclear:hover {
    color: var(--text);
  }
  .mrow {
    display: flex;
    align-items: center;
    border-radius: 7px;
  }
  .mrow:hover,
  .mrow:focus-within {
    background: var(--panel-2, var(--bg));
  }
  .mrow .mitem {
    flex: 1;
  }
  .mrow:hover .mitem,
  .mrow:focus-within .mitem {
    background: none;
  }
  .mitem {
    display: grid;
    gap: 1px;
    min-width: 0;
    text-align: left;
    padding: 6px 8px;
    border: 0;
    border-radius: 7px;
    background: none;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .mitem:hover,
  .mitem:focus-visible {
    background: var(--panel-2, var(--bg));
  }
  .mname {
    font-size: 13px;
    font-weight: 500;
  }
  .mq {
    font-size: 11.5px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mq.strong {
    color: var(--text);
    font-size: 12px;
  }
  .mdel {
    flex: none;
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    margin-right: 4px;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--faint);
    cursor: pointer;
    opacity: 0;
  }
  .mrow:hover .mdel,
  .mdel:focus-visible {
    opacity: 1;
  }
  .mdel:hover {
    color: var(--err);
  }
  .mnone,
  .merr {
    margin: 0;
    padding: 4px 8px 6px;
    font-size: 12.5px;
    color: var(--faint);
  }
  .merr {
    color: var(--err);
  }
  .mfoot {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
    padding: 8px 4px 2px;
    border-top: 1px solid var(--border);
  }
  kbd {
    font: 11px var(--mono);
    color: var(--faint);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 1px 5px;
  }
  .qerr {
    flex-basis: 100%;
    order: 10;
    color: var(--err);
    font-size: 12.5px;
    text-align: right;
    margin-top: -10px;
  }
</style>
