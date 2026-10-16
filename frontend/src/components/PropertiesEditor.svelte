<script lang="ts">
  import Icon from './Icon.svelte';
  import { api, type FieldDef, type FieldType, type FieldValue, type RunBrief } from '../lib/api';
  import { ask, confirmAction } from '../lib/dialog.svelte';
  import { FIELD_TYPES, fieldText, parseFieldValue } from '../lib/fields';
  import { app } from '../lib/state.svelte';

  // Typed properties of one run. Definitions are per project (fields.json), values per run.
  let { run }: { run: RunBrief } = $props();

  let defs = $state<FieldDef[]>([]);
  let saving = $state(false);

  async function load() {
    defs = (await api.fields(run.project)).fields;
  }
  $effect(() => {
    void run.project;
    load();
  });
  // Fields set on the run without a definition are shown as text properties
  const all = $derived([
    ...defs,
    ...Object.keys(run.fields ?? {})
      .filter((k) => !defs.some((d) => d.name === k))
      .sort()
      .map((name): FieldDef => ({ name, type: 'text' })),
  ]);
  // eslint-disable-next-line svelte/prefer-writable-derived -- edited key by key through bind:value
  let drafts = $state<Record<string, string>>({});
  $effect(() => {
    drafts = Object.fromEntries(all.map((d) => [d.name, fieldText(run.fields?.[d.name], d.type)]));
  });
  const changed = $derived(all.filter((d) => drafts[d.name] !== fieldText(run.fields?.[d.name], d.type)));

  async function save() {
    if (!changed.length) return;
    saving = true;
    const patch: Record<string, FieldValue | null> = {};
    const grown: FieldDef[] = [];
    for (const d of changed) {
      const v = parseFieldValue(drafts[d.name], d.type);
      patch[d.name] = v;
      // new choices and tags become options of the property
      const vals = Array.isArray(v) ? v : d.type === 'choice' && typeof v === 'string' ? [v] : [];
      const extra = vals.filter((x) => !(d.options ?? []).includes(x));
      if (extra.length && defs.includes(d)) grown.push({ ...d, options: [...(d.options ?? []), ...extra] });
    }
    await api.annotate([run.key], { fields: patch });
    const next = { ...(run.fields ?? {}) };
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) delete next[k];
      else next[k] = v;
    }
    run.fields = next; // the details panel keeps its own copy of the run
    if (grown.length) {
      const next = defs.map((d) => grown.find((g) => g.name === d.name) ?? d);
      defs = (await api.saveFields(run.project, next)).fields;
    }
    saving = false;
    app.loadRuns();
  }

  const TYPE_LABELS: Record<FieldType, string> = {
    text: 'Text',
    number: 'Number',
    choice: 'Choice (one of a list)',
    tags: 'Tags (several of a list)',
    bool: 'Yes / no',
    date: 'Date',
    link: 'Link',
  };

  async function addProperty() {
    const res = await ask(
      'Add a property',
      [
        { label: 'Name', placeholder: 'e.g. dataset, verdict, paper' },
        {
          label: 'Type',
          value: 'text',
          options: FIELD_TYPES.map((t) => ({ value: t, label: TYPE_LABELS[t] })),
          hint: 'Choice and tags take a list of options; numbers can have a unit.',
        },
        { label: 'Options or unit', placeholder: 'choice/tags: a, b, c · number: unit such as ms' },
        { label: 'Description', placeholder: 'optional' },
      ],
      { confirm: 'Add property', message: `Defined for every run of ${run.project}.` },
    );
    if (!res || !res[0].trim()) return;
    const type = (FIELD_TYPES.includes(res[1].trim() as FieldType) ? res[1].trim() : 'text') as FieldType;
    const def: FieldDef = { name: res[0].trim(), type };
    if (type === 'choice' || type === 'tags')
      def.options = res[2]
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    if (type === 'number' && res[2].trim()) def.unit = res[2].trim();
    if (res[3].trim()) def.description = res[3].trim();
    defs = (await api.saveFields(run.project, [...defs.filter((d) => d.name !== def.name), def])).fields;
  }

  async function removeProperty(d: FieldDef) {
    const ok = await confirmAction(
      `Remove the property "${d.name}"?`,
      `Its definition is removed from ${run.project}/fields.json. Values already set on runs are kept as text.`,
      { confirm: 'Remove', danger: true },
    );
    if (!ok) return;
    defs = (
      await api.saveFields(
        run.project,
        defs.filter((x) => x.name !== d.name),
      )
    ).fields;
  }
  const defined = (d: FieldDef) => defs.some((x) => x.name === d.name);
</script>

<div class="props">
  {#if !all.length}
    <p class="faint">
      No properties yet. Properties are typed values you set on runs, such as a dataset, a verdict or a link to a paper.
      They show up as columns in the runs table and can be queried (<code>verdict = "keep"</code>).
    </p>
  {/if}
  {#each all as d (d.name)}
    <div class="row">
      <label class="name" for="prop-{d.name}" title={d.description ?? d.name}>
        <span class="mono n">{d.name}</span>
        <span class="chip type">{d.type}{d.unit ? ` · ${d.unit}` : ''}</span>
      </label>
      <div class="val">
        {#if d.type === 'bool'}
          <select id="prop-{d.name}" class="input" bind:value={drafts[d.name]}>
            <option value="">—</option>
            <option value="true">yes</option>
            <option value="false">no</option>
          </select>
        {:else if d.type === 'date'}
          <input id="prop-{d.name}" class="input" type="date" bind:value={drafts[d.name]} />
        {:else if d.type === 'number'}
          <input id="prop-{d.name}" class="input mono" inputmode="decimal" bind:value={drafts[d.name]} />
        {:else if d.type === 'link'}
          <input id="prop-{d.name}" class="input" type="url" placeholder="https://" bind:value={drafts[d.name]} />
          {#if drafts[d.name]}<a class="open" href={drafts[d.name]} target="_blank" rel="noopener noreferrer">open</a
            >{/if}
        {:else}
          <input
            id="prop-{d.name}"
            class="input"
            list={d.options?.length ? `opts-${d.name}` : undefined}
            placeholder={d.type === 'tags' ? 'comma, separated' : ''}
            bind:value={drafts[d.name]}
          />
          {#if d.options?.length}
            <datalist id="opts-{d.name}">
              {#each d.options as o (o)}<option value={o}></option>{/each}
            </datalist>
          {/if}
        {/if}
      </div>
      {#if defined(d)}
        <button class="btn btn-ghost sm" aria-label="Remove property {d.name}" onclick={() => removeProperty(d)}
          ><Icon name="trash" size={14} /></button
        >
      {:else}
        <span class="faint small undef" title="Set on this run without a definition">untyped</span>
      {/if}
    </div>
  {/each}
  <div class="actions">
    <button class="btn sm" onclick={addProperty}><Icon name="plus" size={14} /> Add property</button>
    <span class="faint small"
      >Definitions: <code>{run.project}/fields.json</code> · values: the run's annotations.json</span
    >
    <span class="spacer"></span>
    <button class="btn btn-primary sm" disabled={!changed.length || saving} onclick={save}
      >{saving
        ? 'Saving…'
        : changed.length
          ? `Save ${changed.length} change${changed.length === 1 ? '' : 's'}`
          : 'Saved'}</button
    >
  </div>
</div>

<style>
  .props {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 820px;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(140px, 240px) minmax(0, 1fr) 40px;
    gap: 12px;
    align-items: center;
  }
  .name {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .n {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .type {
    height: 20px;
    font-size: 11px;
    flex: none;
  }
  .val {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .val .input {
    flex: 1;
    min-width: 0;
  }
  .open {
    color: var(--accent);
    font-size: 13px;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
    flex-wrap: wrap;
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
  code {
    font-family: var(--mono);
    font-size: 12px;
  }
  .undef {
    font-size: 11px;
  }
</style>
