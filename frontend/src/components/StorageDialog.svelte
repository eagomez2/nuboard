<script lang="ts">
  import { api, type StorageArtifact, type StorageProject, type StorageRun, type StorageStatus } from '../lib/api';
  import { fmtAgo, fmtBytes } from '../lib/format';
  import { router } from '../lib/router.svelte';
  import { storageView as view } from '../lib/storage.svelte';
  import Icon from './Icon.svelte';

  // Disk use of the served folder, like a system storage panel. Nothing is measured until
  // the user presses Measure; a long measurement pauses and asks before going on.
  let el = $state<HTMLDialogElement>();
  let st = $state<StorageStatus | null>(null);
  let error = $state('');
  let openProject = $state<string | null>(null);
  let openArtifact = $state<string | null>(null);

  const PARTS = [
    ['scalars', 'Scalars', 'var(--s1)'],
    ['media', 'Media', 'var(--s2)'],
    ['files', 'Files', 'var(--s4)'],
    ['console', 'Console', 'var(--s3)'],
    ['other', 'Other', 'var(--faint)'],
  ] as const;

  $effect(() => {
    if (!el) return;
    if (view.open && !el.open) {
      el.showModal();
      load();
    } else if (!view.open && el.open) el.close();
  });

  // Poll only while a measurement is under way, to show its progress.
  $effect(() => {
    if (!view.open || st?.state !== 'measuring') return;
    const t = setInterval(load, 400);
    return () => clearInterval(t);
  });

  async function load(action?: 'start' | 'resume' | 'stop') {
    try {
      st = await api.storage(action);
      error = '';
    } catch (e) {
      error = String(e);
    }
  }

  const res = $derived(st?.result ?? null);
  const projects = $derived(res?.projects ?? []);
  const totals = $derived({
    runs: projects.reduce((a, p) => a + p.runs_bytes, 0),
    artifacts: projects.reduce((a, p) => a + p.artifacts_bytes, 0),
    other: projects.reduce((a, p) => a + p.other_bytes, 0),
  });
  const total = $derived(totals.runs + totals.artifacts + totals.other);
  const biggest = $derived(Math.max(1, ...projects.map(projectBytes)));

  function projectBytes(p: StorageProject) {
    return p.runs_bytes + p.artifacts_bytes + p.other_bytes;
  }

  // Artifacts grouped by project and name, largest first.
  const artifactGroups = $derived.by(() => {
    const groups = new Map<string, { project: string; name: string; versions: StorageArtifact[] }>();
    for (const a of res?.artifacts ?? []) {
      const k = `${a.project}/${a.name}`;
      if (!groups.has(k)) groups.set(k, { project: a.project, name: a.name, versions: [] });
      groups.get(k)!.versions.push(a);
    }
    return [...groups.entries()]
      .map(([key, g]) => ({
        key,
        ...g,
        bytes: g.versions.reduce((s, v) => s + v.bytes, 0),
        referenced: g.versions.reduce((s, v) => s + v.referenced, 0),
      }))
      .sort((a, b) => b.bytes - a.bytes || b.referenced - a.referenced);
  });
  const artBytes = $derived(artifactGroups.reduce((s, g) => s + g.bytes, 0));
  const artReferenced = $derived(artifactGroups.reduce((s, g) => s + g.referenced, 0));
  const artBiggest = $derived(Math.max(1, ...artifactGroups.map((g) => g.bytes)));

  const pct = (n: number, of: number) => `${of > 0 ? Math.max(0, (100 * n) / of) : 0}%`;
  const count = (n: number) => n.toLocaleString('en-US');

  function openRun(r: StorageRun) {
    view.open = false;
    router.go('runs', { cmp: r.key });
  }
</script>

<dialog
  bind:this={el}
  class="card storage"
  aria-labelledby="nb-storage-title"
  onclose={() => (view.open = false)}
  onclick={(e) => e.target === el && (view.open = false)}
>
  <div class="shead">
    <h2 id="nb-storage-title">Storage</h2>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected={view.tab === 'runs'} onclick={() => (view.tab = 'runs')}>Runs</button>
      <button role="tab" aria-selected={view.tab === 'artifacts'} onclick={() => (view.tab = 'artifacts')}
        >Artifacts</button
      >
    </div>
    <button class="btn btn-ghost close" aria-label="Close" onclick={() => (view.open = false)}
      ><Icon name="x" size={16} /></button
    >
  </div>

  <div class="measure">
    {#if st?.state === 'measuring'}
      {@const p = st.progress}
      <div class="grow">
        <div class="line">
          Measuring… {count(p.done ?? 0)} of {count(p.total ?? 0)} items, {fmtBytes(p.bytes ?? 0)} so far
        </div>
        <div class="progress"><span style:width={pct(p.done ?? 0, p.total ?? 0)}></span></div>
      </div>
      <button class="btn" onclick={() => load('stop')}>Stop</button>
    {:else if st?.state === 'paused'}
      <span class="faint grow">Measuring is paused.</span>
    {:else if res}
      <span class="faint grow"
        >Measured {fmtAgo(res.measured_at)} in {res.seconds} s{#if res.partial}<span class="chip">Partial</span
          >{/if}</span
      >
      <button class="btn" onclick={() => load('start')}><Icon name="reset" size={14} /> Refresh</button>
    {:else if st}
      <span class="faint grow">Not measured yet. Measuring lists the folder and reads file sizes.</span>
      <button class="btn btn-primary" onclick={() => load('start')}>Measure</button>
    {/if}
  </div>

  {#if st?.state === 'paused'}
    {@const p = st.progress}
    <div class="pause" role="alert">
      <p>
        <strong>This folder is large, so measuring is taking a while.</strong> After {Math.round(p.seconds ?? 0)} s,
        {count(p.done ?? 0)} of about {count(p.total ?? 0)} items are measured ({fmtBytes(p.bytes ?? 0)} so far). Continue
        to measure the rest, or stop and keep this partial result.
      </p>
      <div class="acts">
        <button class="btn" onclick={() => load('stop')}>Stop here</button>
        <button class="btn btn-primary" onclick={() => load('resume')}>Continue measuring</button>
      </div>
    </div>
  {/if}

  {#if error}<p class="err">{error}</p>{/if}

  {#if res && view.tab === 'runs'}
    <div class="total">
      <span class="big">{fmtBytes(total)}</span>
      <span class="faint">in {count(projects.length)} project{projects.length === 1 ? '' : 's'}</span>
    </div>
    <div class="bar" aria-hidden="true">
      <span style:width={pct(totals.runs, total)} style:background="var(--s1)"></span>
      <span style:width={pct(totals.artifacts, total)} style:background="var(--s4)"></span>
      <span style:width={pct(totals.other, total)} style:background="var(--faint)"></span>
    </div>
    <div class="legend">
      <span><i style:background="var(--s1)"></i>Runs {fmtBytes(totals.runs)}</span>
      <span><i style:background="var(--s4)"></i>Artifacts {fmtBytes(totals.artifacts)}</span>
      <span><i style:background="var(--faint)"></i>Other {fmtBytes(totals.other)}</span>
    </div>

    <ul class="list">
      {#each projects as p (p.name)}
        {@const size = projectBytes(p)}
        <li>
          <button
            class="row"
            aria-expanded={openProject === p.name}
            onclick={() => (openProject = openProject === p.name ? null : p.name)}
          >
            <Icon name="chevron" size={14} />
            <span class="mono trunc name" title={p.name}>{p.name}</span>
            <span class="faint keep">{count(p.run_count)} run{p.run_count === 1 ? '' : 's'}</span>
            <span class="mini" aria-hidden="true"
              ><span style:width={pct(size, biggest)}
                ><span style:width={pct(p.runs_bytes, size)} style:background="var(--s1)"></span><span
                  style:width={pct(p.artifacts_bytes, size)}
                  style:background="var(--s4)"
                ></span><span style:width={pct(p.other_bytes, size)} style:background="var(--faint)"></span></span
              ></span
            >
            <span class="size">{fmtBytes(size)}</span>
          </button>
          {#if openProject === p.name}
            <div class="sub">
              <div class="legend sm">
                {#each PARTS as [, label, color] (label)}<span><i style:background={color}></i>{label}</span>{/each}
              </div>
              {#each p.runs as r (r.key)}
                <button class="row run" title="Open {r.name}" onclick={() => openRun(r)}>
                  <span class="mono trunc name">{r.name}</span>
                  <span class="mini" aria-hidden="true"
                    ><span style:width={pct(r.bytes, p.runs[0]?.bytes ?? 1)}
                      >{#each PARTS as [k, , color] (k)}<span style:width={pct(r[k], r.bytes)} style:background={color}
                        ></span>{/each}</span
                    ></span
                  >
                  <span class="size" title={PARTS.map(([k, label]) => `${label}: ${fmtBytes(r[k])}`).join('\n')}
                    >{fmtBytes(r.bytes)}</span
                  >
                </button>
              {:else}
                <p class="faint pad">No runs.</p>
              {/each}
              {#if p.rest.count}
                <p class="faint pad">and {count(p.rest.count)} smaller runs, {fmtBytes(p.rest.bytes)} in all</p>
              {/if}
              {#if p.artifacts_bytes || p.other_bytes}
                <p class="faint pad">
                  Artifacts {fmtBytes(p.artifacts_bytes)}, other files (reports, views, …) {fmtBytes(p.other_bytes)}
                </p>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if res && view.tab === 'artifacts'}
    <div class="total">
      <span class="big">{fmtBytes(artBytes)}</span>
      <span class="faint">stored in this folder</span>
    </div>
    {#if artReferenced}
      <p class="faint note">
        References point to {fmtBytes(artReferenced)} stored elsewhere; it is not counted here.
      </p>
    {/if}
    <ul class="list">
      {#each artifactGroups as g (g.key)}
        <li>
          <button
            class="row"
            aria-expanded={openArtifact === g.key}
            onclick={() => (openArtifact = openArtifact === g.key ? null : g.key)}
          >
            <Icon name="chevron" size={14} />
            <span class="mono trunc name" title={g.key}>{g.name}</span>
            <span class="faint keep trunc"
              >{g.project} · {g.versions.length} version{g.versions.length === 1 ? '' : 's'}</span
            >
            <span class="mini" aria-hidden="true"
              ><span style:width={pct(g.bytes, artBiggest)}
                ><span style:width="100%" style:background="var(--s4)"></span></span
              ></span
            >
            <span class="size">{fmtBytes(g.bytes)}</span>
          </button>
          {#if openArtifact === g.key}
            <div class="sub">
              {#each g.versions as v (v.version)}
                <div class="row run static">
                  <span class="mono name">v{v.version}</span>
                  <span class="faint trunc grow"
                    >{#if v.reference}Reference, points to {fmtBytes(v.referenced)} elsewhere{:else}Copy{/if}{#if v.unlinked}<span
                        class="chip">Unlinked</span
                      >{/if}</span
                  >
                  <span class="size">{fmtBytes(v.bytes)}</span>
                </div>
              {/each}
            </div>
          {/if}
        </li>
      {:else}
        <li class="faint pad">No artifacts.</li>
      {/each}
    </ul>
  {/if}
</dialog>

<style>
  .storage {
    width: min(640px, calc(100vw - 32px));
    max-height: min(760px, calc(100vh - 48px));
    margin: auto;
    padding: 18px 20px 20px;
    color: var(--text);
    overflow: auto;
    box-shadow:
      0 24px 60px -20px rgba(0, 0, 0, 0.35),
      0 2px 6px rgba(0, 0, 0, 0.08);
  }
  .storage::backdrop {
    background: rgba(10, 14, 20, 0.35);
    backdrop-filter: blur(2px);
  }
  .shead {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 12px;
  }
  h2 {
    font-size: 17px;
    margin: 0;
  }
  .tabs {
    display: flex;
    gap: 2px;
    background: var(--panel-2);
    border-radius: 9px;
    padding: 2px;
  }
  .tabs button {
    border: 0;
    background: none;
    color: var(--muted);
    font: inherit;
    font-size: 13px;
    padding: 4px 12px;
    border-radius: 7px;
  }
  .tabs button[aria-selected='true'] {
    background: var(--panel);
    color: var(--text);
    box-shadow: var(--lift);
  }
  .close {
    margin-left: auto;
  }
  .measure {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
    min-height: 32px;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .progress {
    height: 5px;
    border-radius: 3px;
    background: var(--grid);
    margin-top: 6px;
    overflow: hidden;
  }
  .progress span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 0.3s;
  }
  .chip {
    margin-left: 8px;
    font-size: 11px;
    padding: 1px 7px;
    border-radius: 999px;
    background: var(--warn-bg);
    color: var(--warn);
  }
  .pause {
    margin-top: 12px;
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--warn-bg);
    color: var(--text);
    font-size: 13px;
  }
  .pause p {
    margin: 0 0 10px;
    line-height: 1.5;
  }
  .acts {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .err {
    color: var(--err);
    font-size: 13px;
  }
  .total {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-top: 16px;
  }
  .big {
    font-size: 24px;
    font-weight: 650;
  }
  .note {
    font-size: 12.5px;
    margin: 4px 0 0;
  }
  .bar {
    display: flex;
    height: 14px;
    border-radius: 5px;
    overflow: hidden;
    background: var(--grid);
    margin-top: 10px;
    gap: 1px;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    font-size: 12.5px;
    color: var(--muted);
    margin-top: 8px;
  }
  .legend.sm {
    font-size: 11.5px;
    margin: 4px 0 6px 22px;
  }
  .legend i {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 3px;
    margin-right: 6px;
  }
  .list {
    list-style: none;
    margin: 14px 0 0;
    padding: 0;
    border-top: 1px solid var(--border);
  }
  .list > li {
    border-bottom: 1px solid var(--border);
  }
  .row {
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto minmax(60px, 140px) 64px;
    align-items: center;
    gap: 10px;
    width: 100%;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 13px;
    padding: 8px 2px;
    text-align: left;
  }
  .row:hover {
    background: var(--panel-2);
  }
  .row[aria-expanded='true'] :global(svg) {
    transform: rotate(180deg);
  }
  .row.run {
    grid-template-columns: minmax(0, 1fr) minmax(60px, 140px) 64px;
    padding: 5px 2px 5px 26px;
  }
  .row.static {
    grid-template-columns: 40px minmax(0, 1fr) 64px;
  }
  .row.static:hover {
    background: none;
  }
  .name {
    min-width: 0;
  }
  .trunc {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .keep {
    font-size: 12px;
  }
  .size {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .mini {
    display: block;
    height: 8px;
    border-radius: 3px;
    background: var(--grid);
    overflow: hidden;
  }
  .mini > span {
    display: flex;
    height: 100%;
  }
  .mini span span,
  .bar span {
    display: block;
    height: 100%;
  }
  .sub {
    padding-bottom: 8px;
  }
  .pad {
    font-size: 12.5px;
    margin: 6px 0 2px 28px;
  }
  @media (max-width: 520px) {
    .row {
      grid-template-columns: 16px minmax(0, 1fr) 60px 64px;
    }
    .row .keep {
      display: none;
    }
    .row.run {
      grid-template-columns: minmax(0, 1fr) 48px 60px;
      padding-left: 14px;
    }
  }
</style>
