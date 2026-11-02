<script lang="ts">
  // The Categories dialog of the Hypotheses page: names, colors and icons of hypothesis verdicts, and
  // names, colors and the dead-end switch of run outcomes. Edits a copy; Save hands it back.
  import Icon from './Icon.svelte';
  import VerdictIcon from './VerdictIcon.svelte';
  import {
    COLORS,
    ICONS,
    MAX_CATEGORIES,
    colorVar,
    type Board,
    type CategoryColor,
    type Outcome,
    type Verdict,
  } from '../lib/hypotheses';

  let {
    board,
    onsave,
    onclose,
  }: { board: Board; onsave: (b: Pick<Board, 'verdicts' | 'outcomes'>) => void; onclose: () => void } = $props();

  let el: HTMLDialogElement;
  // A working copy, so Cancel leaves the board as it was
  // svelte-ignore state_referenced_locally
  let verdicts = $state<Verdict[]>(structuredClone($state.snapshot(board.verdicts)));
  // svelte-ignore state_referenced_locally
  let outcomes = $state<Outcome[]>(structuredClone($state.snapshot(board.outcomes)));

  $effect(() => {
    el.showModal();
  });

  const freeColor = (list: { color: CategoryColor }[]): CategoryColor =>
    COLORS.find((c) => !list.some((x) => x.color === c)) ?? 'gray';
  // a temporary id; the server derives a clean one from the label
  const tempId = (kind: string) => `${kind}-${Math.random().toString(36).slice(2, 8)}`;

  function save(e: SubmitEvent) {
    e.preventDefault();
    onsave({ verdicts: $state.snapshot(verdicts), outcomes: $state.snapshot(outcomes) });
  }
</script>

<dialog
  bind:this={el}
  class="card cats"
  aria-labelledby="cats-title"
  oncancel={(e) => {
    e.preventDefault();
    onclose();
  }}
  onclick={(e) => {
    if (e.target === el) onclose();
  }}
>
  <form onsubmit={save}>
    <header>
      <div>
        <span class="label">Project setting</span>
        <h2 id="cats-title">Categories</h2>
      </div>
    </header>

    <section>
      <span class="label">Hypothesis verdicts</span>
      <p class="help">Was the idea right? Shown as a badge and the top edge of each card.</p>
      {#each verdicts as v, i (i)}
        <div class="row">
          <input class="input" bind:value={v.label} maxlength="40" aria-label="Verdict name" />
          <div class="swatches" role="group" aria-label="Color">
            {#each COLORS as c (c)}
              <button
                type="button"
                class="sw"
                aria-pressed={v.color === c}
                aria-label={c}
                style="background:{colorVar(c)}"
                onclick={() => (v.color = c)}
              ></button>
            {/each}
          </div>
          <div class="swatches" role="group" aria-label="Icon">
            {#each ICONS as ic (ic)}
              <button
                type="button"
                class="ib"
                aria-pressed={v.icon === ic}
                aria-label={ic}
                style="color:{colorVar(v.color)}"
                onclick={() => (v.icon = ic)}><VerdictIcon icon={ic} /></button
              >
            {/each}
          </div>
          <button
            type="button"
            class="btn btn-ghost icon"
            aria-label="Delete {v.label}"
            title="Delete"
            disabled={verdicts.length < 2}
            onclick={() => verdicts.splice(i, 1)}><Icon name="trash" size={15} /></button
          >
        </div>
      {/each}
      <button
        type="button"
        class="btn sm add"
        disabled={verdicts.length >= MAX_CATEGORIES}
        onclick={() =>
          verdicts.push({ id: tempId('verdict'), label: 'New verdict', color: freeColor(verdicts), icon: 'circle' })}
        ><Icon name="plus" size={14} /> Add verdict</button
      >
    </section>

    <section>
      <span class="label">Run outcomes</span>
      <p class="help">
        Did you keep building on the run? Shown as the dot next to each run. Dead ends are faded and can be hidden.
      </p>
      {#each outcomes as o, i (i)}
        <div class="row">
          <input class="input" bind:value={o.label} maxlength="40" aria-label="Outcome name" />
          <div class="swatches" role="group" aria-label="Color">
            {#each COLORS as c (c)}
              <button
                type="button"
                class="sw"
                aria-pressed={o.color === c}
                aria-label={c}
                style="background:{colorVar(c)}"
                onclick={() => (o.color = c)}
              ></button>
            {/each}
          </div>
          <label class="tg">
            <button
              type="button"
              class="switch"
              role="switch"
              aria-checked={o.dead_end}
              aria-label="Dead end"
              onclick={() => (o.dead_end = !o.dead_end)}
            ></button>Dead end</label
          >
          <button
            type="button"
            class="btn btn-ghost icon"
            aria-label="Delete {o.label}"
            title="Delete"
            disabled={outcomes.length < 2}
            onclick={() => outcomes.splice(i, 1)}><Icon name="trash" size={15} /></button
          >
        </div>
      {/each}
      <button
        type="button"
        class="btn sm add"
        disabled={outcomes.length >= MAX_CATEGORIES}
        onclick={() =>
          outcomes.push({ id: tempId('outcome'), label: 'New outcome', color: freeColor(outcomes), dead_end: false })}
        ><Icon name="plus" size={14} /> Add outcome</button
      >
    </section>

    <p class="help">
      Up to {MAX_CATEGORIES} of each. Hypotheses and runs whose category is deleted show as Open (or the first category).
    </p>
    <footer>
      <button type="button" class="btn" onclick={onclose}>Cancel</button>
      <button type="submit" class="btn btn-primary">Save</button>
    </footer>
  </form>
</dialog>

<style>
  .cats {
    width: min(760px, calc(100vw - 32px));
    margin: auto;
    padding: 0;
    color: var(--text);
  }
  .cats::backdrop {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
    backdrop-filter: blur(2px);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 20px 22px;
  }
  h2 {
    margin: 2px 0 0;
    font-size: 18px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .help {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
  }
  .row .input {
    flex: 1 1 160px;
  }
  .swatches {
    display: flex;
    gap: 4px;
  }
  .sw {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid transparent;
    padding: 0;
  }
  .sw[aria-pressed='true'] {
    border-color: var(--text);
  }
  .ib {
    width: 26px;
    height: 26px;
    border-radius: 7px;
    border: 1px solid transparent;
    background: transparent;
    display: grid;
    place-items: center;
    padding: 0;
  }
  .ib[aria-pressed='true'] {
    border-color: currentColor;
  }
  .tg {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    color: var(--muted);
    font-size: 13px;
  }
  .add {
    align-self: flex-start;
  }
  .icon {
    width: 32px;
    padding: 0;
    justify-content: center;
  }
  footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
</style>
