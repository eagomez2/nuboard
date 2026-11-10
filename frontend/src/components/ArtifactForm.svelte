<script lang="ts">
  import { api } from '../lib/api';
  import { fmtBytes } from '../lib/format';

  // A new artifact version that references a path on the machine running the viewer,
  // as `nuboard artifact add --ref` does: checked as it is typed, reviewed, then added.
  // With `source`, the version is made from a file or folder of a run instead (the Files
  // tab), copied or referenced inside the project; the rest of the form is the same.
  let {
    projects,
    project: startProject,
    name: startName = '',
    names,
    types: usedTypes = [],
    source = null,
    onclose,
    onadded,
  }: {
    /** A file or folder of a run to make the version from, by copy or by reference. */
    source?: {
      runKey: string;
      runName: string;
      /** The run's folder name, under `<project>/runs/`. */
      folder: string;
      path: string;
      kind: 'file' | 'folder';
      files: number;
      size: number;
      running: boolean;
    } | null;
    projects: string[];
    project: string;
    name?: string;
    /** Existing artifact names per project, to say whether a new version or a new artifact is made. */
    names: Map<string, string[]>;
    /** Types other artifacts already have, suggested after the built-in ones. */
    types?: string[];
    onclose: () => void;
    onadded: (project: string, name: string, version: number) => void;
  } = $props();

  // any type can be typed, as in Python; these are suggested
  const TYPES = ['dataset', 'model', 'checkpoint', 'report', 'other'];
  const typeChoices = $derived([...TYPES, ...usedTypes.filter((t) => !TYPES.includes(t)).sort()]);
  // suggestions under the Type box, narrowed as it is typed: those starting with the text first
  let typeOpen = $state(false);
  let typeAt = $state(-1);
  let typeBox = $state<HTMLInputElement>();
  // the list is placed over the dialog (fixed), so the dialog's own scrolling does not cut it off
  let typePos = $state('');
  function openTypes() {
    typeOpen = true;
    typeAt = -1;
    const r = typeBox?.getBoundingClientRect();
    if (r) typePos = `top:${r.bottom + 4}px;left:${r.left}px;width:${r.width}px`;
  }
  const typeHits = $derived.by(() => {
    const q = type.trim().toLowerCase();
    if (!q) return typeChoices;
    const hits = typeChoices.filter((t) => t.toLowerCase().includes(q) && t.toLowerCase() !== q);
    return [
      ...hits.filter((t) => t.toLowerCase().startsWith(q)),
      ...hits.filter((t) => !t.toLowerCase().startsWith(q)),
    ];
  });
  // shown capitalized (Dataset); kept as the type is known (dataset), or as typed if it is new
  const typeLabel = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
  function pickType(t: string) {
    type = typeLabel(t);
    typeOpen = false;
  }
  function typeKey(e: KeyboardEvent) {
    const n = typeHits.length;
    if (!typeOpen || !n) {
      if (e.key === 'ArrowDown') openTypes();
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      typeAt = (typeAt + (e.key === 'ArrowDown' ? 1 : n - 1 + (typeAt < 0 ? 1 : 0))) % n;
    } else if ((e.key === 'Enter' || e.key === 'Tab') && typeAt >= 0) {
      e.preventDefault();
      pickType(typeHits[typeAt]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      typeOpen = false;
    }
  }
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
  const typeValue = $derived(typeChoices.find((t) => t.toLowerCase() === type.trim().toLowerCase()) ?? type.trim());
  let description = $state('');
  let checksum = $state(false);
  // From a run: copy (the default) or reference, a name from the file and a type from its suffix
  let stored = $state<'copy' | 'reference'>('copy');
  // svelte-ignore state_referenced_locally (the starting values only)
  if (source) {
    const base = source.path.split('/').filter(Boolean).pop() ?? '';
    if (!name) name = source.kind === 'file' ? base.replace(/\.[^.]+$/, '') : base;
    if (/\.(safetensors|pt|pth|ckpt|bin|npz|h5|keras|onnx)$/i.test(source.path) || /checkpoint/i.test(source.path))
      type = 'Checkpoint';
  }
  // The source as a path check: where a reference points, relative to the project
  const fromRun = $derived<Check | null>(
    source
      ? {
          resolved: `runs/${source.folder}/${source.path}`,
          exists: true,
          kind: source.kind,
          files: source.files,
          size: source.size,
          partial: false,
        }
      : null,
  );
  const hashed = $derived(checksum || (!!source && stored === 'copy'));
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
    if (source || !p) return;
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
        : source
          ? metaError
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

  // set when the files match the latest version: the form offers to add them anyway
  let duplicateOf = $state<number | null>(null);

  type Added = { project: string; name: string; version: number; duplicate_of?: number };

  async function add(allowDuplicate = false) {
    busy = true;
    error = '';
    duplicateOf = null;
    const common = {
      name: cleanName,
      type: typeValue || null,
      description: description.trim(),
      metadata: Object.fromEntries(meta.map((m) => [m.key.trim(), metaValue(m)])),
      checksum,
      allow_duplicate: allowDuplicate,
    };
    const res = await (
      source
        ? api.editArtifacts<Added>('promote', { ...common, run: source.runKey, path: source.path, store: stored })
        : api.editArtifacts<Added>('add', { ...common, project, path: path.trim() })
    ).catch((e) => ({ error: String(e) }) as Added & { error: string });
    busy = false;
    if (res.error) {
      error = res.error;
      duplicateOf = typeof res.duplicate_of === 'number' ? res.duplicate_of : null;
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
    <h2 id="art-form-title">
      {review ? 'Review the new version' : source ? 'New artifact version from this run' : 'New artifact version'}
    </h2>
    {#if !review}
      {#if source}
        <p class="msg">
          The version is made from a {source.kind} of the run <b>{source.runName}</b>, which is recorded as its
          producer. The run's folder is never changed.
        </p>
      {:else}
        <p class="msg">
          The version references files on the machine running the viewer. Nothing is copied, and NuBoard never changes
          them.
        </p>
      {/if}
      <div class="two">
        <div class="field">
          <label class="label" for="art-project">Project</label>
          <select
            id="art-project"
            class="input"
            bind:value={project}
            disabled={!!source}
            title={source ? "A version made from a run belongs to the run's project" : undefined}
          >
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
      {#if source && fromRun}
        <div class="field">
          <label class="label" for="art-path">Source</label>
          <input id="art-path" class="input mono" value={source.path} readonly />
          <span class="hint check"><span class="mono path">{fromRun.resolved}</span> · {summary(fromRun)}</span>
        </div>
        <div class="field">
          <span class="label">Store as</span>
          <div class="choices" role="radiogroup" aria-label="Store as">
            <button
              type="button"
              class="choice"
              role="radio"
              aria-checked={stored === 'copy'}
              onclick={() => (stored = 'copy')}
            >
              <span class="ct"><span class="dot"></span>Copy</span>
              <span class="cd"
                >Copies {fmtBytes(source.size)} into the artifact. It stays the same whatever happens to the run.</span
              >
            </button>
            <button
              type="button"
              class="choice"
              role="radio"
              aria-checked={stored === 'reference'}
              disabled={source.running}
              onclick={() => (stored = 'reference')}
            >
              <span class="ct"><span class="dot"></span>Reference</span>
              <span class="cd"
                >{source.running
                  ? 'Not while the run is running: its files may still change.'
                  : "Copies nothing. The run can't be deleted while this version uses it."}</span
              >
            </button>
          </div>
          {#if stored === 'reference'}
            <span class="hint">Stored relative to the project, so it can still be copied, rsynced or merged.</span>
          {/if}
        </div>
      {:else}
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
      {/if}
      <div class="two">
        <div class="field typefield">
          <label class="label" for="art-type">Type</label>
          <input
            id="art-type"
            class="input"
            bind:value={type}
            placeholder="Any word, such as tokenizer"
            autocomplete="off"
            role="combobox"
            aria-expanded={typeOpen && typeHits.length > 0}
            aria-controls="art-types"
            aria-autocomplete="list"
            bind:this={typeBox}
            onfocus={openTypes}
            oninput={openTypes}
            onblur={() => (typeOpen = false)}
            onkeydown={typeKey}
          />
          {#if typeOpen && typeHits.length}
            <div class="typepop card" style={typePos} id="art-types" role="listbox" aria-label="Suggested types">
              {#each typeHits as t, i (t)}<button
                  type="button"
                  class="typeopt"
                  class:on={i === typeAt}
                  role="option"
                  aria-selected={i === typeAt}
                  tabindex="-1"
                  onpointerdown={(e) => (e.preventDefault(), pickType(t))}
                  onpointermove={() => (typeAt = i)}>{typeLabel(t)}</button
                >{/each}
            </div>
          {/if}
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
          aria-checked={hashed}
          disabled={!!source && stored === 'copy'}
          aria-label="Checksum"
          onclick={() => (checksum = !checksum)}
        ></button>
        <span>Checksum</span>
        <span class="hint"
          >{source && stored === 'copy'
            ? 'Copies are always hashed (SHA-256).'
            : 'Also hash every file (SHA-256). This reads all of the data.'}</span
        >
      </label>
    {:else}
      <dl class="review">
        <dt>Artifact</dt>
        <dd class="mono">
          {project}/{cleanName}
          <span class="faint">({existing.includes(cleanName) ? 'next version' : 'new artifact'})</span>
        </dd>
        {#if source && fromRun}
          <dt>From run</dt>
          <dd>{source.runName} <span class="faint mono">({source.folder})</span></dd>
          <dt>{stored === 'copy' ? 'Copies' : 'References'}</dt>
          <dd class="mono path">{stored === 'copy' ? source.path : fromRun.resolved}</dd>
          <dt>Contains</dt>
          <dd>{summary(fromRun)}</dd>
        {:else}
          <dt>References</dt>
          <dd class="mono path">{check?.resolved}</dd>
          <dt>Contains</dt>
          <dd>{check ? summary(check) : ''}</dd>
        {/if}
        {#if typeValue}<dt>Type</dt>
          <dd>{typeValue}</dd>{/if}
        {#if description.trim()}<dt>Description</dt>
          <dd>{description.trim()}</dd>{/if}
        {#each meta as m (m.key)}<dt class="mono">{m.key}</dt>
          <dd class="mono">{m.value}</dd>{/each}
        <dt>Checksum</dt>
        <dd>{hashed ? 'Yes, every file is hashed' : 'No, files are checked by size'}</dd>
      </dl>
    {/if}
    {#if error}<p class="err" role="alert">
        {error}{#if duplicateOf !== null}. <button
            type="button"
            class="btn btn-ghost sm"
            disabled={busy}
            onclick={() => add(true)}>Add anyway</button
          >{/if}
      </p>{/if}
    <div class="actions">
      {#if review}
        <button type="button" class="btn" disabled={busy} onclick={() => (review = false)}>Back</button>
      {:else}
        <button type="button" class="btn" onclick={onclose}>Cancel</button>
      {/if}
      <span class="faint why">{review ? '' : metaError}</span>
      <button type="submit" class="btn btn-primary" disabled={!!problem || busy}
        >{busy
          ? source && stored === 'copy'
            ? 'Copying…'
            : checksum
              ? 'Hashing files…'
              : 'Adding…'
          : review
            ? 'Add version'
            : 'Review'}</button
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
  .choices {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .choice {
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: left;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .choice[aria-checked='true'] {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .choice:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .ct {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    font-size: 13.5px;
  }
  .dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1.5px solid var(--faint);
    flex: none;
  }
  .choice[aria-checked='true'] .dot {
    border: 4px solid var(--accent);
  }
  .cd {
    font-size: 12.5px;
    color: var(--muted);
    line-height: 1.4;
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
  .typefield {
    position: relative;
  }
  .typepop {
    position: fixed;
    z-index: 20;
    padding: 4px;
    display: flex;
    flex-direction: column;
    max-height: 220px;
    overflow-y: auto;
    box-shadow: var(--lift);
  }
  .typeopt {
    border: 0;
    background: none;
    text-align: left;
    padding: 5px 8px;
    border-radius: 6px;
    font-size: 13px;
    color: var(--text);
    cursor: pointer;
  }
  .typeopt.on {
    background: var(--accent-soft);
  }
</style>
