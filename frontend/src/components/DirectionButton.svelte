<script lang="ts">
  import {
    canSaveDirections,
    directionArrow,
    directionHint,
    directionOf,
    setDirection,
    type Extreme,
  } from '../lib/directions.svelte';
  import { router } from '../lib/router.svelte';

  /**
   * The ↑ / ↓ next to a scalar picker: which way is better for `name` (lib/directions.svelte.ts).
   * A click changes only this view (`dir` in the URL). When the view's choice differs from the
   * project's, "Save for everyone" writes it to the project (only with one project shown) and
   * "Reset" goes back to it. A faint, dashed arrow is a guess from the name (or `fallback`, a
   * direction the caller kept); ↕ means the projects shown disagree. A save says what the
   * project's direction was when shown, so one changed meanwhile by someone else is not
   * overwritten: the save is refused and the new direction shown. Started with `--lock-directions`,
   * the viewer offers no Save.
   */
  let { projects, name, fallback }: { projects: string[]; name: string; fallback?: Extreme } = $props();

  const view = $derived(router.get('dir'));
  const own = $derived.by(() => {
    const g = directionOf(projects, name);
    return !g.set && !g.mixed && fallback ? { ...g, direction: fallback } : g;
  });
  const direction = $derived(view === 'min' || view === 'max' ? directionOf(projects, name, true, view) : own);
  const changed = $derived(direction.direction !== own.direction || (!!view && !own.set));
  const saveTo = $derived(projects.length === 1 ? projects[0] : null);
  let error = $state('');
  let saving = $state(false);

  function flip() {
    const next: Extreme = direction.direction === 'max' ? 'min' : 'max';
    // back to what the project says: nothing left to save
    router.set({ dir: own.set && next === own.direction ? null : next });
  }
  async function save() {
    if (!saveTo || !direction.direction) return;
    error = '';
    saving = true;
    try {
      await setDirection(saveTo, name, direction.direction, own.set ? own.direction : null);
      router.set({ dir: null });
    } catch (e) {
      error = `Not saved: ${(e as Error).message}`;
    } finally {
      saving = false;
    }
  }
</script>

<button
  class="btn direction"
  class:guess={!direction.set}
  class:changed
  aria-label="Direction of {name}: {direction.direction ?? 'mixed'}"
  title={directionHint(name, direction, saveTo, changed)}
  onclick={flip}>{directionArrow(direction)}</button
>
{#if changed}
  {#if saveTo && canSaveDirections()}
    <button
      class="btn btn-ghost sm"
      disabled={saving}
      title="Keep {direction.direction === 'min'
        ? '↓ lower'
        : '↑ higher'} is better for {name} in {saveTo}, for everyone viewing it"
      onclick={save}>Save for everyone</button
    >
  {/if}
  <button class="btn btn-ghost sm" title="Go back to the project's direction" onclick={() => router.set({ dir: null })}
    >Reset</button
  >
{/if}
{#if error}<span class="err">{error}</span>{/if}

<style>
  .direction {
    margin-left: -4px;
    padding: 0 9px;
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
  }
  /* a guess from the name, not set in the project */
  .direction.guess {
    color: var(--faint);
    border-style: dashed;
  }
  /* this view's own choice, not saved */
  .direction.changed {
    color: var(--accent);
    border-color: var(--accent);
    border-style: dashed;
  }
  .sm {
    font-size: 12px;
  }
  .err {
    color: var(--err);
    font-size: 12px;
  }
</style>
