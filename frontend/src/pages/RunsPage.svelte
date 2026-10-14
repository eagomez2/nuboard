<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import RunTable from '../components/RunTable.svelte';
  import ComparePanel from '../components/ComparePanel.svelte';
  import { api } from '../lib/api';
  import { ask, confirmAction } from '../lib/dialog.svelte';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const project = $derived(router.get('project'));
  const total = $derived(app.info?.projects.reduce((n, p) => n + p.runs, 0) ?? 0);
  const compare = $derived(router.list('cmp'));

  async function openView(projectName: string, view: string) {
    const res = await fetch(`/api/views/${encodeURIComponent(projectName)}/${encodeURIComponent(view)}`);
    if (!res.ok) return;
    const state = await res.json();
    const page = state.page ?? 'charts';
    history.pushState(null, '', `#/${page}?${new URLSearchParams(state.params ?? {}).toString()}`);
    dispatchEvent(new HashChangeEvent('hashchange'));
  }

  const query = $derived(router.get('q'));
  const collectionQuery = (name: string) => `collections has "${name}"`;

  async function removeCollection(projectName: string, name: string) {
    const ok = await confirmAction(`Delete the collection "${name}"?`, 'The runs themselves are not touched.', {
      confirm: 'Delete',
      danger: true,
    });
    if (!ok) return;
    await api.saveCollection({ name, project: projectName, delete: true });
    if (query === collectionQuery(name)) router.set({ q: null });
    app.loadCollections();
    app.loadRuns();
  }

  async function saveView() {
    const target = project || app.info?.projects[0]?.name;
    if (!target) return;
    const res = await ask(
      'Save the current view',
      [{ label: 'Name', value: 'my-view', hint: `Saved in ${target}/views/` }],
      {
        confirm: 'Save',
      },
    );
    const name = res?.[0].trim();
    if (!name) return;
    await fetch('/api/views', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: target, name, state: { page: router.page, params: router.params } }),
    });
    app.loadInfo();
  }
</script>

<div class="layout">
  <aside class="card side">
    <div class="label">Workspace</div>
    <button class="item root" class:on={!project} onclick={() => router.set({ project: null, sel: null })}>
      <Icon name="folder" size={16} />
      <span class="mono grow">{app.info?.root_display ?? '…'}</span>
      <span class="count">{total}</span>
    </button>
    {#each app.info?.projects ?? [] as p (p.name)}
      <button
        class="item proj"
        class:on={project === p.name}
        onclick={() => router.set({ project: p.name, sel: null })}
      >
        <Icon name="folder" size={16} />
        <span class="grow">{p.name}</span>
        <span class="count">{p.runs}</span>
      </button>
      {#each app.collections.filter((c) => c.project === p.name) as c (c.name)}
        <div class="item coll" class:on={project === p.name && query === collectionQuery(c.name)}>
          <button
            class="collbtn"
            title={c.description || `Collection: ${c.runs.length} runs (collections/${c.name}.json)`}
            onclick={() => router.set({ project: p.name, q: collectionQuery(c.name), sel: null })}
          >
            <Icon name="collection" size={15} />
            <span class="grow">{c.name}</span>
            <span class="count">{c.runs.length}</span>
          </button>
          <button class="del" aria-label="Delete collection {c.name}" onclick={() => removeCollection(p.name, c.name)}
            >×</button
          >
        </div>
      {/each}
      {#each p.views as v (v)}
        <button class="item view" onclick={() => openView(p.name, v)} title="Saved view (views/{v})">
          <Icon name="file" size={15} />
          <span class="grow">views/{v}</span>
        </button>
      {/each}
    {/each}
    <button class="btn save" onclick={saveView}>Save current view…</button>
    <p class="hint">
      Each run is its own folder. Stars, notes, review marks and custom fields are written to the run's <code
        >annotations.json</code
      >, so they travel with the folder. Collections and saved views go to <code>&lt;project&gt;/collections/</code> and
      <code>&lt;project&gt;/views/</code>
      and can be committed to git.
    </p>
  </aside>

  <section class="main">
    {#if compare.length}
      <ComparePanel keys={compare} />
    {/if}
    <RunTable />
  </section>
</div>

<style>
  .layout {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .side {
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    position: sticky;
    top: 16px;
  }
  .side .label {
    padding: 0 8px 8px;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 9px;
    border: 0;
    background: none;
    text-align: left;
    padding: 7px 8px;
    border-radius: 8px;
    color: var(--text);
    font-size: 14px;
  }
  .item:hover {
    background: var(--panel-2);
  }
  .item.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 550;
  }
  .proj {
    padding-left: 22px;
  }
  .coll {
    padding: 0 0 0 40px;
    font-size: 13px;
  }
  .collbtn {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 9px;
    border: 0;
    background: none;
    color: inherit;
    padding: 6px 0;
    text-align: left;
  }
  .del {
    border: 0;
    background: none;
    color: var(--faint);
    padding: 0 8px;
    visibility: hidden;
  }
  .coll:hover .del {
    visibility: visible;
  }
  .view {
    padding-left: 40px;
    color: var(--muted);
    font-size: 13px;
  }
  .grow {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .count {
    color: var(--faint);
    font: 12px var(--mono);
  }
  .save {
    margin: 12px 8px 0;
    justify-content: center;
  }
  .hint {
    color: var(--faint);
    font-size: 12.5px;
    margin: 14px 8px 0;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .hint code {
    font-family: var(--mono);
    font-size: 11.5px;
  }
  .main {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
  }
  @media (max-width: 1100px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }
    .side {
      position: static;
    }
  }
</style>
