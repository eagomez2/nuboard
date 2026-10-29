<script lang="ts">
  import { api } from '../lib/api';
  import { fmtBytes } from '../lib/format';

  // A new artifact version that references a path on the machine running the viewer,
  // as `nuboard artifact add --ref` does: checked as it is typed, reviewed, then added.
  let {
    projects,
    project: startProject,
    name: startName = '',
    names,
    onclose,
    onadded,
  }: {
    projects: string[];
    project: string;
    name?: string;
    /** Existing artifact names per project, to say whether a new version or a new artifact is made. */
    names: Map<string, string[]>;
    onclose: () => void;
    onadded: (project: string, name: string, version: number) => void;
  } = $props();

  const TYPES = ['dataset', 'model', 'checkpoint', 'report', 'other'];
  type MetaType = 'text' | 'number' | 'bool' | 'json';
  interface Check {
    resolved?: string;
    exists?: boolean;
    kind?: 'file' | 'folder';
    files?: number;
    size?: number;
    partial?: boolean;
    error?: string;
  }

  let el = $state<HTMLDialogElement>();
  // svelte-ignore state_referenced_locally (the starting values only)
  let project = $state(startProject);
  // svelte-ignore state_referenced_locally
  let name = $state(startName);
  let path = $state('');
  let type = $state('');
  let description = $state('');
  let checksum = $state(false);
  let meta = $state<{ key: string; type: MetaType; value: string }[]>([]);
  let check = $state<Check | null>(null);
  let checking = $state(false);
  let review = $state(false);
  let busy = $state(false);
  let error = $state('');

  const existing = $derived(names.get(project) ?? []);
  const cleanName = $derived(
    name
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, '-')
      .replace(/^[.-]+|[.-]+$/g, '')
      .slice(0, 64),
  );

  $effect(() => {
    if (el && !el.open) el.showModal();
  });

  // Check the path a moment after typing stops
  $effect(() => {
    const p = path.trim();
    check = null;
    if (!p) return;
    checking = true;
    const t = setTimeout(async () => {
      const res = await api.editArtifacts<Check>('check', { path: p }).catch((e) => ({ error: String(e) }) as Check);
      if (path.trim() === p) {
        check = res;
        checking = false;
      }
    }, 300);
    return () => clearTimeout(t);
  });

  function metaValue(m: { type: MetaType; value: string }): unknown {
    if (m.type === 'number') return Number(m.value);
    if (m.type === 'bool') return m.value === 'true';
    if (m.type === 'json') return JSON.parse(m.value);
    return m.value;
  }

  const metaError = $derived.by(() => {
    const keys = new Set<string>();
    for (const m of meta) {
      if (!m.key.trim()) return 'Every metadata row needs a key.';
      if (keys.has(m.key.trim())) return `The key ${m.key.trim()} is used twice.`;
      keys.add(m.key.trim());
      if (m.type === 'number' && (m.value.trim() === '' || !Number.isFinite(Number(m.value))))
        return `${m.key} is not a number.`;
      if (m.type === 'json') {
        try {
          JSON.parse(m.value);
        } catch {
          return `${m.key} is not valid JSON.`;
        }
      }
    }
    return '';
  });

  const problem = $derived(
    !project
      ? 'Choose a project.'
      : !cleanName
        ? 'Enter a name.'
        : !path.trim()
          ? 'Enter a path.'
          : checking || !check
            ? 'Checking the path…'
            : check.error
              ? check.error
              : !check.exists
                ? 'Nothing exists at that path.'
                : metaError,
  );

  // Above this many files the form suggests referencing shards or an index file instead
  const MANY_FILES = 10_000;
  const large = $derived(
    !!check?.exists && check.kind === 'folder' && (!!check.partial || (check.files ?? 0) > MANY_FILES),
  );

  function summary(c: Check): string {
    const what = c.kind === 'file' ? 'File' : 'Folder';
    const files =
      c.kind === 'file'
        ? ''
        : ` · ${c.partial ? 'at least ' : ''}${(c.files ?? 0).toLocaleString('en-US')} ${c.files === 1 ? 'file' : 'files'}`;
    return `${what}${files} · ${c.partial ? 'at least ' : ''}${fmtBytes(c.size ?? 0)}`;
  }

  async function add() {
    busy = true;
    error = '';
    const res = await api
      .editArtifacts<{ project: string; name: string; version: number }>('add', {
        project,
        name: cleanName,
        path: path.trim(),
        type: type || null,
        description: description.trim(),
        metadata: Object.fromEntries(meta.map((m) => [m.key.trim(), metaValue(m)])),
        checksum,
      })
      .catch((e) => ({ error: String(e) }) as { error: string; project: string; name: string; version: number });
    busy = false;
    if (res.error) {
      error = res.error;
      return;
    }
    onadded(res.project, res.name, res.version);
  }
</script>

<dialog
  bind:this={el}
  class="card nb-dialog form"
  aria-labelledby="art-form-title"
  oncancel={(e) => {
    e.preventDefault();
    if (!busy) onclose();
  }}
>
  <form
    onsubmit={(e) => {
      e.preventDefault();
      if (problem) return;
      if (review) add();
      else review = true;
    }}
  >
    <h2 id="art-form-title">{review ? 'Review the new version' : 'New artifact version'}</h2>
    {#if !review}
      <p class="msg">
        The version references files on the machine running the viewer. Nothing is copied, and NuBoard never changes
        them.
      </p>
      <div class="two">
        <div class="field">
          <label class="label" for="art-project">Project</label>
          <select id="art-project" class="input" bind:value={project}>
            {#each projects as p (p)}<option value={p}>{p}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label class="label" for="art-name">Name</label>
          <input
            id="art-name"
            class="input mono"
            bind:value={name}
            list="art-names"
            placeholder="fineweb-edu"
            autocomplete="off"
            spellcheck="false"
          />
          <datalist id="art-names"
            >{#each existing as n (n)}<option value={n}></option>{/each}</datalist
          >
        </div>
      </div>
      {#if cleanName}
        <span class="hint"
          >{existing.includes(cleanName)
            ? `Adds the next version of ${cleanName}.`
            : `Creates the artifact ${cleanName}.`}</span
        >
      {/if}
      <div class="field">
        <label class="label" for="art-path">Path</label>
        <input
          id="art-path"
          class="input mono"
          bind:value={path}
          placeholder="/data/fineweb-edu, ~/models/best.pt, $DATA/corpus or a path relative to the served folder"
          autocomplete="off"
          spellcheck="false"
        />
        <span class="hint check" class:bad={check && (check.error || !check.exists)} aria-live="polite">
          {#if !path.trim()}
            Absolute, ~/…, $VARIABLE/… or relative to the folder the viewer serves.
          {:else if checking || !check}
            Checking…
          {:else if check.error}
            {check.error}
          {:else if !check.exists}
            Nothing exists at <span class="mono">{check.resolved}</span>.
          {:else}
            <span class="mono path">{check.resolved}</span> · {summary(check)}
          {/if}
        </span>
        {#if large}
          <span class="hint warn" role="note">
            That is a lot of files: the manifest lists every one, so adding it takes a while and each
            <span class="mono">use_artifact</span> checks them all. Consider referencing the shards (tar or Parquet files)
            or an index file instead; the artifacts guide has recommendations.
          </span>
        {/if}
      </div>
      <div class="two">
        <div class="field">
          <label class="label" for="art-type">Type</label>
          <select id="art-type" class="input" bind:value={type}>
            <option value="">None</option>
            {#each TYPES as t (t)}<option value={t}>{t[0].toUpperCase() + t.slice(1)}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label class="label" for="art-desc">Description</label>
          <input id="art-desc" class="input" bind:value={description} placeholder="What this version is" />
        </div>
      </div>
      <div class="field">
        <span class="label">Metadata</span>
        {#each meta as m, i (i)}
          <div class="mrow">
            <input
              class="input mono"
              bind:value={m.key}
              placeholder="Key"
              aria-label="Key {i + 1}"
              spellcheck="false"
            />
            <select
              class="input"
              bind:value={m.type}
              onchange={() => (m.value = m.type === 'bool' ? 'true' : m.value)}
              aria-label="Type of {m.key || `key ${i + 1}`}"
            >
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="bool">Yes/no</option>
              <option value="json">JSON</option>
            </select>
            {#if m.type === 'bool'}
              <select class="input" bind:value={m.value} aria-label="Value of {m.key || `key ${i + 1}`}">
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            {:else}
              <input
                class="input mono"
                bind:value={m.value}
                placeholder="Value"
                aria-label="Value of {m.key || `key ${i + 1}`}"
                spellcheck="false"
              />
            {/if}
            <button
              type="button"
              class="btn btn-ghost sm"
              aria-label="Remove {m.key || `key ${i + 1}`}"
              onclick={() => meta.splice(i, 1)}>✕</button
            >
          </div>
        {/each}
        <button
          type="button"
          class="btn btn-ghost sm addmeta"
          onclick={() => meta.push({ key: '', type: 'text', value: '' })}>Add metadata</button
        >
      </div>
      <label class="field row">
        <button
          type="button"
          class="switch"
          role="switch"
          aria-checked={checksum}
          aria-label="Checksum"
          onclick={() => (checksum = !checksum)}
        ></button>
        <span>Checksum</span>
        <span class="hint">Also hash every file (SHA-256). This reads all of the data.</span>
      </label>
    {:else}
      <dl class="review">
        <dt>Artifact</dt>
        <dd class="mono">
          {project}/{cleanName}
          <span class="faint">({existing.includes(cleanName) ? 'next version' : 'new artifact'})</span>
        </dd>
        <dt>References</dt>
        <dd class="mono path">{check?.resolved}</dd>
        <dt>Contains</dt>
        <dd>{check ? summary(check) : ''}</dd>
        {#if type}<dt>Type</dt>
          <dd>{type}</dd>{/if}
        {#if description.trim()}<dt>Description</dt>
          <dd>{description.trim()}</dd>{/if}
        {#each meta as m (m.key)}<dt class="mono">{m.key}</dt>
          <dd class="mono">{m.value}</dd>{/each}
        <dt>Checksum</dt>
        <dd>{checksum ? 'Yes, every file is hashed' : 'No, files are checked by size'}</dd>
      </dl>
    {/if}
    {#if error}<p class="err" role="alert">{error}</p>{/if}
    <div class="actions">
      {#if review}
        <button type="button" class="btn" disabled={busy} onclick={() => (review = false)}>Back</button>
      {:else}
        <button type="button" class="btn" onclick={onclose}>Cancel</button>
      {/if}
      <span class="faint why">{review ? '' : metaError}</span>
      <button type="submit" class="btn btn-primary" disabled={!!problem || busy}
        >{busy ? (checksum ? 'Hashing files…' : 'Adding…') : review ? 'Add version' : 'Review'}</button
      >
    </div>
  </form>
</dialog>

<style>
  .form {
    width: min(620px, calc(100vw - 32px));
    margin: auto;
    padding: 0;
    color: var(--text);
    box-shadow:
      0 1px 2px rgba(16, 24, 40, 0.08),
      0 24px 48px -12px rgba(16, 24, 40, 0.35);
  }
  .form::backdrop {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
    backdrop-filter: blur(2px);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px;
  }
  h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 650;
  }
  .msg {
    margin: -6px 0 0;
    color: var(--muted);
    font-size: 13.5px;
  }
  .two {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 12px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .field.row {
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .hint {
    font-size: 12px;
    color: var(--faint);
  }
  .check {
    overflow-wrap: anywhere;
  }
  .check.bad {
    color: var(--err);
  }
  .warn {
    color: var(--warn, var(--muted));
  }
  .mrow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 100px minmax(0, 1.4fr) auto;
    gap: 6px;
    align-items: center;
  }
  .sm {
    height: 30px;
  }
  .addmeta {
    align-self: flex-start;
  }
  .review {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 6px 16px;
    margin: 0;
    font-size: 13.5px;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    min-width: 0;
  }
  .path {
    overflow-wrap: anywhere;
  }
  .faint {
    color: var(--faint);
  }
  .err {
    margin: 0;
    color: var(--err);
    font-size: 13px;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .why {
    flex: 1;
    font-size: 12.5px;
    text-align: right;
  }
  @media (max-width: 560px) {
    .two {
      grid-template-columns: minmax(0, 1fr);
    }
    .mrow {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
  }
</style>
