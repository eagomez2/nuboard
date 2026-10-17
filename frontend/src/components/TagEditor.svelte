<script lang="ts">
  import Icon from './Icon.svelte';
  import TagPills from './TagPills.svelte';
  import { tagStyle } from '../lib/colors';
  import { notice } from '../lib/dialog.svelte';
  import { editTags, knownTags, parseTags } from '../lib/tags';

  // A run's tags, editable in place: remove one with ×, type to add more.
  let { runKey, tags }: { runKey: string; tags: string[] } = $props();

  let editing = $state(false);
  let draft = $state('');
  let input = $state<HTMLInputElement>();
  const suggestions = $derived(knownTags().filter((t) => !tags.includes(t)));

  async function save(add: string[], remove: string[] = []) {
    try {
      await editTags([runKey], add, remove);
    } catch (e) {
      await notice('Not saved', String(e instanceof Error ? e.message : e).replace(/^\d+ /, ''));
    }
  }
  function submit(e: SubmitEvent) {
    e.preventDefault();
    const add = parseTags(draft);
    draft = '';
    if (add.length) save(add);
    else editing = false;
  }
  function open() {
    editing = true;
    queueMicrotask(() => input?.focus());
  }
</script>

{#if editing}
  <form class="tagedit" onsubmit={submit}>
    {#each tags as t (t)}
      <span class="tagpill" style={tagStyle(t)}
        >{t}<button type="button" class="x" aria-label="Remove tag {t}" onclick={() => save([], [t])}>×</button></span
      >
    {/each}
    <input
      bind:this={input}
      class="input"
      placeholder="add a tag"
      aria-label="Add a tag"
      list="tagedit-known"
      bind:value={draft}
      onkeydown={(e) => e.key === 'Escape' && ((draft = ''), (editing = false))}
      autocomplete="off"
      spellcheck="false"
    />
    <datalist id="tagedit-known">
      {#each suggestions as s (s)}<option value={s}></option>{/each}
    </datalist>
    <button type="button" class="btn btn-ghost done" onclick={() => ((draft = ''), (editing = false))}>Done</button>
  </form>
{:else}
  <span class="tagview">
    {#if tags.length}<TagPills {tags} />{/if}
    <button class="btn btn-ghost edit" aria-label="Edit tags" title="Edit tags" onclick={open}
      ><Icon name="tag" size={13} />{tags.length ? '' : ' Add tags'}</button
    >
  </span>
{/if}

<style>
  .tagview,
  .tagedit {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }
  .edit {
    height: 22px;
    padding: 0 5px;
    font-size: 12px;
    color: var(--faint);
  }
  .x {
    border: 0;
    background: none;
    color: inherit;
    padding: 0 0 0 4px;
    cursor: pointer;
    font: inherit;
  }
  .input {
    height: 24px;
    width: 140px;
    font-size: 12px;
  }
  .done {
    height: 24px;
    padding: 0 6px;
    font-size: 12px;
  }
</style>
