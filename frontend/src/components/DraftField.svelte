<script module lang="ts">
  // Unsaved drafts outlive the field: switching to another run and back brings the draft back,
  // and leaving the page with one asks first.
  const drafts = new Map<string, string>();
  let guarded = false;
  function guard() {
    if (guarded || typeof window === 'undefined') return;
    guarded = true;
    window.addEventListener('beforeunload', (e) => {
      if (drafts.size) e.preventDefault();
    });
  }
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  // A text field that saves only on Save (or Ctrl/Cmd+Enter; Enter for one line) and goes back on
  // Cancel (or Esc). The buttons show once the text differs from what is saved.
  let {
    id,
    value,
    multiline = false,
    rows = 3,
    placeholder = '',
    label = '',
    disabled = false,
    onsave,
  }: {
    /** Names the draft, such as "conclusion:<hyp>:<run>", so it survives switching away. */
    id: string;
    value: string;
    multiline?: boolean;
    rows?: number;
    placeholder?: string;
    label?: string;
    disabled?: boolean;
    onsave: (v: string) => void;
  } = $props();

  let text = $state('');
  // a new field, or a new saved value with no draft in progress: show the saved value
  $effect.pre(() => {
    const key = id;
    const saved = value;
    untrack(() => {
      const d = drafts.get(key);
      if (d !== undefined && d !== saved) text = d;
      else {
        drafts.delete(key);
        text = saved;
      }
    });
  });
  const dirty = $derived(text !== value);

  function input(v: string) {
    text = v;
    if (v !== value) {
      drafts.set(id, v);
      guard();
    } else drafts.delete(id);
  }
  function save() {
    if (!dirty) return;
    drafts.delete(id);
    onsave(text);
  }
  function cancel() {
    drafts.delete(id);
    text = value;
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && dirty) {
      e.preventDefault();
      e.stopPropagation();
      cancel();
    } else if (e.key === 'Enter' && (!multiline || e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      save();
    }
  }
</script>

<div class="draft" class:dirty>
  {#if multiline}
    <textarea
      class="input"
      {rows}
      {placeholder}
      {disabled}
      aria-label={label || undefined}
      value={text}
      oninput={(e) => input(e.currentTarget.value)}
      onkeydown={keydown}></textarea>
  {:else}
    <input
      class="input"
      {placeholder}
      {disabled}
      aria-label={label || undefined}
      value={text}
      oninput={(e) => input(e.currentTarget.value)}
      onkeydown={keydown}
    />
  {/if}
  {#if dirty && !disabled}
    <div class="bar">
      <button class="btn btn-primary sm" onclick={save}>Save</button>
      <button class="btn sm" onclick={cancel}>Cancel</button>
      <span class="hint">{multiline ? 'Ctrl+Enter' : 'Enter'} saves · Esc cancels</span>
    </div>
  {/if}
</div>

<style>
  .draft {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .draft > :global(.input) {
    width: 100%;
  }
  textarea.input {
    height: auto;
    padding: 6px 10px;
    resize: vertical;
  }
  .dirty > :global(.input) {
    border-color: var(--accent);
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .hint {
    margin-left: auto;
    font-size: 11px;
    color: var(--faint);
  }
</style>
