<script lang="ts">
  // The Hypotheses page: a per-project board of hypotheses, the runs that tested them and why each
  // one followed from another, drawn as a tree or a timeline. See docs/guide/hypotheses.md.
  import { onMount } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import Icon from '../components/Icon.svelte';
  import VerdictIcon from '../components/VerdictIcon.svelte';
  import HypothesisPanel from '../components/HypothesisPanel.svelte';
  import HypothesisCategories from '../components/HypothesisCategories.svelte';
  import { api, type RunBrief } from '../lib/api';
  import { ask, confirmAction, notice } from '../lib/dialog.svelte';
  import { fmtDate, fmtNum, lowerIsBetter } from '../lib/format';
  import {
    SIZE,
    cardValue,
    chipY,
    colorVar,
    edges,
    filteredRuns,
    isFolded,
    layout,
    outcomeOf,
    related,
    timeline,
    verdictOf,
    type Board,
    type BoardData,
    type BoardListItem,
    type CardSetting,
    type HRun,
    type Hypothesis,
    type Placed,
    type ViewOptions,
  } from '../lib/hypotheses';
  import { Fold } from '../lib/fold.svelte';
  import { onLive } from '../lib/live';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const projects = $derived((app.info?.projects ?? []).map((p) => p.name));
  // The board list follows the workspace's project filter, as the Reports list does
  const globalProject = $derived(router.get('project'));
  const boards = new Fold('hypothesesBoardsFolded');
  let boardList = $state<BoardListItem[]>([]);
  let boardsLoaded = $state(false);
  // The board in the URL, else the first one listed
  const project = $derived(router.get('hproject') || boardList[0]?.project || '');
  const boardParam = $derived(router.get('hproject') ? router.get('hboard') : (boardList[0]?.name ?? ''));

  async function loadBoards() {
    const g = globalProject;
    try {
      const res = await api.hypothesisBoards(g || null);
      if (g !== globalProject) return;
      boardList = res.boards;
    } catch {
      boardList = [];
    }
    boardsLoaded = true;
  }
  $effect(() => {
    void globalProject;
    loadBoards();
  });

  let data = $state<BoardData | null>(null);
  let projectRuns = $state<RunBrief[]>([]);
  let loadError = $state('');
  let dragging = false;

  async function load() {
    const p = project;
    const b = boardParam;
    if (!p) {
      data = null;
      return;
    }
    try {
      const [board, list] = await Promise.all([api.hypotheses(p, b), api.runs('', p)]);
      if (p !== project || b !== boardParam || dragging) return;
      data = board;
      loadBoards();
      projectRuns = list.runs.filter((r) => r.project === p);
      loadError = '';
    } catch (e) {
      if (p === project) loadError = e instanceof Error ? e.message : String(e);
    }
  }
  $effect(() => {
    void project;
    void boardParam;
    data = null;
    load();
  });
  onMount(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = onLive('runs', () => {
      clearTimeout(timer);
      timer = setTimeout(load, 600);
    });
    return () => {
      clearTimeout(timer);
      off();
    };
  });

  const ro = $derived(!!data?.read_only);
  const view = $derived(router.get('hview') === 'timeline' ? 'timeline' : 'tree');
  const selHyp = $derived(router.get('h'));
  const selRun = $derived(router.get('hrun'));
  const picked = new SvelteSet<string>();
  let hideDead = $state(prefs.get('hypothesesHideDeadEnds', false));
  let starredOnly = $state(false);
  const showDead = new SvelteSet<string>();
  let hover = $state<{ run?: string; hyp?: string } | null>(null);
  let categories = $state(false);
  // bumped by "New hypothesis": the panel opens its form
  let askNew = $state(0);
  let drag = $state<{ h: Hypothesis; x: number; y: number; dx: number; dy: number; moved: boolean } | null>(null);

  const opts = $derived<ViewOptions | null>(
    data
      ? {
          board: data.board,
          runs: data.runs,
          hideDeadEnds: hideDead,
          showDeadEnds: showDead,
          starredOnly,
          selectedRun: selRun || null,
        }
      : null,
  );
  const placed = $derived(data && opts ? layout(data.hypotheses, opts) : []);
  const lines = $derived(data ? edges(placed, data.hypotheses) : []);
  const focus = $derived(hover && data && !drag ? related(data.hypotheses, hover) : null);
  const canvasW = $derived(Math.max(0, ...placed.map((p) => p.x + SIZE.width)) + 40);
  const canvasH = $derived(Math.max(0, ...placed.map((p) => p.y + p.height)) + 70);
  const tl = $derived(data && opts && view === 'timeline' ? timeline(data.hypotheses, opts) : null);

  // The metrics the chip number can show, from the project's runs
  const metrics = $derived([...new Set(projectRuns.flatMap((r) => Object.keys(r.summary ?? {})))].sort());

  function select(hyp?: string | null, run?: string | null) {
    picked.clear();
    router.set({ h: hyp ?? null, hrun: run ?? null });
  }

  function clickRun(e: MouseEvent, h: Hypothesis, r: HRun) {
    if (justDragged) return;
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      if (!data?.runs[r.id]) return;
      if (selRun && !picked.size && selRun !== r.id && data.runs[selRun]) picked.add(selRun);
      if (picked.has(r.id)) picked.delete(r.id);
      else picked.add(r.id);
      router.set({ h: null, hrun: null });
      return;
    }
    select(h.id, r.id);
  }

  // -- saving -----------------------------------------------------------------------------------
  async function save(h: Hypothesis) {
    if (!data || ro) return;
    try {
      const res = await api.saveHypothesis(project, data.name, $state.snapshot(h) as Hypothesis);
      if (!h.id) select(res.hypothesis.id, null);
    } catch (e) {
      await notice('Not saved', e instanceof Error ? e.message : String(e));
    }
    await load();
  }
  async function remove(h: Hypothesis) {
    if (!data || ro) return;
    try {
      await api.deleteHypothesis(project, data.name, h.id);
    } catch (e) {
      await notice('Not deleted', e instanceof Error ? e.message : String(e));
    }
    select(null, null);
    await load();
  }
  async function saveBoard(patch: Partial<Board>) {
    if (!data || ro) return;
    try {
      data.board = (await api.saveBoard(project, data.name, patch)).board;
    } catch (e) {
      await notice('Not saved', e instanceof Error ? e.message : String(e));
      await load();
    }
  }

  // -- several boards per project -----------------------------------------------------------------
  const boardLabel = (b: { name: string; title: string }) => b.title || b.name;
  const byProject = $derived(
    [...new Set(boardList.map((b) => b.project))].map((p) => ({ p, boards: boardList.filter((b) => b.project === p) })),
  );
  async function newBoard() {
    if (data?.read_only || !projects.length) return;
    const res = await ask(
      'New board',
      [
        { label: 'Name', value: '', placeholder: 'e.g. Data cleaning' },
        {
          label: 'Project',
          value: '',
          combo: (app.info?.projects ?? []).map((p) => ({ value: p.name, label: p.name, detail: `${p.runs} runs` })),
          preselect: globalProject || project || projects[0],
          placeholder: 'Type to find a project',
          newLabel: '',
        },
      ],
      { message: 'A board is one tree of hypotheses, for one study of a project.', confirm: 'Create' },
    );
    const title = res?.[0]?.trim();
    const proj = res?.[1]?.trim() || project;
    if (!title || !proj) return;
    if (!projects.includes(proj)) {
      await notice('Unknown project', `There is no project named “${proj}”. A board belongs to an existing project.`);
      return;
    }
    const base =
      title
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 56) || 'board';
    const taken = new Set(boardList.filter((b) => b.project === proj).map((b) => b.name));
    let name = base;
    for (let i = 2; taken.has(name); i++) name = `${base}-${i}`;
    try {
      await api.saveBoard(proj, name, { title });
      select(null, null);
      router.set({ hproject: proj, hboard: name });
      await loadBoards();
    } catch (e) {
      await notice('Not created', e instanceof Error ? e.message : String(e));
    }
  }
  async function deleteBoard() {
    if (!data || ro) return;
    const n = data.hypotheses.length;
    const ok = await confirmAction(
      'Delete board',
      `Delete the board “${boardLabel({ name: data.name, title: data.board.title })}” and its ${n} hypothes${n === 1 ? 'is' : 'es'}? Runs and reports are not touched.`,
      { confirm: 'Delete', danger: true },
    );
    if (!ok) return;
    try {
      await api.deleteBoard(project, data.name);
    } catch (e) {
      await notice('Not deleted', e instanceof Error ? e.message : String(e));
    }
    editingHead = false;
    select(null, null);
    router.set({ hproject: null, hboard: null });
    await loadBoards();
  }

  function setCard(metric: string, stat?: CardSetting['stat']) {
    if (!data) return;
    const card: CardSetting | null = metric
      ? { metric, stat: stat ?? data.board.card?.stat ?? 'best', higher: !lowerIsBetter(metric) }
      : null;
    saveBoard({ card });
  }

  // -- dragging cards -----------------------------------------------------------------------------
  let justDragged = false;
  function startDrag(e: PointerEvent, h: Hypothesis) {
    if (ro || e.button !== 0 || (e.target as Element).closest('button')) return;
    drag = { h, x: e.clientX, y: e.clientY, dx: h.position.dx, dy: h.position.dy, moved: false };
  }
  function moveDrag(e: PointerEvent) {
    if (!drag) return;
    const mx = e.clientX - drag.x;
    const my = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(mx, my) < 5) return;
    drag.moved = dragging = true;
    drag.h.position = { dx: drag.dx + mx, dy: drag.dy + my };
  }
  function endDrag() {
    const d = drag;
    drag = null;
    dragging = false;
    if (!d?.moved) return;
    justDragged = true;
    setTimeout(() => (justDragged = false), 0);
    save(d.h);
  }
  async function autoArrange() {
    if (!data) return;
    const moved = data.hypotheses.filter((h) => h.position.dx || h.position.dy);
    for (const h of moved) {
      h.position = { dx: 0, dy: 0 };
      await api.saveHypothesis(project, data.name, $state.snapshot(h) as Hypothesis).catch(() => null);
    }
    await load();
  }

  function toggleFold(h: Hypothesis) {
    h.folded = !isFolded(h);
    save(h);
  }

  // -- editing the text on an arrow ---------------------------------------------------------------
  let editingEdge = $state<string | null>(null);
  let edgeText = $state('');
  function editEdge(key: string, text: string) {
    if (ro) return;
    editingEdge = key;
    edgeText = text;
  }
  function finishEdge(keep: boolean) {
    const key = editingEdge;
    editingEdge = null;
    if (!keep || !key || !data) return;
    const [hid, idx] = key.split(':');
    const h = data.hypotheses.find((x) => x.id === hid);
    if (!h) return;
    if (idx === undefined) {
      h.reason = edgeText.trim();
      h.show_reason = true;
    } else if (h.also[+idx]) h.also[+idx].reason = edgeText.trim();
    save(h);
  }
  const focusInput = (el: HTMLInputElement) => {
    el.focus();
    el.select();
  };

  // -- the board's title and description ---------------------------------------------------------
  let editingHead = $state(false);
  let headTitle = $state('');
  let headDesc = $state('');
  function editHead() {
    if (!data || ro) return;
    headTitle = data.board.title;
    headDesc = data.board.description;
    editingHead = true;
  }

  // -- helpers for the template -------------------------------------------------------------------
  const runName = (id: string) => data?.runs[id]?.name ?? id;
  const isDead = (r: HRun) => !!data && !!outcomeOf(data.board, r.outcome)?.dead_end;
  const foldHidden = (p: Placed) =>
    data && opts ? filteredRuns(p.hyp, opts).filter((r) => !p.runs.includes(r)).length : 0;
  const chipNumber = (h: Hypothesis, r: HRun) => {
    if (!data) return '';
    const card = h.card ?? data.board.card;
    if (!card) return '';
    const v = cardValue(data.runs[r.id], card);
    return v === null ? '—' : fmtNum(v);
  };
  const STAT = { best: 'Best', last: 'Last', min: 'Min', max: 'Max' } as const;
  /** What the chip number is, such as "val/acc (Best)". */
  const numberName = (h: Hypothesis) => {
    const card = h.card ?? data?.board.card;
    return card ? `${card.metric} (${STAT[card.stat]})` : '';
  };
  const tip = (r: HRun) => {
    const run = data?.runs[r.id];
    if (!run) return `Run ${r.id} was not found. It may have been moved or deleted.`;
    const lines = Object.entries(run.summary)
      .slice(0, 12)
      .map(
        ([m, s]) =>
          `${m}: last ${fmtNum(typeof s.last === 'number' ? s.last : null)}, min ${fmtNum(s.min)}, max ${fmtNum(s.max)}`,
      );
    return [run.name, ...lines].join('\n');
  };
  const dim = (id: string) => !!focus && !focus.has(id);
</script>

<svelte:window onpointermove={moveDrag} onpointerup={endDrag} onkeydown={boards.onkeydown} />

<div class="page" class:folded={boards.folded}>
  {#if boards.folded}
    <aside class="card side bar">
      <button
        class="btn btn-ghost icon"
        aria-label="Show the board list"
        title="Show the board list ( [ )"
        onclick={boards.toggle}><Icon name="sidebar" size={16} /></button
      >
      {#if !data?.read_only}
        <button class="btn btn-ghost icon" aria-label="New board" title="New board" onclick={newBoard}
          ><Icon name="plus" size={16} /></button
        >
      {/if}
    </aside>
  {:else}
    <aside class="card side">
      <div class="head">
        <span class="label">Hypotheses</span>
        <span class="grow"></span>
        {#if !data?.read_only}
          <button class="btn sm" onclick={newBoard}><Icon name="plus" size={15} /> New</button>
        {/if}
        <button
          class="btn btn-ghost icon"
          aria-label="Hide the board list"
          title="Hide the board list ( [ )"
          onclick={boards.toggle}><Icon name="sidebar" size={16} /></button
        >
      </div>
      {#if boardsLoaded && !boardList.length}
        <p class="faint small">No boards yet. Press <b>New</b> to start one.</p>
      {/if}
      {#each byProject as g (g.p)}
        <div class="item group" title={g.p}><Icon name="folder" size={16} /><span class="bt">{g.p}</span></div>
        {#each g.boards as b (b.project + '/' + b.name)}
          <button
            class="item child"
            class:on={b.project === project && b.name === data?.name}
            onclick={() => {
              select(null, null);
              router.set({ hproject: b.project, hboard: b.name });
            }}
            title="{b.project}/hypotheses/{b.name}/"
          >
            <Icon name="tree" size={15} />
            <span class="bt">{boardLabel(b)}</span>
            <span class="count">{b.count}</span>
          </button>
        {/each}
      {/each}
      <p class="hint">
        A board is one study: a tree of hypotheses and the runs that tested them. Boards are JSON files in
        <code>&lt;project&gt;/hypotheses/</code>.
      </p>
    </aside>
  {/if}

  <div class="main">
    {#if !project}
      {#if boardsLoaded}
        <section class="card pick">
          <h2>No hypothesis boards yet</h2>
          <p class="faint">
            A board keeps the story of a study: what you tested, the runs that tested it and which run led to the next
            idea. Press <b>New</b> in the board list to start one.
          </p>
        </section>
      {:else}
        <section class="card pick faint">Loading…</section>
      {/if}
    {:else if loadError && !data}
      <section class="card pick">Could not load the board: {loadError}</section>
    {:else if data && opts}
      <div class="toolbar">
        <div class="seg" role="group" aria-label="View">
          <button aria-pressed={view === 'tree'} onclick={() => router.set({ hview: null })}
            ><Icon name="board" size={15} /> Board</button
          >
          <button aria-pressed={view === 'timeline'} onclick={() => router.set({ hview: 'timeline' })}
            ><Icon name="timeline" size={15} /> Timeline</button
          >
        </div>
        <label class="tg"
          ><button
            class="switch"
            role="switch"
            aria-checked={hideDead}
            aria-label="Hide dead ends"
            onclick={() => {
              hideDead = !hideDead;
              showDead.clear();
              prefs.set('hypothesesHideDeadEnds', hideDead);
            }}
          ></button>Hide dead ends</label
        >
        <label class="tg"
          ><button
            class="switch"
            role="switch"
            aria-checked={starredOnly}
            aria-label="Starred only"
            onclick={() => (starredOnly = !starredOnly)}
          ></button>Starred only</label
        >
        <label class="tg"
          >Number
          <select
            class="input sm"
            value={data.board.card?.metric ?? ''}
            disabled={ro}
            onchange={(e) => setCard(e.currentTarget.value)}
          >
            <option value="">None</option>
            {#each metrics as m (m)}<option value={m}>{m}</option>{/each}
            {#if data.board.card && !metrics.includes(data.board.card.metric)}
              <option value={data.board.card.metric}>{data.board.card.metric}</option>
            {/if}
          </select>
          {#if data.board.card}
            <select
              class="input sm"
              aria-label="Summary"
              value={data.board.card.stat}
              disabled={ro}
              onchange={(e) => setCard(data!.board.card!.metric, e.currentTarget.value as CardSetting['stat'])}
            >
              <option value="best">Best</option>
              <option value="last">Last</option>
              <option value="min">Min</option>
              <option value="max">Max</option>
            </select>
          {/if}
        </label>
        {#if view === 'tree'}
          <button
            class="btn btn-ghost icon"
            title="Auto-arrange cards"
            aria-label="Auto-arrange cards"
            disabled={ro}
            onclick={autoArrange}><Icon name="grid" size={16} /></button
          >
        {/if}
        <span class="grow"></span>
        {#if ro}<span class="chip">Read-only</span>{:else}
          <button
            class="btn sm"
            onclick={() => {
              select(null, null);
              askNew++;
            }}><Icon name="idea" size={15} /> New hypothesis</button
          >
        {/if}
      </div>

      <div class="layout">
        <section class="card canvas-card">
          <div class="board-head">
            {#if editingHead}
              <form
                onsubmit={(e) => {
                  e.preventDefault();
                  editingHead = false;
                  saveBoard({ title: headTitle, description: headDesc });
                }}
              >
                <input
                  class="input"
                  bind:value={headTitle}
                  placeholder="Board title (optional)"
                  aria-label="Board title"
                />
                <textarea
                  class="input"
                  bind:value={headDesc}
                  rows="2"
                  placeholder="Description (optional)"
                  aria-label="Board description"></textarea>
                <div class="row">
                  <button class="btn btn-primary sm" type="submit">Save</button>
                  <button class="btn sm" type="button" onclick={() => (editingHead = false)}>Cancel</button>
                  <span class="grow"></span>
                  {#if data.boards.length > 1 || data.hypotheses.length}
                    <button class="btn btn-ghost sm danger" type="button" onclick={deleteBoard}
                      ><Icon name="trash" size={14} /> Delete board</button
                    >
                  {/if}
                </div>
              </form>
            {:else if data.board.title || data.board.description}
              <div class="grow">
                {#if data.board.title}<h2>{data.board.title}</h2>{/if}
                {#if data.board.description}<p>{data.board.description}</p>{/if}
              </div>
              {#if !ro}
                <button
                  class="btn btn-ghost icon hover-only"
                  title="Edit title and description"
                  aria-label="Edit title and description"
                  onclick={editHead}><Icon name="edit" size={15} /></button
                >
              {/if}
            {:else if !ro}
              <button class="add-head" onclick={editHead}>+ Add a title and description</button>
            {/if}
          </div>

          <div
            class="stage"
            class:dragging={!!drag}
            onmouseleave={() => (hover = null)}
            onclick={(e) => {
              // a click on the empty canvas clears the selection
              const t = e.target as Element;
              if (!justDragged && (t === e.currentTarget || t.classList.contains('canvas'))) select(null, null);
            }}
            role="presentation"
          >
            {#if !data.hypotheses.length}
              <div class="empty faint">
                <p><b>No hypotheses yet.</b></p>
                <p>
                  Start with the question you are testing: press <b>New hypothesis</b> in the side panel, then add the
                  runs that test it. Pick a run later and use <b>Follow up</b> to start the next hypothesis from it.
                </p>
              </div>
            {:else if view === 'tree'}
              <div class="canvas" style="width:{canvasW}px;height:{canvasH}px">
                <svg width={canvasW} height={canvasH} aria-hidden="true">
                  {#each lines as l (l.to.hyp.id + ':' + l.index)}
                    {@const x1 = l.from.x + SIZE.width}
                    {@const y1 = chipY(l.from, l.run)}
                    {@const x2 = l.to.x}
                    {@const y2 = l.to.y + SIZE.head / 2}
                    {@const mx = (x1 + x2) / 2}
                    <path
                      class="edge"
                      class:also={l.also}
                      class:dim={focus && !(focus.has(l.run) && focus.has(l.to.hyp.id))}
                      d="M{x1} {y1} C{mx} {y1}, {mx} {y2}, {x2} {y2}"
                    />
                  {/each}
                </svg>
                {#each lines as l (l.to.hyp.id + ':' + l.index)}
                  {@const x1 = l.from.x + SIZE.width}
                  {@const y1 = chipY(l.from, l.run)}
                  {@const x2 = l.to.x}
                  {@const y2 = l.to.y + SIZE.head / 2}
                  {@const key = l.also ? `${l.to.hyp.id}:${l.index}` : l.to.hyp.id}
                  {@const at = `left:${(x1 + x2) / 2}px;top:${(y1 + y2) / 2}px`}
                  {@const faded = !!focus && !(focus.has(l.run) && focus.has(l.to.hyp.id))}
                  {#if editingEdge === key}
                    <input
                      class="input label-edit"
                      style={at}
                      bind:value={edgeText}
                      placeholder="Why this link? (empty: no text)"
                      use:focusInput
                      onkeydown={(e) => {
                        if (e.key === 'Enter') finishEdge(true);
                        if (e.key === 'Escape') finishEdge(false);
                      }}
                      onblur={() => finishEdge(true)}
                    />
                  {:else if l.reason && l.showReason}
                    <button
                      class="elabel"
                      class:also={l.also}
                      class:dim={faded}
                      style={at}
                      title={ro ? l.reason : 'Click to edit'}
                      onclick={() => editEdge(key, l.reason)}>{l.reason}</button
                    >
                  {:else if !ro}
                    <button
                      class="handle"
                      class:dim={faded}
                      style={at}
                      title={l.reason ? 'Text hidden; click to edit' : 'Add text to this link'}
                      aria-label={l.reason ? 'Edit the hidden text of this link' : 'Add text to this link'}
                      onclick={() => editEdge(key, l.reason)}>{l.reason ? '…' : '+'}</button
                    >
                  {/if}
                {/each}

                {#each placed as p (p.hyp.id)}
                  {@const v = verdictOf(data.board, p.hyp.verdict)}
                  {@const n = p.hyp.runs.length}
                  {@const hiddenByFold = foldHidden(p)}
                  <div
                    class="hcard"
                    class:sel={selHyp === p.hyp.id && !selRun}
                    class:starred={p.hyp.star}
                    class:dim={dim(p.hyp.id)}
                    style="left:{p.x}px;top:{p.y}px;border-top-color:{colorVar(v.color)}"
                  >
                    <div
                      class="hhead"
                      role="button"
                      tabindex="0"
                      title={ro ? p.hyp.title : 'Click to open; drag to move'}
                      onpointerdown={(e) => startDrag(e, p.hyp)}
                      onclick={() => !justDragged && select(p.hyp.id)}
                      onkeydown={(e) => e.key === 'Enter' && select(p.hyp.id)}
                      onmouseenter={() => (hover = { hyp: p.hyp.id })}
                    >
                      <div class="k">
                        <span class="verdict" style="--vc:{colorVar(v.color)}"
                          ><VerdictIcon icon={v.icon} />{v.label}</span
                        >
                        {#if n > 3}
                          <button
                            class="fold"
                            class:closed={isFolded(p.hyp)}
                            title={isFolded(p.hyp) ? 'Show all runs' : 'Fold to key runs'}
                            onclick={(e) => {
                              e.stopPropagation();
                              if (!ro) toggleFold(p.hyp);
                            }}
                            >{n} runs
                            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"
                              ><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.6" /></svg
                            ></button
                          >
                        {:else}
                          <span>{n} run{n === 1 ? '' : 's'}</span>
                        {/if}
                        <span class="meta">
                          {#if p.hyp.card}<span class="own" title="This card shows {numberName(p.hyp)}"
                              >{p.hyp.card.metric}</span
                            >{/if}
                          {#if p.hyp.reports.length}{p.hyp.reports.length} report{p.hyp.reports.length > 1
                              ? 's'
                              : ''}{/if}
                          {#if p.hyp.star}<span class="star">★</span>{/if}
                        </span>
                      </div>
                      <div class="t">{p.hyp.title}</div>
                    </div>
                    {#each p.runs as r (r.id)}
                      {@const o = outcomeOf(data.board, r.outcome)}
                      {@const run = data.runs[r.id]}
                      <button
                        class="chiprow"
                        class:dead={o?.dead_end}
                        class:missing={!run}
                        class:sel={selRun === r.id}
                        class:picked={picked.has(r.id)}
                        class:dim={dim(r.id)}
                        title={tip(r)}
                        onclick={(e) => clickRun(e, p.hyp, r)}
                        onmouseenter={() => (hover = { run: r.id })}
                      >
                        <span class="dot" style="background:{run ? colorVar(o?.color ?? 'gray') : 'transparent'}"
                        ></span>
                        <span class="n">{runName(r.id)}</span>
                        {#if r.star}<span class="star">★</span>{/if}
                        {#if run?.status === 'running'}<span class="live">live</span>{/if}
                        {#if !run}<span class="nf">not found</span>{:else}<span class="m" title={numberName(p.hyp)}
                            >{chipNumber(p.hyp, r)}</span
                          >{/if}
                      </button>
                    {/each}
                    {#if p.hidden.length}
                      <button
                        class="more"
                        title={hiddenByFold ? 'Show all runs' : 'Show dead ends'}
                        onclick={() => {
                          if (hiddenByFold) {
                            if (!ro) toggleFold(p.hyp);
                          } else if (showDead.has(p.hyp.id)) showDead.delete(p.hyp.id);
                          else showDead.add(p.hyp.id);
                        }}
                        >+{p.hidden.length}
                        <span class="strip"
                          >{#each p.hidden.slice(0, 16) as r (r.id)}<span
                              class="dot sm"
                              style="background:{colorVar(outcomeOf(data.board, r.outcome)?.color ?? 'gray')}"
                            ></span>{/each}</span
                        ></button
                      >
                    {/if}
                  </div>
                {/each}
              </div>
            {:else if tl}
              {@const LANE = 18}
              {@const ROW = 52}
              {@const gw = 18 + tl.lanes.length * LANE}
              {@const laneOf = new Map(tl.lanes.map((l) => [l.hyp.id, l]))}
              {@const rowOf = new Map(tl.rows.map((row, i) => [row.run.id, i]))}
              <div class="tl">
                <svg width={gw} height={tl.rows.length * ROW} aria-hidden="true">
                  {#each tl.lanes as l (l.hyp.id)}
                    {@const x = 12 + l.lane * LANE}
                    {@const c = colorVar(verdictOf(data.board, l.hyp.verdict).color)}
                    {@const pr = l.hyp.parent_run ? rowOf.get(l.hyp.parent_run) : undefined}
                    {@const pl = pr !== undefined ? laneOf.get(tl.rows[pr].hyp.id) : undefined}
                    <line
                      x1={x}
                      x2={x}
                      y1={l.first * ROW + ROW / 2}
                      y2={l.last * ROW + ROW / 2}
                      stroke={c}
                      stroke-width="2.5"
                      stroke-linecap="round"
                    />
                    {#if pr !== undefined && pl && pl.hyp.id !== l.hyp.id}
                      {@const x0 = 12 + pl.lane * LANE}
                      {@const y0 = pr * ROW + ROW / 2}
                      {@const y1 = l.first * ROW + ROW / 2}
                      <path
                        d="M{x0} {y0} C{x0} {y0 + ROW * 0.8}, {x} {y1 - ROW * 0.8}, {x} {y1}"
                        fill="none"
                        stroke={c}
                        stroke-width="2"
                        opacity="0.8"
                      />
                    {/if}
                  {/each}
                  {#each tl.rows as row, i (row.run.id)}
                    {@const l = laneOf.get(row.hyp.id)}
                    {#if l}
                      <circle
                        cx={12 + l.lane * LANE}
                        cy={i * ROW + ROW / 2}
                        r="5.5"
                        fill={data.runs[row.run.id]
                          ? colorVar(outcomeOf(data.board, row.run.outcome)?.color ?? 'gray')
                          : 'var(--panel)'}
                        stroke={data.runs[row.run.id] ? 'var(--panel)' : 'var(--faint)'}
                        stroke-width="2"
                      />
                    {/if}
                  {/each}
                </svg>
                {#each tl.rows as row, i (row.run.id)}
                  {@const first = laneOf.get(row.hyp.id)?.first === i}
                  {@const run = data.runs[row.run.id]}
                  <button
                    class="tlrow"
                    class:sel={selRun === row.run.id}
                    class:picked={picked.has(row.run.id)}
                    class:dead={isDead(row.run)}
                    class:missing={!run}
                    style="grid-template-columns:{gw}px 150px minmax(0,1fr) 80px"
                    onclick={(e) => clickRun(e, row.hyp, row.run)}
                  >
                    <span></span>
                    <span class="d mono">{row.time ? fmtDate(row.time) : '—'}</span>
                    <span class="c">
                      <span class="l1"
                        ><span class="n mono">{runName(row.run.id)}</span>{#if row.run.star}<span class="star">★</span
                          >{/if}<span class="s">{row.hyp.title}</span></span
                      >
                      <span class="l2"
                        >{#if first && row.hyp.reason}<em>Why:</em> {row.hyp.reason} &middot;&nbsp;{/if}{row.run
                          .conclusion ||
                          (run ? (run.status === 'running' ? 'Running' : 'No conclusion yet') : 'Run not found')}</span
                      >
                    </span>
                    <span class="d mono right">{run ? chipNumber(row.hyp, row.run) : 'not found'}</span>
                  </button>
                {/each}
              </div>
            {/if}
          </div>

          <div class="legend">
            <span class="grp">
              {#each data.board.verdicts as v (v.id)}
                <span class="verdict" style="--vc:{colorVar(v.color)}"><VerdictIcon icon={v.icon} />{v.label}</span>
              {/each}
            </span>
            <span class="grp">
              {#each data.board.outcomes as o (o.id)}
                <span><i style="background:{colorVar(o.color)}"></i>{o.label.toLowerCase()}</span>
              {/each}
            </span>
            <span class="grp">
              <svg width="20" height="6" aria-hidden="true"
                ><path d="M1 3h18" stroke="var(--edge)" stroke-width="1.8" /></svg
              >led to
              <svg width="20" height="6" aria-hidden="true"
                ><path d="M1 3h18" stroke="var(--edge)" stroke-width="1.8" stroke-dasharray="4 3" /></svg
              >also informed by
            </span>
            {#if !ro}
              <button
                class="btn btn-ghost icon sm"
                title="Edit categories"
                aria-label="Edit categories"
                onclick={() => (categories = true)}><Icon name="edit" size={14} /></button
              >
            {/if}
          </div>
        </section>

        <HypothesisPanel
          {data}
          {project}
          {projectRuns}
          {selHyp}
          {selRun}
          {picked}
          {ro}
          onsave={save}
          ondelete={remove}
          onselect={select}
          oncategories={() => (categories = true)}
          {askNew}
        />
      </div>

      {#if categories}
        <HypothesisCategories
          board={data.board}
          onclose={() => (categories = false)}
          onsave={(b) => {
            categories = false;
            saveBoard(b);
          }}
        />
      {/if}
    {:else}
      <section class="card pick faint">Loading…</section>
    {/if}
  </div>
</div>

<style>
  /* the side list, as the Runs workspace draws it: a folder per project, its items indented */
  .item {
    display: flex;
    align-items: center;
    gap: 9px;
    border: 0;
    background: none;
    border-radius: 8px;
    padding: 7px 8px;
    text-align: left;
    min-width: 0;
    color: var(--text);
    font-size: 14px;
  }
  .item.group {
    margin-top: 2px;
    cursor: default;
  }
  .item.child {
    padding-left: 22px;
  }
  .item.child:hover {
    background: var(--panel-2);
  }
  .item.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 550;
  }
  .bt {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .count {
    flex: none;
    color: var(--faint);
    font: 12px var(--mono);
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
  .pick {
    padding: 20px;
  }
  .pick h2 {
    margin: 0;
    font-size: 17px;
  }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 18px;
  }
  .page {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .page.folded {
    grid-template-columns: 44px minmax(0, 1fr);
  }
  .main {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
  }
  .side {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    position: sticky;
    top: 16px;
    min-width: 0;
  }
  .side.bar {
    padding: 6px;
    align-items: center;
  }
  .side .head {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }
  .side .icon {
    width: 30px;
    height: 30px;
  }
  .btn.sm {
    height: 30px;
  }
  .small {
    font-size: 12px;
  }
  .board-head .danger {
    color: var(--err);
  }
  .toolbar .seg button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .tg {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    color: var(--muted);
    font-size: 13px;
    white-space: nowrap;
  }
  .input.sm {
    height: 30px;
    max-width: 220px;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .icon {
    width: 34px;
    padding: 0;
    justify-content: center;
  }
  .icon.sm {
    width: 26px;
    height: 26px;
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px;
    align-items: start;
  }
  .canvas-card {
    --edge: color-mix(in srgb, var(--faint) 70%, var(--border));
    position: relative;
    display: flex;
    flex-direction: column;
    height: max(460px, calc(100vh - 190px));
    overflow: hidden;
    background: var(--bg);
  }
  .board-head {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 14px 20px 0;
  }
  .board-head h2 {
    margin: 0;
    font-size: 17px;
    letter-spacing: -0.01em;
  }
  .board-head p {
    margin: 4px 0 0;
    color: var(--muted);
    font-size: 13.5px;
    max-width: 80ch;
    white-space: pre-wrap;
  }
  .board-head form {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: min(640px, 100%);
  }
  .board-head textarea {
    height: auto;
    padding: 6px 10px;
    resize: vertical;
  }
  .board-head .row {
    display: flex;
    gap: 6px;
  }
  .hover-only {
    opacity: 0;
  }
  .board-head:hover .hover-only,
  .hover-only:focus-visible {
    opacity: 1;
  }
  @media (hover: none) {
    .hover-only {
      opacity: 1;
    }
  }
  .add-head {
    border: 0;
    background: none;
    color: var(--faint);
    font-size: 13px;
    padding: 0;
  }
  .add-head:hover {
    color: var(--accent);
  }
  .stage {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 18px 20px 64px;
  }
  .empty {
    max-width: 60ch;
    font-size: 13.5px;
  }
  .canvas {
    position: relative;
  }
  .canvas > svg {
    position: absolute;
    inset: 0;
    overflow: visible;
    pointer-events: none;
  }
  .edge {
    fill: none;
    stroke: var(--edge);
    stroke-width: 1.6;
    transition: opacity 0.15s;
  }
  .edge.also {
    stroke-dasharray: 4 4;
  }
  .dim {
    opacity: 0.22;
  }
  .elabel,
  .handle,
  .label-edit {
    position: absolute;
    transform: translate(-50%, -50%);
  }
  .elabel {
    max-width: 112px;
    font-size: 11.5px;
    line-height: 1.3;
    color: var(--muted);
    background: var(--bg);
    padding: 3px 6px;
    border-radius: 5px;
    border: 0;
    text-align: center;
    cursor: text;
  }
  .elabel.also {
    font-style: italic;
  }
  .elabel:hover {
    color: var(--text);
    box-shadow: 0 0 0 1px var(--border);
  }
  .handle {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--faint);
    font-size: 12px;
    line-height: 13px;
    padding: 0;
    opacity: 0.6;
  }
  .handle:hover {
    opacity: 1;
    color: var(--accent);
    border-color: var(--accent);
  }
  .label-edit {
    width: 200px;
    height: 30px;
    font-size: 12px;
    z-index: 2;
    background: var(--panel);
  }
  .hcard {
    position: absolute;
    width: 260px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-top-width: 3px;
    border-radius: 11px;
    box-shadow: var(--lift);
    transition:
      opacity 0.15s,
      box-shadow 0.15s;
  }
  .hcard.starred {
    border-left-color: var(--warn);
    border-right-color: var(--warn);
    border-bottom-color: var(--warn);
  }
  .hcard.sel {
    box-shadow: 0 0 0 3px var(--accent-soft);
    border-left-color: var(--accent);
    border-right-color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .hhead {
    height: 60px;
    padding: 8px 12px 6px;
    border-bottom: 1px solid var(--border);
    cursor: grab;
    touch-action: none;
    outline-offset: -2px;
  }
  .dragging .hhead {
    cursor: grabbing;
  }
  .dragging .hcard {
    transition: none;
  }
  .k {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10.5px;
    color: var(--faint);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
  }
  .verdict {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 1px 6px 1px 4px;
    border-radius: 4px;
    color: var(--vc);
    background: color-mix(in srgb, var(--vc) 15%, var(--panel));
  }
  .fold {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    border: 0;
    background: none;
    padding: 0 3px;
    border-radius: 4px;
    color: inherit;
    font: inherit;
    letter-spacing: inherit;
    text-transform: inherit;
  }
  .fold:hover {
    color: var(--text);
    background: var(--panel-2);
  }
  .fold.closed svg {
    transform: rotate(-90deg);
  }
  .own {
    max-width: 90px;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: var(--mono);
    color: var(--muted);
  }
  .meta {
    margin-left: auto;
    text-transform: none;
    letter-spacing: 0;
    display: inline-flex;
    gap: 4px;
  }
  .t {
    font-weight: 600;
    font-size: 13px;
    line-height: 1.3;
    margin-top: 3px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .star {
    color: var(--warn);
  }
  .chiprow {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: 34px;
    padding: 0 12px;
    border: 0;
    background: transparent;
    text-align: left;
    font-size: 13px;
  }
  .chiprow:hover {
    background: var(--panel-2);
  }
  .chiprow.sel {
    background: var(--accent-soft);
  }
  .chiprow.picked {
    box-shadow: inset 3px 0 0 var(--accent);
    background: var(--accent-soft);
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
  }
  .dot.sm {
    width: 6px;
    height: 6px;
    display: inline-block;
  }
  .chiprow .n {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--mono);
    font-size: 12.5px;
  }
  .chiprow .m {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .chiprow.dead .n,
  .tlrow.dead .n {
    color: var(--faint);
    text-decoration: line-through;
    text-decoration-color: var(--border);
  }
  .chiprow.missing {
    opacity: 0.65;
  }
  .chiprow.missing .n {
    font-style: italic;
    color: var(--faint);
  }
  .chiprow.missing .dot {
    border: 1.5px dashed var(--faint);
  }
  .nf {
    font-size: 10.5px;
    color: var(--faint);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .live {
    color: var(--accent);
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .more {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    height: 26px;
    border: 0;
    background: none;
    padding: 0 12px 0 29px;
    font-size: 12px;
    color: var(--faint);
  }
  .more:hover {
    color: var(--text);
  }
  .strip {
    display: inline-flex;
    gap: 3px;
  }
  .legend {
    position: absolute;
    left: 12px;
    bottom: 12px;
    max-width: calc(100% - 24px);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 14px;
    font-size: 12px;
    color: var(--muted);
    background: color-mix(in srgb, var(--panel) 94%, transparent);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 5px 6px 5px 10px;
    box-shadow: var(--lift);
  }
  .legend .grp {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 5px 8px;
  }
  .legend i {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-right: 4px;
  }
  .tl {
    position: relative;
    min-width: 560px;
  }
  .tl > svg {
    position: absolute;
    left: 0;
    top: 0;
    overflow: visible;
  }
  .tlrow {
    display: grid;
    align-items: center;
    gap: 12px;
    width: 100%;
    height: 52px;
    border: 0;
    border-bottom: 1px solid var(--border);
    background: none;
    text-align: left;
    padding: 0 12px 0 0;
  }
  .tlrow:hover {
    background: var(--panel);
  }
  .tlrow.sel {
    background: var(--accent-soft);
  }
  .tlrow.picked {
    box-shadow: inset 3px 0 0 var(--accent);
  }
  .tlrow.missing {
    opacity: 0.6;
  }
  .tlrow .d {
    white-space: nowrap;
    font-size: 12px;
    color: var(--faint);
  }
  .tlrow .right {
    text-align: right;
    color: var(--muted);
  }
  .tlrow .c {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .l1 {
    display: flex;
    gap: 8px;
    align-items: baseline;
    white-space: nowrap;
    overflow: hidden;
  }
  .l1 .n {
    font-size: 12.5px;
  }
  .l1 .s {
    font-size: 12px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .l2 {
    font-size: 12.5px;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .l2 em {
    font-style: normal;
    color: var(--text);
  }
  @media (max-width: 900px) {
    .layout,
    .page,
    .page.folded {
      grid-template-columns: minmax(0, 1fr);
    }
    .side {
      position: static;
    }
    .canvas-card {
      height: 70vh;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .hcard,
    .edge {
      transition: none;
    }
  }
</style>
