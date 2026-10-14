<script lang="ts">
  import Icon from './Icon.svelte';
  import Status from './Status.svelte';
  import { api, num, type RunDetail } from '../lib/api';
  import { flatten, sideBySide } from '../lib/diff';
  import { fmtDate, fmtDuration, fmtNum, fmtValue } from '../lib/format';
  import { router } from '../lib/router.svelte';

  let { keys }: { keys: string[] } = $props();
  let details = $state<RunDetail[]>([]);
  let texts = $state<(string | null)[]>([]);
  let loadingFile = $state(false);

  const tab = $derived(router.get('tab', 'settings'));
  const onlyChanges = $derived(router.get('changes') === '1');
  const pair = $derived(details.length === 2);

  $effect(() => {
    const ks = keys;
    Promise.all(ks.map((k) => api.run(k))).then((d) => (details = d));
  });

  const files = $derived([...new Set(details.flatMap((d) => d.files))].sort());

  $effect(() => {
    const t = tab;
    const ds = details;
    if (t === 'settings' || !ds.length) return;
    loadingFile = true;
    Promise.all(ds.map((d) => api.file(d.run.key, t))).then((x) => {
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
      tags: d.run.tags.join(', ') || null,
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
      inputs:
        (m.inputs ?? []).map((a: { artifact: string; version: number }) => `${a.artifact}:v${a.version}`).join(', ') ||
        null,
      outputs:
        (m.outputs ?? []).map((a: { artifact: string; version: number }) => `${a.artifact}:v${a.version}`).join(', ') ||
        null,
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
        diff: pair && fmtValue(maps[0][k]) !== fmtValue(maps[1][k]),
      }))
      .filter((r) => !onlyChanges || r.diff);
  });

  const diffRows = $derived(pair && texts.length === 2 ? sideBySide(texts[0] ?? '', texts[1] ?? '') : []);
  const shownDiff = $derived(
    onlyChanges
      ? diffRows.filter(
          (r, i) => r.kind !== 'same' || diffRows.slice(Math.max(0, i - 2), i + 3).some((x) => x.kind !== 'same'),
        )
      : diffRows,
  );
  const changed = $derived(diffRows.filter((r) => r.kind !== 'same').length);
  const errorText = $derived(details.map((d) => d.run.error).find(Boolean));
</script>

<div class="card cmp">
  <div class="top">
    <h2>{pair ? 'Compare' : 'Run'} <span class="mono">{details.map((d) => d.run.name).join(' · ')}</span></h2>
    {#if details.length === 1}<Status status={details[0].run.status} />{/if}
    <button class="btn btn-ghost close" aria-label="Close" onclick={() => router.set({ cmp: null, tab: null })}
      ><Icon name="x" size={16} /></button
    >
  </div>

  {#if errorText}
    <pre class="error mono">{errorText}</pre>
  {/if}

  <div class="tabs">
    <button class="tab mono" aria-pressed={tab === 'settings'} onclick={() => router.set({ tab: null })}
      >all settings</button
    >
    {#each files as f (f)}
      <button class="tab mono" aria-pressed={tab === f} onclick={() => router.set({ tab: f })}>{f}</button>
    {/each}
    {#if pair}
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

  {#if tab === 'settings'}
    <div class="settings mono">
      {#each settingRows as row (row.k)}
        <div
          class="srow"
          class:diff={row.diff}
          style="grid-template-columns: minmax(180px, 1fr) repeat({details.length}, minmax(0, 1.6fr))"
        >
          <span class="k">{row.k}</span>
          {#each row.vals as v, i (i)}<span class="v" title={v}>{v}</span>{/each}
        </div>
      {/each}
    </div>
  {:else if loadingFile}
    <p class="muted">Loading…</p>
  {:else if pair}
    <p class="muted small">
      <span class="mono">files/{tab}</span> · {changed} changed line{changed === 1 ? '' : 's'} · saved by init into each run
      folder
    </p>
    <div class="diff mono">
      <div class="dh"><b>{details[0].run.name}</b><span>{details[0].run.path}/files/{tab}</span></div>
      <div class="dh"><b>{details[1].run.name}</b><span>{details[1].run.path}/files/{tab}</span></div>
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
    <pre class="file mono">{texts[0] ?? '(missing)'}</pre>
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
    align-items: center;
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
  .srow.diff {
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
