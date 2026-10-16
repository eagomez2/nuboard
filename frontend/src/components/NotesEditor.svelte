<script lang="ts">
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';
  import { api, type RunBrief } from '../lib/api';
  import { app } from '../lib/state.svelte';

  // A run's notes, written in Markdown and kept in its annotations.json.
  let { run }: { run: RunBrief } = $props();

  let editing = $state(false);
  let draft = $state('');
  let notes = $derived(run.notes ?? '');

  function edit() {
    draft = notes;
    editing = true;
  }
  async function save() {
    await api.annotate([run.key], { notes: draft });
    notes = draft;
    run.notes = draft;
    editing = false;
    app.loadRuns();
  }
</script>

<div class="notes">
  {#if editing}
    <div class="panes">
      <textarea
        class="editor mono"
        aria-label="Notes (Markdown)"
        bind:value={draft}
        placeholder="What did this run try, what happened, what next? Markdown works: **bold**, lists, `code`, links, tables."
        onkeydown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault();
            save();
          }
          if (e.key === 'Escape') editing = false;
        }}></textarea>
      <div class="preview"><Markdown text={draft || '*Nothing yet.*'} project={run.project} /></div>
    </div>
    <div class="actions">
      <span class="faint small">Markdown · ctrl/⌘ + S saves · Esc cancels</span>
      <span class="spacer"></span>
      <button class="btn sm" onclick={() => (editing = false)}>Cancel</button>
      <button class="btn btn-primary sm" onclick={save}>Save notes</button>
    </div>
  {:else}
    <div class="actions">
      <span class="faint small">Notes in Markdown, saved in the run's annotations.json</span>
      <span class="spacer"></span>
      <button class="btn sm" onclick={edit}><Icon name="edit" size={14} /> Edit notes</button>
    </div>
    {#if notes.trim()}
      <Markdown text={notes} project={run.project} />
    {:else}
      <p class="faint">No notes yet.</p>
    {/if}
  {/if}
</div>

<style>
  .notes {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .panes {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px;
  }
  .editor {
    width: 100%;
    min-height: 260px;
    resize: vertical;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.55;
    outline: none;
    box-sizing: border-box;
  }
  .editor:focus {
    border-color: var(--accent);
  }
  .preview {
    min-width: 0;
    max-height: 520px;
    overflow: auto;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .spacer {
    flex: 1;
  }
  .sm {
    height: 30px;
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12px;
  }
</style>
