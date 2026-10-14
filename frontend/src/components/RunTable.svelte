<script lang="ts">
  import Icon from './Icon.svelte';
  import Status from './Status.svelte';
  import { api, num, type RunBrief } from '../lib/api';
  import { defaultMetric, fmtAgo, fmtDuration, fmtNum, fmtValue, lowerIsBetter } from '../lib/format';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const ROW = 56;
  let scrollTop = $state(0);
  let viewport = $state(600);
  let editing = $state<string | null>(null);
  let noteDraft = $state('');

  const find = $derived(router.get('find').toLowerCase());
  const showArchived = $derived(router.get('archived') === '1');
  const resultMode = $derived(router.get('res', 'best'));
  const metrics = $derived(app.runs?.metrics ?? []);
  const metric = $derived.by(() => {
    const m = router.get('metric');
    if (m && metrics.includes(m)) return m;
    return defaultMetric(metrics);
  });
  const lower = $derived(lowerIsBetter(metric));
  const multiProject = $derived(new Set((app.runs?.runs ?? []).map((r) => r.project)).size > 1);

  function result(r: RunBrief): number | null {
    const s = r.summary[metric];
    if (!s) return null;
    if (resultMode === 'last') return num(s.last);
    return lower ? s.min : s.max;
  }

  const rows = $derived.by(() => {
    let list = (app.runs?.runs ?? []).filter((r) => showArchived || !r.archived);
    if (find) {
      list = list.filter((r) =>
        [r.name, r.id, r.project, r.notes, ...r.tags].some((s) => s?.toLowerCase().includes(find)),
      );
    }
    const sort = router.get('sort');
    if (sort) {
      const dir = router.get('desc') ? -1 : 1;
      const key = (r: RunBrief): number | string | null =>
        sort === 'result'
          ? result(r)
          : sort === 'name'
            ? r.name
            : sort === 'status'
              ? r.status
              : sort === 'duration'
                ? r.duration
                : r.started;
      list = [...list].sort((a, b) => {
        const ka = key(a);
        const kb = key(b);
        if (ka === null || (typeof ka === 'number' && Number.isNaN(ka))) return 1;
        if (kb === null || (typeof kb === 'number' && Number.isNaN(kb))) return -1;
        return (ka < kb ? -1 : ka > kb ? 1 : 0) * dir;
      });
    }
    return list;
  });

  // Config keys whose values differ between the listed runs: the ones worth showing.
  const varying = $derived.by(() => {
    const values = new Map<string, Set<string>>();
    for (const r of rows.slice(0, 2000))
      for (const [k, v] of Object.entries(r.config)) {
        if (!values.has(k)) values.set(k, new Set());
        values.get(k)!.add(JSON.stringify(v));
      }
    return [...values.entries()]
      .filter(([, s]) => s.size > 1)
      .map(([k]) => k)
      .slice(0, 8);
  });

  const start = $derived(Math.max(0, Math.floor(scrollTop / ROW) - 8));
  const end = $derived(Math.min(rows.length, Math.ceil((scrollTop + viewport) / ROW) + 8));
  const allSelected = $derived(rows.length > 0 && rows.every((r) => app.selected.has(r.key)));

  function toggle(key: string) {
    if (app.selected.has(key)) app.selected.delete(key);
    else app.selected.add(key);
  }
  function toggleAll() {
    if (allSelected) app.selected.clear();
    else rows.forEach((r) => app.selected.add(r.key));
  }
  function sortBy(col: string) {
    const same = router.get('sort') === col;
    router.set({
      sort: col,
      desc: same ? (router.get('desc') ? null : '1') : col === 'started' || (col === 'result' && !lower) ? '1' : null,
    });
  }
  async function annotate(keys: string[], patch: Parameters<typeof api.annotate>[1]) {
    for (const k of keys) {
      const r = app.runByKey(k);
      if (r) Object.assign(r, patch);
    }
    await api.annotate(keys, patch);
  }
  function startNote(r: RunBrief) {
    editing = r.key;
    noteDraft = r.notes;
  }
  async function saveNote(r: RunBrief) {
    if (editing !== r.key) return;
    editing = null;
    if (noteDraft !== r.notes) await annotate([r.key], { notes: noteDraft });
  }
  function short(k: string) {
    const parts = k.split('.');
    return parts[parts.length - 1];
  }
  function plotSelected() {
    router.go('charts', { sel: [...app.selected].join(',') });
  }
  const selected = $derived([...app.selected]);
  const selectedArchived = $derived(selected.length > 0 && selected.every((k) => app.runByKey(k)?.archived));
  const arrow = (col: string) => (router.get('sort') === col ? (router.get('desc') ? ' ↓' : ' ↑') : '');
</script>

<div class="card panel">
  <div class="toolbar">
    <span class="muted">{rows.length} runs{selected.length ? ` · ${selected.length} selected` : ''}</span>
    <input
      class="input find"
      placeholder="Filter by name, tag or note"
      value={router.get('find')}
      oninput={(e) => router.set({ find: (e.currentTarget as HTMLInputElement).value || null })}
    />
    <select
      class="input metric mono"
      value={metric}
      onchange={(e) => router.set({ metric: (e.currentTarget as HTMLSelectElement).value })}
      aria-label="Result metric"
    >
      {#each metrics as m (m)}<option value={m}>{m}</option>{/each}
    </select>
    <div class="seg" role="group" aria-label="Result">
      <button aria-pressed={resultMode === 'best'} onclick={() => router.set({ res: null })}>best</button>
      <button aria-pressed={resultMode === 'last'} onclick={() => router.set({ res: 'last' })}>last</button>
    </div>
    <label class="toggle">
      <button
        class="switch"
        role="switch"
        aria-checked={showArchived}
        aria-label="Show archived"
        onclick={() => router.set({ archived: showArchived ? null : '1' })}
      ></button>
      show archived
    </label>
    <button
      class="btn"
      disabled={selected.length < 1 || selected.length > 2}
      onclick={() => router.set({ cmp: selected.slice(0, 2).join(',') })}
    >
      Compare
    </button>
    <button class="btn btn-primary" disabled={!selected.length} onclick={plotSelected}>Plot selected</button>
  </div>

  {#if selected.length}
    <div class="selbar">
      <span class="count">{selected.length} selected</span>
      <button
        class="btn"
        onclick={() => annotate(selected, { starred: !selected.every((k) => app.runByKey(k)?.starred) })}
      >
        <Icon name="star" size={15} /> Star
      </button>
      <button class="btn" onclick={() => annotate(selected, { archived: !selectedArchived })}>
        <Icon name="archive" size={15} />
        {selectedArchived ? 'Unarchive' : 'Archive'}
      </button>
      <button
        class="btn"
        onclick={() => annotate(selected, { reviewed: !selected.every((k) => app.runByKey(k)?.reviewed) })}
      >
        <Icon name="check" size={15} /> Mark reviewed
      </button>
      <button class="btn" onclick={() => router.go('media', { sel: selected.join(',') })}>Media</button>
      <button class="btn btn-ghost" onclick={() => app.selected.clear()}>Clear selection</button>
    </div>
  {/if}

  <div class="table" role="table" aria-rowcount={rows.length}>
    <div class="row head" role="row">
      <span><input type="checkbox" checked={allSelected} onchange={toggleAll} aria-label="Select all" /></span>
      <span title="Starred">★</span>
      <button class="h" onclick={() => sortBy('status')}>Status{arrow('status')}</button>
      <button class="h" onclick={() => sortBy('name')}>Run{arrow('name')}</button>
      <span class="h">Config</span>
      <button class="h right" onclick={() => sortBy('result')}>Result ({resultMode}){arrow('result')}</button>
      <button class="h" onclick={() => sortBy('started')}>Started{arrow('started')}</button>
      <button class="h right" onclick={() => sortBy('duration')}>Duration{arrow('duration')}</button>
      <span class="h">Reviewed</span>
      <span class="h">Notes</span>
    </div>
    <div
      class="body"
      bind:clientHeight={viewport}
      onscroll={(e) => (scrollTop = (e.currentTarget as HTMLElement).scrollTop)}
    >
      <div style="height:{rows.length * ROW}px; position:relative">
        {#each rows.slice(start, end) as r, i (r.key)}
          {@const value = result(r)}
          <div
            class="row"
            role="row"
            class:sel={app.selected.has(r.key)}
            class:archived={r.archived}
            style="top:{(start + i) * ROW}px"
          >
            <span
              ><input
                type="checkbox"
                checked={app.selected.has(r.key)}
                onchange={() => toggle(r.key)}
                aria-label="Select {r.name}"
              /></span
            >
            <span>
              <button
                class="star"
                class:on={r.starred}
                aria-label={r.starred ? 'Unstar' : 'Star'}
                onclick={() => annotate([r.key], { starred: !r.starred })}
              >
                <Icon name="star" size={16} filled={r.starred} />
              </button>
            </span>
            <span><Status status={r.status} /></span>
            <span class="run">
              <button class="name mono" onclick={() => router.set({ cmp: r.key })} title="Show details">{r.name}</button
              >
              <span class="path mono" title={r.path}>{multiProject ? '' : ''}{r.path}/</span>
            </span>
            <span
              class="config mono"
              title={Object.entries(r.config)
                .map(([k, v]) => `${k}=${fmtValue(v)}`)
                .join('\n')}
            >
              {#each varying.filter((k) => k in r.config) as k (k)}<span>{short(k)}={fmtValue(r.config[k])}</span
                >{/each}
              {#if r.tags.length}<span class="tags"
                  >{#each r.tags.slice(0, 3) as t (t)}<span class="chip">{t}</span>{/each}</span
                >{/if}
            </span>
            <span class="result mono right">
              {#if value !== null}
                <span class="mname">{metric} {lower ? '↓' : '↑'}</span>
                <span class:bad={!Number.isFinite(value) || r.nonfinite.includes(metric)}>
                  {r.nonfinite.includes(metric) && resultMode === 'last' ? 'NaN' : fmtNum(value)}
                </span>
              {:else}<span class="faint">—</span>{/if}
            </span>
            <span class="muted" title={r.started ? new Date(r.started * 1000).toLocaleString() : ''}
              >{fmtAgo(r.started)}</span
            >
            <span class="mono right muted">{fmtDuration(r.duration)}</span>
            <span
              >{#if r.reviewed}<span class="yes">✓ yes</span>{:else}<span class="faint">—</span>{/if}</span
            >
            <span class="notes">
              {#if editing === r.key}
                <!-- svelte-ignore a11y_autofocus -->
                <input
                  class="input note"
                  bind:value={noteDraft}
                  autofocus
                  onblur={() => saveNote(r)}
                  onkeydown={(e) => {
                    if (e.key === 'Enter') saveNote(r);
                    if (e.key === 'Escape') editing = null;
                  }}
                />
              {:else}
                <button class="notebtn" class:faint={!r.notes} onclick={() => startNote(r)} title="Edit note"
                  >{r.notes || (r.status === 'crashed' ? 'add a note…' : '—')}</button
                >
              {/if}
            </span>
          </div>
        {/each}
      </div>
      {#if !rows.length}
        <div class="empty">
          {#if app.loading}Loading…{:else if app.runs?.total === 0}No runs found in this folder yet. Log one with <code
              >nm.init(…)</code
            >
            or run <code>nuboard demo</code>.{:else}No runs match.{/if}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .panel {
    overflow: hidden;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
  }
  .muted {
    color: var(--muted);
  }
  .faint {
    color: var(--faint);
  }
  .find {
    flex: 1 1 200px;
  }
  .metric {
    max-width: 220px;
    font-size: 12.5px;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 13.5px;
  }
  .selbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--accent-soft);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .selbar .count {
    color: var(--accent);
    font-weight: 600;
    margin-right: 8px;
  }
  .table {
    overflow-x: auto;
  }
  .row {
    display: grid;
    grid-template-columns: 30px 26px 96px minmax(220px, 2.2fr) minmax(180px, 2fr) 170px 84px 80px 76px minmax(
        120px,
        1.2fr
      );
    align-items: center;
    gap: 10px;
    padding: 0 14px;
    height: 56px;
    min-width: 1120px;
    border-bottom: 1px solid var(--border);
  }
  .body .row {
    position: absolute;
    left: 0;
    right: 0;
  }
  .row.sel {
    background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
  }
  .row.archived {
    opacity: 0.55;
  }
  .row:not(.head):hover {
    background: var(--panel-2);
  }
  .head {
    height: 40px;
    position: sticky;
    top: 0;
    background: var(--panel);
    z-index: 1;
  }
  .h {
    border: 0;
    background: none;
    padding: 0;
    text-align: left;
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    white-space: nowrap;
  }
  .head > span {
    color: var(--muted);
  }
  .right {
    text-align: right;
    justify-content: flex-end;
  }
  .body {
    max-height: max(360px, calc(100vh - 290px));
    overflow-y: auto;
    position: relative;
    min-width: 1120px;
  }
  .run {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    border: 0;
    background: none;
    padding: 0;
    text-align: left;
    font-weight: 600;
    font-size: 13.5px;
    color: var(--text);
  }
  .name:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .path {
    font-size: 11.5px;
    color: var(--faint);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .config {
    font-size: 12px;
    color: var(--muted);
    display: flex;
    gap: 10px;
    overflow: hidden;
    white-space: nowrap;
    align-items: center;
  }
  .tags {
    display: inline-flex;
    gap: 4px;
  }
  .result {
    display: flex;
    align-items: baseline;
    gap: 8px;
    justify-content: flex-end;
    font-size: 14px;
  }
  .mname {
    color: var(--faint);
    font-size: 11.5px;
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bad {
    color: var(--err);
  }
  .star {
    border: 0;
    background: none;
    color: var(--faint);
    padding: 2px;
    display: grid;
  }
  .star.on {
    color: #e69f00;
  }
  .yes {
    color: var(--accent);
    font-size: 13px;
  }
  .notes {
    min-width: 0;
  }
  .notebtn {
    border: 0;
    background: none;
    padding: 0;
    text-align: left;
    width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    color: var(--text);
  }
  .notebtn.faint {
    color: var(--faint);
  }
  .note {
    height: 30px;
    width: 100%;
  }
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }
  .empty code {
    font-family: var(--mono);
  }
</style>
