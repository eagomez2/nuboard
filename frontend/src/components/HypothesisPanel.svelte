<script lang="ts">
  // The side panel of the Hypotheses page: what is selected (a hypothesis, a run, or several runs
  // picked with Shift), or how to start when nothing is. Every change goes through `onsave` with an
  // edited copy, so the page stays the only writer. Runs and reports that are gone show greyed.
  import { untrack } from 'svelte';
  import type { SvelteSet } from 'svelte/reactivity';
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';
  import VerdictIcon from './VerdictIcon.svelte';
  import type { RunBrief } from '../lib/api';
  import { confirmAction } from '../lib/dialog.svelte';
  import { Fold } from '../lib/fold.svelte';
  import { fmtNum, fmtValue } from '../lib/format';
  import { directionOf } from '../lib/directions.svelte';
  import {
    CARD_CHOICES,
    cardChoice,
    cardFor,
    colorVar,
    newHypothesis,
    outcomeOf,
    ownerOf,
    verdictOf,
    type BoardData,
    type CardChoice,
    type HRun,
    type Hypothesis,
  } from '../lib/hypotheses';
  import { router } from '../lib/router.svelte';

  let {
    data,
    project,
    projectRuns,
    selHyp,
    selRun,
    picked,
    ro,
    onsave,
    ondelete,
    onselect,
    oncategories,
    askNew = 0,
  }: {
    data: BoardData;
    project: string;
    projectRuns: RunBrief[];
    selHyp: string;
    selRun: string;
    picked: SvelteSet<string>;
    ro: boolean;
    onsave: (h: Hypothesis) => void;
    ondelete: (h: Hypothesis) => void;
    onselect: (hyp?: string | null, run?: string | null) => void;
    oncategories: () => void;
    /** Bumped to show the New hypothesis form and focus it. */
    askNew?: number;
  } = $props();

  const side = new Fold('hypothesesPanelFolded');

  const owner = $derived(ownerOf(data.hypotheses));
  const hyp = $derived(
    data.hypotheses.find((h) => h.id === selHyp) ?? (selRun ? owner.get(selRun) : undefined) ?? null,
  );
  const hrun = $derived(selRun && hyp ? (hyp.runs.find((r) => r.id === selRun) ?? null) : null);
  const run = $derived(hrun ? data.runs[hrun.id] : undefined);
  /** Project runs that no hypothesis lists yet, newest first. */
  const unfiled = $derived(
    projectRuns
      .filter((r) => !owner.has(r.id))
      .sort((a, b) => (b.started ?? b.created ?? 0) - (a.started ?? a.created ?? 0)),
  );
  const nameOf = (id: string) => data.runs[id]?.name ?? projectRuns.find((r) => r.id === id)?.name ?? id;
  const keyOf = (id: string) => data.runs[id]?.key ?? projectRuns.find((r) => r.id === id)?.key;

  /** Save an edited copy of a hypothesis. */
  function edit(h: Hypothesis, change: (c: Hypothesis) => void) {
    if (ro) return;
    const c = structuredClone($state.snapshot(h)) as Hypothesis;
    change(c);
    onsave(c);
  }
  const editRun = (h: Hypothesis, id: string, change: (r: HRun) => void) =>
    edit(h, (c) => {
      const r = c.runs.find((x) => x.id === id);
      if (r) change(r);
    });

  function openCharts(ids: string[]) {
    const keys = ids.map(keyOf).filter((k): k is string => !!k);
    if (keys.length) router.go('charts', { sel: keys.join(','), h: null, hrun: null, hview: null });
  }
  function openCompare(ids: string[]) {
    const keys = ids.map(keyOf).filter((k): k is string => !!k);
    if (keys.length) router.go('runs', { cmp: keys.join(','), h: null, hrun: null, hview: null });
  }

  // -- forms ------------------------------------------------------------------------------------
  let newTitle = $state('');
  let newInput = $state<HTMLInputElement>();
  // "New hypothesis" on the page bumps `askNew`: unfold, then put the cursor in the form
  $effect(() => {
    if (!askNew) return;
    untrack(() => side.folded && side.toggle());
    requestAnimationFrame(() => newInput?.focus());
  });
  let newRun = $state('');
  let followTitle = $state('');
  let followReason = $state('');
  let editingNote = $state(false);
  let noteText = $state('');

  function create(e: SubmitEvent) {
    e.preventDefault();
    const title = newTitle.trim();
    if (!title) return;
    onsave(
      newHypothesis({ title, runs: newRun ? [{ id: newRun, outcome: 'open', conclusion: '', star: false }] : [] }),
    );
    newTitle = newRun = '';
  }
  function followUp(e: SubmitEvent) {
    e.preventDefault();
    const title = followTitle.trim();
    if (!title || !hrun) return;
    onsave(newHypothesis({ title, parent_run: hrun.id, reason: followReason.trim() }));
    followTitle = followReason = '';
  }
  async function remove(h: Hypothesis) {
    const n = h.runs.length;
    const ok = await confirmAction(
      'Delete hypothesis',
      `Delete “${h.title}”? Its ${n} run${n === 1 ? '' : 's'} stay on disk and go back to the unfiled list.`,
      { confirm: 'Delete', danger: true },
    );
    if (ok) ondelete(h);
  }

  // A run's config next to its parent run's, keeping the keys that differ
  const parentRun = $derived(hyp?.parent_run ? data.runs[hyp.parent_run] : undefined);
  const diff = $derived.by(() => {
    if (!run || !parentRun || parentRun.id === run.id) return [];
    const keys = [...new Set([...Object.keys(run.config ?? {}), ...Object.keys(parentRun.config ?? {})])].sort();
    return keys
      .map((k) => ({ k, a: fmtValue(parentRun.config?.[k]), b: fmtValue(run.config?.[k]) }))
      .filter((d) => d.a !== d.b)
      .slice(0, 30);
  });

  const metrics = $derived([...new Set(projectRuns.flatMap((r) => Object.keys(r.summary ?? {})))].sort());
  function setOwnCard(h: Hypothesis, metric: string, choice?: CardChoice) {
    edit(h, (c) => {
      const keepLast = !choice && c.card?.stat === 'last';
      c.card = metric
        ? cardFor(metric, choice ?? (keepLast ? 'last' : null), directionOf([project], metric).direction ?? 'max')
        : null;
    });
  }
</script>

{#if side.folded}
  <aside class="card side bar">
    <button class="btn btn-ghost icon" aria-label="Show the panel" title="Show the panel" onclick={side.toggle}
      ><Icon name="sidebar" size={16} /></button
    >
  </aside>
{:else}
  <aside class="card side">
    <div class="head">
      <span class="label">
        {#if picked.size}{picked.size} runs picked{:else if hrun}Run{:else if hyp}Hypothesis{:else}Getting started{/if}
      </span>
      <button class="btn btn-ghost icon" aria-label="Hide the panel" title="Hide the panel" onclick={side.toggle}
        ><Icon name="sidebar" size={16} /></button
      >
    </div>

    {#if picked.size}
      <!-- several runs, picked with Shift-click -->
      <ul class="plain">
        {#each [...picked] as id (id)}
          <li class="mono">{nameOf(id)} <span class="faint">· {owner.get(id)?.title ?? ''}</span></li>
        {/each}
      </ul>
      <div class="row">
        <button class="btn btn-primary sm" onclick={() => openCharts([...picked])}
          ><Icon name="charts" size={14} /> Charts</button
        >
        <button class="btn sm" onclick={() => openCompare([...picked])}
          >{#if picked.size === 1}<Icon name="info" size={14} /> Details{:else}<Icon name="compare" size={14} />
            Compare{/if}</button
        >
        <button class="btn btn-ghost sm" onclick={() => picked.clear()}>Clear</button>
      </div>
    {:else if hyp && hrun}
      <!-- one run -->
      {@const o = outcomeOf(data.board, hrun.outcome)}
      <div class="title-row">
        <h3 class="mono grow" class:missing={!run}>{nameOf(hrun.id)}</h3>
        <button
          class="btn btn-ghost icon"
          class:on={hrun.star}
          disabled={ro}
          aria-pressed={hrun.star}
          title={hrun.star ? 'Unstar' : 'Star: keep on the starred path and in folded cards'}
          aria-label="Star"
          onclick={() => editRun(hyp, hrun.id, (r) => (r.star = !r.star))}><Icon name="star" size={15} /></button
        >
      </div>
      <button class="back" onclick={() => onselect(hyp.id, null)}>← {hyp.title}</button>

      {#if !run}
        <p class="warn-box">
          This run was not found. It may have been moved, renamed on disk or deleted. The board keeps the link so its
          conclusion is not lost.
        </p>
        {#if !ro}
          <button class="btn sm" onclick={() => edit(hyp, (c) => (c.runs = c.runs.filter((r) => r.id !== hrun.id)))}
            ><Icon name="trash" size={14} /> Remove from hypothesis</button
          >
        {/if}
      {/if}

      <section>
        <span class="label">Outcome</span>
        <div class="chips">
          {#each data.board.outcomes as c (c.id)}
            <button
              class="cat"
              aria-pressed={o?.id === c.id}
              disabled={ro}
              style="--vc:{colorVar(c.color)}"
              onclick={() => editRun(hyp, hrun.id, (r) => (r.outcome = c.id))}><i></i>{c.label}</button
            >
          {/each}
          {#if !ro}
            <button
              class="btn btn-ghost icon sm"
              title="Edit categories"
              aria-label="Edit categories"
              onclick={oncategories}><Icon name="edit" size={13} /></button
            >
          {/if}
        </div>
      </section>

      <section>
        <span class="label">Conclusion</span>
        {#key hrun.id}
          <textarea
            class="input"
            rows="3"
            placeholder="What did this run show?"
            value={hrun.conclusion}
            disabled={ro}
            onchange={(e) => {
              const v = e.currentTarget.value;
              editRun(hyp, hrun.id, (r) => (r.conclusion = v));
            }}></textarea>
        {/key}
      </section>

      {#if run}
        <div class="row">
          <button class="btn sm" onclick={() => openCharts([hrun.id])}><Icon name="charts" size={14} /> Charts</button>
          <button class="btn sm" onclick={() => router.go('media', { sel: run.key, h: null, hrun: null, hview: null })}
            ><Icon name="media" size={14} /> Media</button
          >
          <button class="btn sm" onclick={() => openCompare([hrun.id])}><Icon name="info" size={14} /> Details</button>
        </div>

        {#if Object.keys(run.summary).length}
          <section>
            <span class="label">Metrics</span>
            <table class="kv">
              <tbody>
                {#each Object.entries(run.summary).slice(0, 12) as [m, s] (m)}
                  <tr
                    ><td class="mono">{m}</td><td class="mono num"
                      >{fmtNum(typeof s.last === 'number' ? s.last : null)}</td
                    ></tr
                  >
                {/each}
              </tbody>
            </table>
          </section>
        {/if}

        {#if diff.length}
          <section>
            <span class="label">Changed from {parentRun?.name}</span>
            <table class="kv">
              <tbody>
                {#each diff as d (d.k)}
                  <tr><td class="mono">{d.k}</td><td class="mono faint">{d.a}</td><td class="mono">{d.b}</td></tr>
                {/each}
              </tbody>
            </table>
          </section>
        {/if}
      {/if}

      {#if !ro}
        <form class="box" onsubmit={followUp}>
          <span class="label">Follow up</span>
          <p class="help">Start the next hypothesis from this run. An arrow will lead from it.</p>
          <input class="input" bind:value={followTitle} placeholder="Next hypothesis" aria-label="Next hypothesis" />
          <input
            class="input"
            bind:value={followReason}
            placeholder="Why? (optional, shown on the arrow)"
            aria-label="Why"
          />
          <button class="btn btn-primary sm" type="submit" disabled={!followTitle.trim()}>Create</button>
        </form>
      {/if}
    {:else if hyp}
      <!-- one hypothesis -->
      {@const v = verdictOf(data.board, hyp.verdict)}
      {@const others = data.hypotheses.flatMap((h) => (h.id === hyp.id ? [] : h.runs.map((r) => ({ id: r.id, h }))))}
      <div class="title-row">
        {#key hyp.id}
          <input
            class="input title"
            value={hyp.title}
            disabled={ro}
            aria-label="Title"
            onchange={(e) => {
              const t = e.currentTarget.value.trim();
              if (t) edit(hyp, (c) => (c.title = t));
            }}
          />
        {/key}
        <button
          class="btn btn-ghost icon"
          class:on={hyp.star}
          disabled={ro}
          aria-pressed={hyp.star}
          title={hyp.star ? 'Unstar' : 'Star'}
          aria-label="Star"
          onclick={() => edit(hyp, (c) => (c.star = !c.star))}><Icon name="star" size={15} /></button
        >
        {#if !ro}
          <button class="btn btn-ghost icon" title="Delete" aria-label="Delete hypothesis" onclick={() => remove(hyp)}
            ><Icon name="trash" size={15} /></button
          >
        {/if}
      </div>

      <section>
        <span class="label">Verdict</span>
        <div class="chips">
          {#each data.board.verdicts as c (c.id)}
            <button
              class="cat"
              aria-pressed={v.id === c.id}
              disabled={ro}
              style="--vc:{colorVar(c.color)}"
              onclick={() => edit(hyp, (h) => (h.verdict = c.id))}><VerdictIcon icon={c.icon} />{c.label}</button
            >
          {/each}
          {#if !ro}
            <button
              class="btn btn-ghost icon sm"
              title="Edit categories"
              aria-label="Edit categories"
              onclick={oncategories}><Icon name="edit" size={13} /></button
            >
          {/if}
        </div>
      </section>

      <section>
        <span class="label">Comes from</span>
        <select
          class="input"
          value={hyp.parent_run ?? ''}
          disabled={ro}
          aria-label="Parent run"
          onchange={(e) => {
            const p = e.currentTarget.value || null;
            edit(hyp, (c) => (c.parent_run = p));
          }}
        >
          <option value="">Nothing (a starting point)</option>
          {#each others as o (o.id)}
            <option value={o.id}>{nameOf(o.id)} · {o.h.title}</option>
          {/each}
          {#if hyp.parent_run && !others.some((o) => o.id === hyp.parent_run)}
            <option value={hyp.parent_run}>{hyp.parent_run} (not found)</option>
          {/if}
        </select>
        {#if hyp.parent_run}
          {#key hyp.id}
            <input
              class="input"
              value={hyp.reason}
              disabled={ro}
              placeholder="Why? (text on the arrow)"
              aria-label="Why"
              onchange={(e) => {
                const r = e.currentTarget.value.trim();
                edit(hyp, (c) => (c.reason = r));
              }}
            />
          {/key}
          <label class="tg"
            ><button
              class="switch"
              role="switch"
              aria-checked={hyp.show_reason}
              aria-label="Show on the arrow"
              disabled={ro}
              onclick={() => edit(hyp, (c) => (c.show_reason = !c.show_reason))}
            ></button>Show on the arrow</label
          >
        {/if}
      </section>

      <section>
        <div class="sec-head">
          <span class="label">Note</span>
          {#if !ro && !editingNote}
            <button
              class="btn btn-ghost icon sm"
              title="Edit note"
              aria-label="Edit note"
              onclick={() => {
                noteText = hyp.note;
                editingNote = true;
              }}><Icon name="edit" size={13} /></button
            >
          {/if}
        </div>
        {#if editingNote}
          <textarea class="input note" rows="8" bind:value={noteText} placeholder="Markdown"></textarea>
          <div class="row">
            <button
              class="btn btn-primary sm"
              onclick={() => {
                editingNote = false;
                const t = noteText;
                edit(hyp, (c) => (c.note = t));
              }}>Save</button
            >
            <button class="btn sm" onclick={() => (editingNote = false)}>Cancel</button>
          </div>
        {:else if hyp.note}
          <div class="md"><Markdown text={hyp.note} {project} /></div>
        {:else}
          <p class="help">The idea, the plan, what you expect. Markdown.</p>
        {/if}
      </section>

      <section>
        <span class="label">Reports</span>
        {#each hyp.reports as name (name)}
          {@const found = data.reports.includes(name)}
          <div class="line" class:missing={!found}>
            <Icon name="report" size={14} />
            {#if found}
              <button
                class="link grow"
                onclick={() => router.go('reports', { rproject: project, report: name, h: null, hrun: null })}
                >{name}</button
              >
            {:else}
              <span class="grow" title="This report was not found">{name} <span class="nf">not found</span></span>
            {/if}
            {#if !ro}
              <button
                class="btn btn-ghost icon sm"
                title="Unlink"
                aria-label="Unlink {name}"
                onclick={() => edit(hyp, (c) => (c.reports = c.reports.filter((r) => r !== name)))}
                ><Icon name="x" size={13} /></button
              >
            {/if}
          </div>
        {/each}
        {#if !ro && data.reports.some((r) => !hyp.reports.includes(r))}
          <select
            class="input"
            value=""
            aria-label="Link a report"
            onchange={(e) => {
              const name = e.currentTarget.value;
              if (name) edit(hyp, (c) => c.reports.push(name));
            }}
          >
            <option value="">Link a report…</option>
            {#each data.reports.filter((r) => !hyp.reports.includes(r)) as r (r)}<option value={r}>{r}</option>{/each}
          </select>
        {:else if !hyp.reports.length}
          <p class="help">No reports in this project yet.</p>
        {/if}
      </section>

      <section>
        <span class="label">Runs</span>
        {#each hyp.runs as r (r.id)}
          {@const o = outcomeOf(data.board, r.outcome)}
          <div class="line" class:missing={!data.runs[r.id]}>
            <span class="dot" style="background:{data.runs[r.id] ? colorVar(o?.color ?? 'gray') : 'transparent'}"
            ></span>
            <button class="link mono grow" onclick={() => onselect(hyp.id, r.id)}>{nameOf(r.id)}</button>
            {#if !data.runs[r.id]}<span class="nf">not found</span>{/if}
            {#if !ro}
              <button
                class="btn btn-ghost icon sm"
                title="Remove from hypothesis"
                aria-label="Remove {nameOf(r.id)}"
                onclick={() => edit(hyp, (c) => (c.runs = c.runs.filter((x) => x.id !== r.id)))}
                ><Icon name="x" size={13} /></button
              >
            {/if}
          </div>
        {/each}
        {#if !ro}
          {#if unfiled.length}
            <select
              class="input"
              value=""
              aria-label="Add a run"
              onchange={(e) => {
                const id = e.currentTarget.value;
                if (id) edit(hyp, (c) => c.runs.push({ id, outcome: 'open', conclusion: '', star: false }));
              }}
            >
              <option value="">Add a run…</option>
              {#each unfiled as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
            </select>
          {:else}
            <p class="help">Every run of the project is on the board.</p>
          {/if}
        {/if}
        {#if hyp.runs.some((r) => data.runs[r.id])}
          <div class="row">
            <button class="btn sm" onclick={() => openCharts(hyp.runs.map((r) => r.id))}
              ><Icon name="charts" size={14} /> Charts</button
            >
            <button class="btn sm" onclick={() => openCompare(hyp.runs.map((r) => r.id))}
              >{#if hyp.runs.filter((r) => data.runs[r.id]).length === 1}<Icon name="info" size={14} />
                Details{:else}<Icon name="compare" size={14} /> Compare{/if}</button
            >
          </div>
        {/if}
      </section>

      <section>
        <span class="label">Also informed by</span>
        {#each hyp.also as a, i (a.run + i)}
          <div class="line" class:missing={!data.runs[a.run]}>
            <span class="grow"
              ><span class="mono">{nameOf(a.run)}</span>{#if a.reason}<span class="faint">
                  · {a.reason}</span
                >{/if}</span
            >
            {#if !data.runs[a.run]}<span class="nf">not found</span>{/if}
            {#if !ro}
              <button
                class="btn btn-ghost icon sm"
                title="Remove link"
                aria-label="Remove link"
                onclick={() => edit(hyp, (c) => c.also.splice(i, 1))}><Icon name="x" size={13} /></button
              >
            {/if}
          </div>
        {/each}
        {#if !ro}
          <select
            class="input"
            value=""
            aria-label="Add a dashed link"
            onchange={(e) => {
              const id = e.currentTarget.value;
              if (id) edit(hyp, (c) => c.also.push({ run: id, reason: '' }));
            }}
          >
            <option value="">Add a dashed link from a run…</option>
            {#each others.filter((o) => o.id !== hyp.parent_run && !hyp.also.some((a) => a.run === o.id)) as o (o.id)}
              <option value={o.id}>{nameOf(o.id)} · {o.h.title}</option>
            {/each}
          </select>
        {/if}
      </section>

      {#if !ro}
        <section>
          <span class="label">Number on this card</span>
          <div class="row">
            <select
              class="input"
              value={hyp.card?.metric ?? ''}
              aria-label="Metric"
              onchange={(e) => setOwnCard(hyp, e.currentTarget.value)}
            >
              <option value="">Board setting{data.board.card ? ` (${data.board.card.metric})` : ''}</option>
              {#each metrics as m (m)}<option value={m}>{m}</option>{/each}
              {#if hyp.card && !metrics.includes(hyp.card.metric)}<option value={hyp.card.metric}
                  >{hyp.card.metric}</option
                >{/if}
            </select>
            {#if hyp.card}
              <div class="seg stat" role="group" aria-label="Summary">
                {#each CARD_CHOICES as c (c.value)}
                  <button
                    aria-pressed={cardChoice(hyp.card) === c.value}
                    onclick={() => setOwnCard(hyp, hyp.card!.metric, c.value)}>{c.label}</button
                  >
                {/each}
              </div>
            {/if}
          </div>
        </section>
      {/if}
    {:else}
      <!-- nothing selected -->
      <p class="help">
        Each card is a hypothesis: the question, the runs that tested it and a verdict. An arrow says which run the next
        idea came from. Click a card or a run to see it here; Shift-click runs to compare them.
      </p>
      {#if !ro}
        <form class="box" onsubmit={create}>
          <span class="label">New hypothesis</span>
          <input
            class="input"
            bind:this={newInput}
            bind:value={newTitle}
            placeholder="What are you testing?"
            aria-label="Title"
          />
          <select class="input" bind:value={newRun} aria-label="First run">
            <option value="">No run yet</option>
            {#each unfiled as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
          </select>
          <button class="btn btn-primary sm" type="submit" disabled={!newTitle.trim()}
            ><Icon name="plus" size={14} /> Create</button
          >
        </form>
      {/if}
      {#if unfiled.length}
        <section>
          <span class="label">Not on the board ({unfiled.length})</span>
          <ul class="plain">
            {#each unfiled.slice(0, 12) as r (r.id)}<li class="mono">{r.name}</li>{/each}
          </ul>
          {#if unfiled.length > 12}<p class="help">and {unfiled.length - 12} more</p>{/if}
        </section>
      {/if}
    {/if}
  </aside>
{/if}

<style>
  .side {
    width: 340px;
    padding: 14px 14px 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow: auto;
  }
  /* a scrolling column must not squeeze its rows (it cut the "← hypothesis" line) */
  .side > :global(*) {
    flex-shrink: 0;
  }
  .side.bar {
    width: 44px;
    padding: 6px;
    align-items: center;
  }
  .head,
  .title-row,
  .sec-head,
  .row,
  .line {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .head,
  .sec-head {
    justify-content: space-between;
  }
  .row {
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .icon {
    width: 30px;
    height: 30px;
    padding: 0;
    display: inline-grid;
    place-items: center;
    flex: none;
  }
  .icon.sm {
    width: 24px;
    height: 24px;
  }
  .icon.on {
    color: var(--warn);
  }
  h3 {
    margin: 0;
    font-size: 15px;
    overflow-wrap: anywhere;
  }
  .input.title {
    flex: 1;
    min-width: 0;
    font-weight: 600;
  }
  section,
  .box {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .box {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px;
  }
  .help {
    margin: 0;
    color: var(--muted);
    font-size: 12.5px;
  }
  textarea.input {
    height: auto;
    padding: 6px 10px;
    resize: vertical;
  }
  .note {
    font-family: var(--mono);
    font-size: 12.5px;
  }
  .md {
    font-size: 13px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    align-items: center;
  }
  .cat {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: 1px solid var(--border);
    background: none;
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 12.5px;
    color: var(--muted);
  }
  .cat i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--vc);
  }
  .cat[aria-pressed='true'] {
    color: var(--vc);
    border-color: var(--vc);
    background: color-mix(in srgb, var(--vc) 12%, var(--panel));
  }
  .cat[aria-pressed='true'] i {
    background: var(--vc);
  }
  .tg {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    color: var(--muted);
    font-size: 13px;
  }
  .back,
  .link {
    border: 0;
    background: none;
    padding: 0;
    text-align: left;
    color: var(--muted);
    font-size: 12.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .link {
    color: var(--text);
    font-size: 13px;
  }
  .back:hover,
  .link:hover {
    color: var(--accent);
  }
  .line {
    font-size: 13px;
    min-height: 26px;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
  }
  .missing {
    opacity: 0.6;
  }
  .missing .dot {
    border: 1.5px dashed var(--faint);
  }
  .nf {
    font-size: 10.5px;
    color: var(--faint);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .warn-box {
    margin: 0;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 12.5px;
    color: var(--muted);
    background: var(--panel-2);
  }
  .plain {
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 12.5px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .plain li {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kv {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .kv td {
    padding: 3px 4px;
    border-bottom: 1px solid var(--border);
    overflow-wrap: anywhere;
  }
  .kv .num {
    text-align: right;
  }
  .stat {
    flex: none;
  }
  @media (max-width: 900px) {
    .side {
      width: auto;
      position: static;
      max-height: none;
    }
  }
</style>
