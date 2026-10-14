<script lang="ts">
  import Icon from './Icon.svelte';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

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

  const examples = [
    'where status != crashed order by started desc',
    'where tags has "sweep" group by config.optim.lr agg mean±std',
    'train/loss.min < 2.4 order by train/loss.min',
    'where project = "vit-ablations" group by config.augment',
  ];
</script>

<svelte:window onkeydown={onKey} />

<form class="cmd" class:err={!!app.runs?.error} onsubmit={submit}>
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
</form>
{#if app.runs?.error}
  <div class="qerr" role="alert">{app.runs.error}</div>
{/if}

<style>
  .cmd {
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
