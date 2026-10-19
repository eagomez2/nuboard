<script lang="ts">
  import FilesView from './FilesView.svelte';
  import Icon from './Icon.svelte';
  import NotesEditor from './NotesEditor.svelte';
  import PropertiesEditor from './PropertiesEditor.svelte';
  import Status from './Status.svelte';
  import TagEditor from './TagEditor.svelte';
  import { api, num, type RunDetail, type RunTree } from '../lib/api';
  import { flatten, sideBySide } from '../lib/diff';
  import { fmtDate, fmtDuration, fmtNum, fmtValue } from '../lib/format';
  import { pinMatches } from '../lib/pattern';
  import { pins } from '../lib/pins.svelte';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  let { keys }: { keys: string[] } = $props();
  let details = $state<RunDetail[]>([]);
  let texts = $state<(string | null)[]>([]);
  let loadingFile = $state(false);

  const tab = $derived(router.get('tab', 'settings'));
  const onlyChanges = $derived(router.get('changes') === '1');
  const multi = $derived(details.length >= 2);
  // File diffs are pairwise: which two of the compared runs (indices into keys).
  const pairIdx = $derived.by(() => {
    const [a, b] = router.list('pair').map(Number);
    const n = details.length;
    const ok = (i: number) => Number.isInteger(i) && i >= 0 && i < n;
    return ok(a) && ok(b) && a !== b ? [a, b] : [0, 1];
  });
  const pair = $derived(multi ? pairIdx.map((i) => details[i]) : []);
  const pairTexts = $derived(multi && texts.length === details.length ? pairIdx.map((i) => texts[i]) : []);
  const COLORS = [
    'var(--s1)',
    'var(--s2)',
    'var(--s3)',
    'var(--s4)',
    'var(--s5)',
    'var(--s6)',
    'var(--s7)',
    'var(--s8)',
  ];

  let panel = $state<HTMLDivElement | null>(null);
  // Opening a comparison from far down the table should not happen off screen.
  $effect(() => {
    if (keys.join() && panel && panel.getBoundingClientRect().top < 0)
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  $effect(() => {
    const ks = keys;
    Promise.all(ks.map((k) => api.run(k))).then((d) => (details = d));
  });

  // Each run's file listing, kept with the runs it belongs to so a new set of runs never mixes with the last
  let loaded = $state<{ keys: string; trees: (RunTree | null)[] }>({ keys: '', trees: [] });
  const runKeys = $derived(details.map((d) => d.run.key).join(','));
  const trees = $derived(loaded.keys === runKeys ? loaded.trees : []);
  $effect(() => {
    const ks = runKeys;
    if (!ks) return;
    Promise.all(ks.split(',').map((k) => api.tree(k).catch(() => null))).then((t) => (loaded = { keys: ks, trees: t }));
  });

  // Pinned files are tabs, shared by everyone through each project's pins.json; a pin
  // shows only where one of the runs has a file it names
  const projects = $derived([...new Set(details.map((d) => d.run.project))]);
  $effect(() => {
    for (const p of projects) pins.load(p);
  });
  const pinTabs = $derived(pins.of(projects).filter((p) => trees.some((t) => pinMatches(p, t?.files ?? []).length)));
  const pinOf = (t: string) => (t.startsWith('pin:') ? t.slice(4) : null);
  const pinLabel = (p: string) => p.split('/').pop() || p;

  // Console logs (files/output.log, output.r<rank>.log) come first, as "Console".
  // An artifact from another project shows with it, as in use_artifact("datasets/fineweb-edu:v2")
  const artifactRef = (a: { artifact: string; version: number; project?: string }) =>
    `${a.project ? a.project + '/' : ''}${a.artifact}:v${a.version}`;
  const isConsole = (f: string) => /^output(\.r\d+)?\.log$/.test(f);
  // Other files are in the Files tab, or pinned
  const files = $derived([...new Set(details.flatMap((d) => d.files))].filter(isConsole).sort());
  function fileLabel(f: string): string {
    if (!isConsole(f)) return f;
    const rank = f.match(/\.r(\d+)\.log$/)?.[1];
    return rank ? `Console r${rank}` : 'Console';
  }

  const ANSI = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[A-Za-z]`, 'g'); // color and cursor codes

  /** Show a console log as a terminal would: no color codes, and `\r` redraws its line (progress bars). */
  function asTerminal(text: string): string {
    return text
      .replace(ANSI, '')
      .split('\n')
      .map((line) => {
        const parts = line.replace(/\r+$/, '').split('\r');
        return parts[parts.length - 1];
      })
      .join('\n');
  }

  let filePre = $state<HTMLPreElement | null>(null);
  // A console log is read from its end, like a terminal.
  $effect(() => {
    if (filePre && isConsole(tab) && texts.length) filePre.scrollTop = filePre.scrollHeight;
  });

  $effect(() => {
    const t = tab;
    const ds = details;
    if (t === 'settings' || t === 'notes' || t === 'properties' || t === 'filetree' || pinOf(t) || !ds.length) return;
    loadingFile = true;
    const term = isConsole(t);
    Promise.all(ds.map((d) => api.file(d.run.key, t, term))).then((x) => {
      texts = term ? x.map((v) => (v === null ? null : asTerminal(v))) : x;
      loadingFile = false;
    });
  });

  function settings(d: RunDetail): Record<string, unknown> {
    const m = d.meta;
    const out: Record<string, unknown> = {
      status: d.run.status,
      project: d.run.project,
      id: d.run.id,
      started: fmtDate(d.run.started),
      duration: fmtDuration(d.run.duration),
      tags: (app.runByKey(d.run.key)?.tags ?? d.run.tags).join(', ') || null, // edited tags show at once
      group: d.run.group,
      'git.commit': m.git?.commit ?? null,
      'git.branch': m.git?.branch ?? null,
      'git.dirty': m.git?.dirty ?? null,
      host: m.env?.host ?? null,
      python: m.env?.python ?? null,
      platform: m.env?.platform ?? null,
      gpus: (m.env?.gpus ?? []).map((g: { name: string }) => g.name).join(', ') || null,
      world_size: m.distributed?.world_size ?? 1,
      fork: m.fork ? `${m.fork.run_id} @ ${m.fork.step}` : null,
      inputs: (m.inputs ?? []).map(artifactRef).join(', ') || null,
      outputs: (m.outputs ?? []).map(artifactRef).join(', ') || null,
    };
    for (const [k, v] of Object.entries(flatten(m.config ?? {}))) out[`config.${k}`] = v;
    for (const [k, s] of Object.entries(d.run.summary ?? {})) out[`last.${k}`] = fmtNum(num(s.last), 6);
    return out;
  }

  const settingRows = $derived.by(() => {
    const maps = details.map(settings);
    const keysAll = [...new Set(maps.flatMap((m) => Object.keys(m)))];
    return keysAll
      .map((k) => ({
        k,
        vals: maps.map((m) => fmtValue(m[k])),
      }))
      .map((row) => ({ ...row, diff: multi && new Set(row.vals).size > 1 }))
      .filter((r) => !onlyChanges || r.diff);
  });

  const diffRows = $derived(pairTexts.length === 2 ? sideBySide(pairTexts[0] ?? '', pairTexts[1] ?? '') : []);
  const shownDiff = $derived(
    onlyChanges
      ? diffRows.filter(
          (r, i) => r.kind !== 'same' || diffRows.slice(Math.max(0, i - 2), i + 3).some((x) => x.kind !== 'same'),
        )
      : diffRows,
  );
  const changed = $derived(diffRows.filter((r) => r.kind !== 'same').length);
  // Fixed minimum widths keep every row's columns aligned; wide comparisons scroll sideways.
  const cols = $derived(`minmax(180px, 1fr) repeat(${details.length}, minmax(170px, 1.6fr))`);
  const rowWidth = $derived(`${180 + details.length * 182}px`);

  function setPair(side: 0 | 1, e: Event) {
    const next = [...pairIdx];
    next[side] = Number((e.currentTarget as HTMLSelectElement).value);
    if (next[0] === next[1]) next[1 - side] = pairIdx[side];
    router.set({ pair: next.join(',') });
  }

  // The run list holds tags edited since this panel loaded
  const tags = $derived(details.length === 1 ? (app.runByKey(details[0].run.key)?.tags ?? details[0].run.tags) : []);

  const errorText = $derived(details.map((d) => d.run.error).find(Boolean));
</script>

<div class="card cmp" bind:this={panel}>
  <div class="top">
    <div class="title">
      <h2>
        {multi ? `Compare ${details.length} runs` : 'Run'}
        {#if !multi}<span class="mono">{details.map((d) => d.run.name).join(' · ')}</span>{/if}
      </h2>
      {#if !multi}<div class="runtags"><TagEditor runKey={details[0].run.key} {tags} /></div>{/if}
    </div>
    {#if details.length === 1}<Status status={details[0].run.status} />{/if}
    <button
      class="btn btn-ghost close"
      aria-label="Close"
      onclick={() => router.set({ cmp: null, tab: null, pair: null, file: null })}><Icon name="x" size={16} /></button
    >
  </div>

  {#if errorText}
    <pre class="error mono">{errorText}</pre>
  {/if}

  <div class="tabs">
    {#if details.length === 1}
      <button class="tab" aria-pressed={tab === 'notes'} onclick={() => router.set({ tab: 'notes' })}>Notes</button>
      <button class="tab" aria-pressed={tab === 'properties'} onclick={() => router.set({ tab: 'properties' })}
        >Properties</button
      >
    {/if}
    <button class="tab" aria-pressed={tab === 'settings'} onclick={() => router.set({ tab: null })}>All settings</button
    >
    {#each files as f (f)}
      <button
        class="tab"
        aria-pressed={tab === f}
        title={`files/${f}: what the script printed`}
        onclick={() => router.set({ tab: f })}>{fileLabel(f)}</button
      >
    {/each}
    <button
      class="tab"
      aria-pressed={tab === 'filetree'}
      title="Every file in the run folder: browse, preview, diff, download and pin"
      onclick={() => router.set({ tab: 'filetree' })}>Files</button
    >
    {#each pinTabs as p (p)}
      <button
        class="tab mono"
        aria-pressed={tab === `pin:${p}`}
        title="Pinned: {p}"
        onclick={() => router.set({ tab: `pin:${p}` })}><Icon name="pin" size={12} /> {pinLabel(p)}</button
      >
    {/each}
    {#if multi}
      <label class="only">
        <button
          class="switch"
          role="switch"
          aria-checked={onlyChanges}
          aria-label="Only changes"
          onclick={() => router.set({ changes: onlyChanges ? null : '1' })}
        ></button>
        only changes
      </label>
    {/if}
  </div>

  {#if tab === 'notes' && details.length === 1}
    <NotesEditor run={details[0].run} />
  {:else if tab === 'properties' && details.length === 1}
    <PropertiesEditor run={details[0].run} />
  {:else if tab === 'filetree' || pinOf(tab)}
    {#if multi && details.length > 2}
      <p class="muted small">
        Diff
        <select class="input sm mono" aria-label="Left run" value={pairIdx[0]} onchange={(e) => setPair(0, e)}>
          {#each details as d, i (d.run.key)}<option value={i}>{d.run.name}</option>{/each}
        </select>
        against
        <select class="input sm mono" aria-label="Right run" value={pairIdx[1]} onchange={(e) => setPair(1, e)}>
          {#each details as d, i (d.run.key)}<option value={i}>{d.run.name}</option>{/each}
        </select>
      </p>
    {/if}
    <FilesView {details} {trees} {pairIdx} {onlyChanges} colors={COLORS} pin={pinOf(tab)} />
  {:else if tab === 'settings'}
    <div class="settings mono">
      {#if multi}
        <div class="srow head" style="grid-template-columns: {cols}; min-width: {rowWidth}">
          <span class="k">run</span>
          {#each details as d, i (d.run.key)}
            <span class="v run" title={d.run.name}
              ><i style="background:{COLORS[i % COLORS.length]}"></i>{d.run.name}</span
            >
          {/each}
        </div>
      {/if}
      {#each settingRows as row (row.k)}
        <div class="srow" class:changed={row.diff} style="grid-template-columns: {cols}; min-width: {rowWidth}">
          <span class="k">{row.k}</span>
          {#each row.vals as v, i (i)}<span class="v" title={v}>{v}</span>{/each}
        </div>
      {/each}
    </div>
  {:else if loadingFile}
    <p class="muted">Loading…</p>
  {:else if multi}
    <p class="muted small">
      <span class="mono">files/{tab}</span> · {changed} changed line{changed === 1 ? '' : 's'} · saved by init into each run
      folder
      {#if details.length > 2}
        · diff
        <select class="input sm mono" aria-label="Left run" value={pairIdx[0]} onchange={(e) => setPair(0, e)}>
          {#each details as d, i (d.run.key)}<option value={i}>{d.run.name}</option>{/each}
        </select>
        against
        <select class="input sm mono" aria-label="Right run" value={pairIdx[1]} onchange={(e) => setPair(1, e)}>
          {#each details as d, i (d.run.key)}<option value={i}>{d.run.name}</option>{/each}
        </select>
      {/if}
    </p>
    <div class="diff mono">
      <div class="dh"><b>{pair[0].run.name}</b><span>{pair[0].run.path}/files/{tab}</span></div>
      <div class="dh"><b>{pair[1].run.name}</b><span>{pair[1].run.path}/files/{tab}</span></div>
      {#each shownDiff as r, i (i)}
        <div class="line {r.kind === 'same' ? '' : r.kind === 'add' ? 'none' : 'del'}">
          <span class="ln">{r.ln ?? ''}</span><span class="tx"
            >{r.kind !== 'same' && r.left !== null ? '- ' : '  '}{r.left ?? ''}</span
          >
        </div>
        <div class="line {r.kind === 'same' ? '' : r.kind === 'del' ? 'none' : 'add'}">
          <span class="ln">{r.rn ?? ''}</span><span class="tx"
            >{r.kind !== 'same' && r.right !== null ? '+ ' : '  '}{r.right ?? ''}</span
          >
        </div>
      {/each}
    </div>
  {:else}
    <pre class="file mono" class:console={isConsole(tab)} bind:this={filePre}>{texts[0] ?? '(missing)'}</pre>
  {/if}
</div>

<style>
  .cmp {
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .top {
    display: flex;
    align-items: baseline;
    gap: 14px;
  }
  h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 650;
  }
  h2 .mono {
    font-size: 15px;
  }
  .title {
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-width: 0;
  }
  .runtags :global(.pills) {
    flex-wrap: wrap;
  }
  .close {
    margin-left: auto;
    padding: 0 8px;
  }
  .tabs {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
  }
  .tab {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    border: 1px solid var(--border);
    background: var(--panel-2);
    border-radius: 8px;
    padding: 5px 12px;
    font-size: 13px;
    color: var(--muted);
  }
  .tab[aria-pressed='true'] {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
    font-weight: 600;
  }
  .only {
    margin-left: auto;
    display: inline-flex;
    gap: 8px;
    align-items: center;
    color: var(--muted);
    font-size: 13.5px;
  }
  .muted {
    color: var(--muted);
    margin: 0;
  }
  .small {
    font-size: 13px;
  }
  .settings {
    font-size: 12.5px;
    max-height: 520px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
  }
  .srow {
    display: grid;
    gap: 12px;
    padding: 5px 12px;
    border-bottom: 1px solid var(--border);
  }
  .srow:last-child {
    border-bottom: 0;
  }
  .srow.head {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--panel-2);
    font-weight: 600;
  }
  .run {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .run i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex: none;
  }
  /* not `.diff`: that class is the file diff view, whose border and grid it picked up */
  .srow.changed {
    background: var(--diff-del);
  }
  .k {
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .v {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .diff {
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 4px;
    font-size: 12.5px;
    max-height: 560px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
  }
  .dh {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: var(--panel-2);
  }
  .dh span {
    color: var(--faint);
    font-size: 11.5px;
  }
  .line {
    display: grid;
    grid-template-columns: 44px 1fr;
    min-height: 20px;
  }
  .ln {
    color: var(--faint);
    text-align: right;
    padding-right: 10px;
    user-select: none;
  }
  .tx {
    white-space: pre;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-left: 6px;
  }
  .line.del {
    background: var(--diff-del);
  }
  .line.add {
    background: var(--diff-add);
  }
  .line.none {
    background: repeating-linear-gradient(-45deg, transparent 0 4px, var(--border) 4px 5px);
    opacity: 0.5;
  }
  .file {
    font-size: 12.5px;
    max-height: 520px;
    overflow: auto;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    margin: 0;
    white-space: pre;
  }
  .file.console {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .error {
    margin: 0;
    background: var(--err-bg);
    color: var(--err);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 12px;
    max-height: 160px;
    overflow: auto;
    white-space: pre-wrap;
  }
</style>
