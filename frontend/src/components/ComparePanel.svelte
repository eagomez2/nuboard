<script lang="ts">
  import { untrack } from 'svelte';
  import FilesView from './FilesView.svelte';
  import Icon from './Icon.svelte';
  import NotesEditor from './NotesEditor.svelte';
  import PropertiesEditor from './PropertiesEditor.svelte';
  import JobChips from './JobChips.svelte';
  import Status from './Status.svelte';
  import TagEditor from './TagEditor.svelte';
  import Terminal from './Terminal.svelte';
  import { isTerminalText, stripAnsi } from '../lib/ansi';
  import { api, num, type RunDetail, type RunTree } from '../lib/api';
  import { flatten, sideBySide } from '../lib/diff';
  import { fmtDate, fmtDuration, fmtNum, fmtValue } from '../lib/format';
  import { keyFilter, splitMarked } from '../lib/keyfilter';
  import { pinMatches } from '../lib/pattern';
  import { pins } from '../lib/pins.svelte';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  let { keys }: { keys: string[] } = $props();

  // Charts, Sweeps and Media limited to the runs shown here, as the Runs selection bar opens them
  const JUMPS = [
    { page: 'charts', label: 'Charts', icon: 'charts' },
    { page: 'sweeps', label: 'Sweeps', icon: 'sweep' },
    { page: 'media', label: 'Media', icon: 'media' },
  ] as const;
  let details = $state<RunDetail[]>([]);
  let texts = $state<(string | null)[]>([]);
  let loadingFile = $state(false);

  const tab = $derived(router.get('tab', 'settings'));
  const onlyChanges = $derived(router.get('changes') === '1');
  // The settings filter: text, regex mode and matching values too, all kept in the URL
  let findText = $state(router.get('sfind'));
  let findEl = $state<HTMLInputElement>();
  let findFocused = $state(false);
  $effect(() => {
    const t = router.get('sfind');
    if (!findFocused) findText = t;
  });
  const findRegex = $derived(router.get('sre') === '1');
  const findValues = $derived(router.get('svals') === '1');
  const finder = $derived(keyFilter(findText, { regex: findRegex, values: findValues }));
  function setFind(text: string) {
    findText = text;
    router.set({ sfind: text || null });
  }
  function onWindowKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    const typing = !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
    if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && tab === 'settings') {
      e.preventDefault();
      findEl?.focus();
      findEl?.select();
    }
  }
  const multi = $derived(details.length >= 2);
  // File diffs are pairwise: which two of the compared runs (indices into keys).
  const pairIdx = $derived.by(() => {
    const [a, b] = router.list('pair').map(Number);
    const n = details.length;
    const ok = (i: number) => Number.isInteger(i) && i >= 0 && i < n;
    return ok(a) && ok(b) && a !== b ? [a, b] : [0, 1];
  });
  const pair = $derived(multi ? pairIdx.map((i) => details[i]) : []);
  // Logs are diffed by what a terminal shows, so color codes alone are no change
  const plainTexts = $derived(texts.map((t) => (t !== null && isTerminalText(t) ? stripAnsi(t) : t)));
  const pairTexts = $derived(multi && texts.length === details.length ? pairIdx.map((i) => plainTexts[i]) : []);
  let raw = $state(false);
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

  // Keep the open runs' status, duration and summary in step with the live run list. When
  // a status changes (a run finishes or crashes), fetch that run again for its end time and
  // error; nothing else on the panel is reloaded.
  $effect(() => {
    void app.runs?.version;
    const now = untrack(() => details);
    let changed = false;
    const next = now.map((d) => {
      const b = app.runByKey(d.run.key);
      if (!b || (b.status === d.run.status && b.duration === d.run.duration && b.heartbeat === d.run.heartbeat))
        return d;
      changed = true;
      if (b.status !== d.run.status)
        api
          .run(d.run.key)
          .then(
            (f) => (details = details.map((x) => (x.run.key === f.run.key ? { ...x, run: f.run, meta: f.meta } : x))),
          )
          .catch(() => {});
      return { ...d, run: { ...d.run, ...b } };
    });
    if (changed) details = next;
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
  // keyed by strings, so live status updates of `details` do not reload pins or files
  const projectKey = $derived([...new Set(details.map((d) => d.run.project))].join('\n'));
  const projects = $derived(projectKey ? projectKey.split('\n') : []);
  const statusKey = $derived(details.map((d) => d.run.status).join(','));
  $effect(() => {
    for (const p of projects) pins.load(p);
  });
  const pinTabs = $derived(pins.of(projects).filter((p) => trees.some((t) => pinMatches(p, t?.files ?? []).length)));
  const pinOf = (t: string) => (t.startsWith('pin:') ? t.slice(4) : null);
  const pinLabel = (p: string) => p.split('/').pop() || p;

  // Console logs (files/output.log, output.r<rank>.log) come first, as "Console".
  // An artifact from another project shows with it, as in use_artifact("datasets/fineweb-edu:v2")
  const artifactRef = (a: { artifact: string; version: number; project?: string; unlinked?: boolean }) =>
    `${a.project ? a.project + '/' : ''}${a.artifact}:v${a.version}${a.unlinked ? ' (unlinked)' : ''}`;
  const isConsole = (f: string) => /^output(\.r\d+)?\.log$/.test(f);
  const fileTab = $derived(!['settings', 'notes', 'properties', 'filetree'].includes(tab) && !pinOf(tab));
  const showsTerminal = $derived(!multi && fileTab && (isConsole(tab) || (!!texts[0] && isTerminalText(texts[0]))));
  // Other files are in the Files tab, or pinned
  const files = $derived([...new Set(details.flatMap((d) => d.files))].filter(isConsole).sort());
  function fileLabel(f: string): string {
    if (!isConsole(f)) return f;
    const rank = f.match(/\.r(\d+)\.log$/)?.[1];
    return rank ? `Console r${rank}` : 'Console';
  }

  $effect(() => {
    const t = tab;
    const ks = runKeys;
    void statusKey; // a finished run's console is read once more
    if (t === 'settings' || t === 'notes' || t === 'properties' || t === 'filetree' || pinOf(t) || !ks) return;
    loadingFile = true;
    const term = isConsole(t);
    Promise.all(ks.split(',').map((k) => api.file(k, t, term))).then((x) => {
      texts = x;
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
      'git.pushed': gitPushed(m.git),
      'git.untracked': gitUntracked(m.git),
      'git.remote': m.git?.remote ?? null,
      'git.source': gitSource(m.git),
      host: m.env?.host ?? null,
      python: m.env?.python ?? null,
      platform: m.env?.platform ?? null,
      gpus: (m.env?.gpus ?? []).map((g: { name: string }) => g.name).join(', ') || null,
      world_size: m.distributed?.world_size ?? 1,
      fork: m.fork ? `${m.fork.run_id} @ ${m.fork.step}` : null,
      jobs: (d.run.jobs ?? []).map((j) => `${j.job} (${j.status}${j.host ? `, ${j.host}` : ''})`).join(', ') || null,
      inputs: (m.inputs ?? []).map(artifactRef).join(', ') || null,
      outputs: (m.outputs ?? []).map(artifactRef).join(', ') || null,
    };
    for (const [k, v] of Object.entries(flatten(m.config ?? {}))) out[`config.${k}`] = v;
    for (const [k, s] of Object.entries(d.run.summary ?? {})) out[`last.${k}`] = fmtNum(num(s.last), 6);
    return out;
  }

  // Whether the run can be checked out again elsewhere; older runs lack these fields
  type Git = { pushed?: boolean | null; untracked?: number | null; source?: string | null } | null | undefined;
  function gitPushed(g: Git): string | null {
    if (!g || g.pushed === undefined) return null;
    if (g.pushed === null) return 'unknown (no remote-tracking branches)';
    return g.pushed ? 'yes' : 'no: this commit is on no remote branch, so only this machine has it';
  }
  function gitUntracked(g: Git): string | null {
    if (!g || g.untracked === undefined || g.untracked === null) return null;
    return g.untracked ? `${g.untracked} file${g.untracked === 1 ? '' : 's'}, not in git.patch` : 'none';
  }
  const GIT_SOURCES: Record<string, string> = {
    code_dir: 'code_dir passed to init',
    script: "the script's folder",
    cwd: 'the working directory (a best guess)',
  };
  // rows that say the run cannot be fully restored from git
  const GIT_WARN = /^git\.(pushed|untracked)$/;
  const gitSource = (g: Git) => (g?.source ? (GIT_SOURCES[g.source] ?? g.source) : null);

  const allSettingRows = $derived.by(() => {
    const maps = details.map(settings);
    const keysAll = [...new Set(maps.flatMap((m) => Object.keys(m)))];
    return keysAll
      .map((k) => ({
        k,
        vals: maps.map((m) => fmtValue(m[k])),
      }))
      .map((row) => ({ ...row, diff: multi && new Set(row.vals).size > 1 }));
  });
  const settingRows = $derived(allSettingRows.filter((r) => (!onlyChanges || r.diff) && finder.test(r.k, r.vals)));

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

<svelte:window onkeydown={onWindowKey} />

<div class="card cmp" bind:this={panel}>
  <div class="top">
    <div class="title">
      <h2>
        {multi ? `Compare ${details.length} runs` : 'Run'}
        {#if !multi}<span class="mono">{details.map((d) => d.run.name).join(' · ')}</span>{/if}
      </h2>
      {#if !multi}<div class="runtags"><TagEditor runKey={details[0].run.key} {tags} /></div>{/if}
    </div>
    {#if details.length === 1}<Status status={details[0].run.status} /><JobChips jobs={details[0].run.jobs} />{/if}
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
    <span class="jump" role="group" aria-label="Open {keys.length === 1 ? 'this run' : 'these runs'} in">
      {#each JUMPS as j (j.page)}
        <button
          class="tab"
          title="{j.label} with only {keys.length === 1 ? 'this run' : 'these runs'}"
          onclick={() => router.go(j.page, { sel: keys.join(','), cmp: null, pair: null, tab: null })}
          ><Icon name={j.icon} size={13} /> {j.label}</button
        >
      {/each}
    </span>
    {#if tab === 'settings'}
      <div class="find" class:bad={!!finder.error}>
        <Icon name="search" size={14} />
        <input
          class="mono"
          placeholder="Filter keys  (/regex/, !exclude)"
          aria-label="Filter settings"
          aria-invalid={!!finder.error}
          title={finder.error ?? 'Press / to focus, Esc to clear'}
          bind:this={findEl}
          value={findText}
          oninput={(e) => setFind(e.currentTarget.value)}
          onfocus={() => (findFocused = true)}
          onblur={() => (findFocused = false)}
          onkeydown={(e) => {
            if (e.key !== 'Escape') return;
            if (findText) setFind('');
            else findEl?.blur();
          }}
        />
        <button
          class="tog mono"
          aria-pressed={findRegex}
          aria-label="Regular expression"
          title="Every term is a regular expression"
          onclick={() => router.set({ sre: findRegex ? null : '1' })}>.*</button
        >
        <button
          class="tog"
          aria-pressed={findValues}
          aria-label="Match values"
          title="Also match the values, not only the keys"
          onclick={() => router.set({ svals: findValues ? null : '1' })}>Values</button
        >
      </div>
      {#if !finder.empty || onlyChanges}
        <span class="count">{settingRows.length} of {allSettingRows.length} keys</span>
      {/if}
    {/if}
    {#if multi}
      <label class="only">
        <button
          class="switch"
          role="switch"
          aria-checked={onlyChanges}
          aria-label="Only changes"
          onclick={() => router.set({ changes: onlyChanges ? null : '1' })}
        ></button>
        Only changes
      </label>
    {:else if showsTerminal && !loadingFile}
      <label class="only" title="The text as stored, with its color codes">
        <button class="switch" role="switch" aria-checked={raw} aria-label="Raw" onclick={() => (raw = !raw)}></button>
        Raw
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
          <span class="k">Run</span>
          {#each details as d, i (d.run.key)}
            <span class="v run" title={d.run.name}
              ><i style="background:{COLORS[i % COLORS.length]}"></i>{d.run.name}</span
            >
          {/each}
        </div>
      {/if}
      {#each settingRows as row (row.k)}
        <div
          class="srow"
          class:changed={row.diff}
          class:warn={GIT_WARN.test(row.k) && row.vals.some((v) => /^(no|\d+ files?)\b/.test(v))}
          style="grid-template-columns: {cols}; min-width: {rowWidth}"
        >
          <span class="k" title={row.k}
            >{#each splitMarked(row.k, finder.highlight(row.k)) as part, j (j)}{#if part.mark}<mark>{part.text}</mark
                >{:else}{part.text}{/if}{/each}</span
          >
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
        · Diff
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
    {#if showsTerminal && texts[0] != null}
      <Terminal text={texts[0]} {raw} follow />
    {:else}
      <pre class="file mono">{texts[0] ?? '(missing)'}</pre>
    {/if}
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
  .jump {
    display: inline-flex;
    gap: 6px;
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
  .find {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 4px 0 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel-2);
    color: var(--faint);
  }
  .find:focus-within {
    border-color: var(--accent);
  }
  .find.bad {
    border-color: var(--err);
    background: var(--err-bg);
  }
  .find input {
    width: 230px;
    border: 0;
    outline: none;
    background: transparent;
    color: var(--text);
    font-size: 12.5px;
  }
  .tog {
    border: 1px solid transparent;
    background: transparent;
    border-radius: 6px;
    padding: 1px 6px;
    font-size: 12px;
    color: var(--muted);
  }
  .tog[aria-pressed='true'] {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
  }
  .count {
    color: var(--faint);
    font-size: 12.5px;
    white-space: nowrap;
  }
  .find ~ .only {
    margin-left: 6px;
  }
  .k mark {
    background: var(--accent-soft);
    color: var(--accent);
    border-radius: 2px;
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
  .srow.warn .v {
    color: var(--warn);
  }
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
