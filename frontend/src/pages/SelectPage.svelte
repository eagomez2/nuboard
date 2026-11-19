<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import ScalarPicker from '../components/ScalarPicker.svelte';
  import { api, type SavedPick, type StepCheckpoint, type StepRows, type StepsResult } from '../lib/api';
  import { seriesVar } from '../lib/colors';
  import { ask, confirmAction, notice } from '../lib/dialog.svelte';
  import { directionOf } from '../lib/directions.svelte';
  import { fmtAxis, fmtDate, fmtNum, fmtValue } from '../lib/format';
  import { onLive } from '../lib/live';
  import { router } from '../lib/router.svelte';
  import { bestIndex, better, edge2d, niceTicks, padded, rankOf, rowId, type Dir } from '../lib/selection';
  import { app } from '../lib/state.svelte';

  // The Select page: which run at which step to take forward, when runs win on different scalars.
  // A row is a run at a step where every chosen scalar was logged; the shortlist holds the rows no
  // other row beats on every scalar (the server finds it, see nuboard/selection.py). Rows can be
  // compared side by side and picked with a note, saved in the project's picks.json.
  // URL: `m` the scalars, `dirs` this view's own direction of each (empty: the project's), `x` and
  // `y` the scatter axes, `rows` the rows to compare, `sort` the shortlist's column, `tab`.

  const MAX_COMPARE = 6;
  const SHOWN = 100; // shortlist rows shown before "Show all"

  const runs = $derived(app.visibleRuns().filter((r) => r.metric_count > 0));
  const runKeys = $derived(runs.map((r) => r.key));
  const projects = $derived([...new Set(runs.map((r) => r.project))].sort());
  const allMetrics = $derived(app.runs?.metrics ?? []);
  const tab = $derived(router.get('tab', 'shortlist'));

  // ---- the scalars and which way is better for each ----
  const metrics = $derived(router.list('m'));
  const overrides = $derived(router.get('dirs').split(','));
  const dirInfo = $derived(metrics.map((m, i) => directionOf(projects, m, true, overrides[i] || null)));
  // projects that disagree, with no choice made here: higher is better until one is picked
  const dirs = $derived(dirInfo.map((g): Dir => g.direction ?? 'max'));

  function setMetrics(list: string[], own: string[]) {
    router.set({ m: list.length ? list.join(',') : null, dirs: own.some(Boolean) ? own.join(',') : null });
  }
  const ownDirs = () => metrics.map((_, i) => overrides[i] ?? '');
  function addMetric(m: string) {
    if (!m || metrics.includes(m)) return;
    setMetrics([...metrics, m], [...ownDirs(), '']);
  }
  function removeMetric(m: string) {
    const i = metrics.indexOf(m);
    setMetrics(
      metrics.filter((_, k) => k !== i),
      ownDirs().filter((_, k) => k !== i),
    );
  }
  function flip(i: number) {
    const own = ownDirs();
    const next: Dir = dirs[i] === 'max' ? 'min' : 'max';
    const saved = directionOf(projects, metrics[i], true);
    own[i] = saved.set && saved.direction === next ? '' : next; // back to the project's: nothing kept
    setMetrics(metrics, own);
  }
  const arrow = (d: Dir) => (d === 'min' ? '↓' : '↑');

  // Scalars to suggest before any is chosen: evaluation ones first
  const suggestions = $derived(
    [...allMetrics]
      .filter((m) => !m.startsWith('system/') && !m.startsWith('timing/'))
      .sort((a, b) => Number(/^(val|eval|test)/i.test(b)) - Number(/^(val|eval|test)/i.test(a)))
      .slice(0, 6),
  );

  // ---- scoring ----
  let result = $state<StepsResult | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  const query = $derived(JSON.stringify([runKeys, metrics, dirs]));
  $effect(() => {
    const [keys, ms, ds] = JSON.parse(query) as [string[], string[], Dir[]];
    void app.runs?.version; // again when runs change
    if (!keys.length || !ms.length) {
      result = null;
      return;
    }
    const ctrl = new AbortController();
    loading = true;
    api
      .steps(keys, ms, ds, ctrl.signal)
      .then((r) => {
        result = r;
        error = null;
      })
      .catch((e) => {
        if (e.name !== 'AbortError') error = String(e.message ?? e);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) loading = false;
      });
    return () => ctrl.abort();
  });
  // only a result for the scalars and directions shown
  const data = $derived(
    result && JSON.stringify([result.metrics, result.directions]) === JSON.stringify([metrics, dirs]) ? result : null,
  );

  type Row = StepRows & { id: string; key: string; front: boolean };
  const runOf = (r: StepRows) => data!.runs[r.run];
  const toRow = (r: StepRows, front: boolean): Row => ({
    ...r,
    id: rowId(data!.runs[r.run].key, r.step),
    key: data!.runs[r.run].key,
    front,
  });
  const front = $derived(data ? data.front.map((r) => toRow(r, true)) : []);
  const others = $derived(data ? data.others.map((r) => toRow(r, false)) : []);
  const byId = $derived(new Map([...front, ...others].map((r) => [r.id, r])));
  const best = $derived(
    bestIndex(
      front.map((r) => r.values),
      dirs,
    ),
  );
  const color = (r: StepRows) => seriesVar(r.run);

  // ---- picks ----
  let picks = $state<SavedPick[]>([]);
  async function loadPicks() {
    picks = await api.picks().catch(() => picks);
  }
  onMount(() => {
    void loadPicks();
    return onLive('runs', () => void loadPicks());
  });
  const shownPicks = $derived(picks.filter((p) => projects.includes(p.project)));
  const pickedIds = $derived(new Set(shownPicks.filter((p) => p.key).map((p) => rowId(p.key!, p.step))));

  // ---- rows chosen to compare ----
  const chosen = $derived(router.list('rows'));
  function toggleRow(id: string) {
    const next = chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id].slice(-MAX_COMPARE);
    router.set({ rows: next.length ? next.join(',') : null });
  }
  const compared = $derived(chosen.map((id) => byId.get(id)).filter((r): r is Row => !!r));

  // ---- the shortlist table ----
  const sortBy = $derived(metrics.includes(router.get('sort')) ? router.get('sort') : metrics[0]);
  const sorted = $derived.by(() => {
    const k = metrics.indexOf(sortBy);
    if (k < 0) return front;
    const sign = dirs[k] === 'min' ? 1 : -1;
    return [...front].sort((a, b) => sign * (a.values[k] - b.values[k]));
  });
  let showAll = $state(false);

  // checkpoints that go with a row, and the nearest ones of its run when none does
  const checkpointsAt = (r: StepRows): StepCheckpoint[] => runOf(r).checkpoints.filter((c) => c.row === r.step);
  function nearest(r: StepRows): StepCheckpoint | null {
    const list = runOf(r).checkpoints.filter((c) => c.step !== null);
    if (!list.length) return null;
    return list.reduce((a, b) => (Math.abs(b.step! - r.step) < Math.abs(a.step! - r.step) ? b : a));
  }
  const ckptLabel = (c: StepCheckpoint) => `${c.artifact} v${c.version ?? '?'}`;
  const openCheckpoint = (c: StepCheckpoint) =>
    router.go('artifacts', { art: `${c.project}|${c.artifact}|${c.version}`, cmp: null, tab: null });

  // ---- the scatter plot ----
  const axes = $derived(['step', ...metrics]);
  const ax = $derived(axes.includes(router.get('x')) ? router.get('x') : (metrics[0] ?? 'step'));
  const ay = $derived(
    axes.includes(router.get('y'))
      ? router.get('y')
      : metrics.length > 1
        ? metrics[1]
        : metrics[0] === ax
          ? 'step'
          : metrics[0],
  );
  const valueOn = (r: StepRows, axis: string) => (axis === 'step' ? r.step : r.values[metrics.indexOf(axis)]);
  const dirOn = (axis: string): Dir | null => (axis === 'step' ? null : dirs[metrics.indexOf(axis)]);
  let plotW = $state(800);
  const PH = 300;
  const PL = 62;
  const PR = 16;
  const PT = 12;
  const PB = 40;
  // The range of an axis: every shortlist row, and the other rows but the 10% furthest behind, so
  // the early steps of training do not squeeze the part where the choice is made.
  function axisRange(axis: string): [number, number] {
    const f = front.map((r) => valueOn(r, axis));
    const o = others.map((r) => valueOn(r, axis)).sort((a, b) => a - b);
    const d = dirOn(axis);
    if (!d || o.length < 20) return padded([...f, ...o]);
    const cut = d === 'max' ? o[Math.floor(o.length * 0.1)] : o[Math.ceil(o.length * 0.9) - 1];
    return padded([...f, ...o.filter((v) => (d === 'max' ? v >= cut : v <= cut))]);
  }
  const xr = $derived(axisRange(ax));
  const yr = $derived(axisRange(ay));
  const inside = (r: StepRows) => {
    const [x, y] = [valueOn(r, ax), valueOn(r, ay)];
    return x >= xr[0] && x <= xr[1] && y >= yr[0] && y <= yr[1];
  };
  const offPlot = $derived(others.filter((r) => !inside(r)).length);
  // better is to the right and up: an axis where lower is better is flipped
  const X = (v: number) => {
    const t = (v - xr[0]) / (xr[1] - xr[0]);
    return PL + (dirOn(ax) === 'min' ? 1 - t : t) * (plotW - PL - PR);
  };
  const Y = (v: number) => {
    const t = (v - yr[0]) / (yr[1] - yr[0]);
    return PT + (dirOn(ay) === 'min' ? t : 1 - t) * (PH - PT - PB);
  };
  const edge = $derived.by(() => {
    const dx = dirOn(ax);
    const dy = dirOn(ay);
    if (!dx || !dy || ax === ay) return '';
    const e = edge2d(
      front.map((r): [number, number] => [valueOn(r, ax), valueOn(r, ay)]),
      dx,
      dy,
    );
    return e.map(([x, y], i) => `${i ? 'L' : 'M'}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join('');
  });
  let hover = $state<Row | null>(null);

  // ---- compare: each run's curves, and the config keys that differ ----
  const comparedKeys = $derived([...new Set(compared.map((r) => r.key))]);
  let curves = $state<Record<string, Record<string, { x: Float64Array; y: Float64Array }>>>({});
  let config = $state<{ keys: string[]; values: Record<string, Record<string, unknown>> } | null>(null);
  const compareQuery = $derived(tab === 'compare' ? JSON.stringify([comparedKeys, metrics]) : '');
  $effect(() => {
    if (!compareQuery) return;
    const [keys, ms] = JSON.parse(compareQuery) as [string[], string[]];
    if (!keys.length) return;
    const ctrl = new AbortController();
    Promise.all(
      ms.map((metric) =>
        api.chart({ runs: keys, metric, x: 'step', points: 160, signal: ctrl.signal }).then((d) => {
          const per: Record<string, { x: Float64Array; y: Float64Array }> = {};
          for (const s of d.series) if (s.runs.length === 1) per[s.runs[0]] = { x: s.x, y: s.y };
          return [metric, per] as const;
        }),
      ),
    )
      .then((list) => (curves = Object.fromEntries(list)))
      .catch(() => {});
    api
      .sweepKeys(keys)
      .then((c) => (config = c))
      .catch(() => (config = null));
    return () => ctrl.abort();
  });
  const configDiff = $derived(
    config
      ? config.keys.filter((k) => new Set(comparedKeys.map((key) => JSON.stringify(config!.values[k]?.[key]))).size > 1)
      : [],
  );
  function spark(key: string, metric: string, step: number, w = 120, h = 30) {
    const c = curves[metric]?.[key];
    if (!c || c.x.length < 2) return null;
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of c.y) if (Number.isFinite(v)) [lo, hi] = [Math.min(lo, v), Math.max(hi, v)];
    if (!(hi > lo)) hi = lo + 1;
    const x0 = c.x[0];
    const x1 = c.x[c.x.length - 1] || x0 + 1;
    const sx = (v: number) => 1 + ((v - x0) / (x1 - x0 || 1)) * (w - 2);
    const sy = (v: number) => h - 3 - ((v - lo) / (hi - lo)) * (h - 6);
    let d = '';
    c.x.forEach((x, i) => {
      if (Number.isFinite(c.y[i])) d += `${d ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(c.y[i]).toFixed(1)}`;
    });
    return { d, at: sx(step), w, h };
  }

  // ---- picking ----
  async function pickRow(r: Row) {
    const run = runOf(r);
    const own = checkpointsAt(r);
    const near = own.length ? null : nearest(r);
    const options = [...own, ...(near ? [near] : [])].map((c) => ({
      value: `${c.artifact}\n${c.version}`,
      label: `${ckptLabel(c)}${c.step !== null && c.step !== r.step ? ` (step ${c.step.toLocaleString()})` : ''}`,
    }));
    const existing = shownPicks.find((p) => p.key === r.key && p.step === r.step);
    const fields = [
      {
        label: 'Why this step',
        value: existing?.note ?? '',
        placeholder: 'Best accuracy under the latency limit; later steps get worse calibration',
      },
      ...(options.length
        ? [
            {
              label: 'Checkpoint to go with it',
              options: [...options, { value: '', label: 'None' }],
              value: options[0].value,
            },
          ]
        : []),
    ];
    const summary = metrics.map((m, k) => `${m} ${fmtNum(r.values[k])}`).join(' · ');
    const got = await ask(`Pick ${run.name} at step ${r.step.toLocaleString()}`, fields, {
      message: `${summary}. Saved in ${run.project}/picks.json, with the scalars and which way was better for each.`,
      confirm: existing ? 'Save pick' : 'Pick step',
    });
    if (!got) return;
    const [artifact, version] = (got[1] ?? '').split('\n');
    try {
      await api.savePick(run.project, {
        id: existing?.id,
        run: run.id,
        run_name: run.name,
        step: r.step,
        note: got[0],
        metrics: Object.fromEntries(metrics.map((m, k) => [m, r.values[k]])),
        directions: Object.fromEntries(metrics.map((m, k) => [m, dirs[k]])),
        checkpoint: artifact ? { artifact, version: version ? Number(version) : null } : null,
      });
      await loadPicks();
    } catch (e) {
      await notice('The pick was not saved', (e as Error).message);
    }
  }
  async function editNote(p: SavedPick) {
    const got = await ask('Why this step', [{ label: 'Note', value: p.note }], { confirm: 'Save' });
    if (got === null) return;
    await api.savePick(p.project, { ...p, note: got[0] }).catch((e) => notice('Not saved', e.message));
    await loadPicks();
  }
  async function removePick(p: SavedPick) {
    if (
      !(await confirmAction('Remove this pick?', `${p.run_name || p.run} at step ${p.step.toLocaleString()}`, {
        danger: true,
        confirm: 'Remove',
      }))
    )
      return;
    await api.deletePick(p.project, p.id).catch((e) => notice('Not removed', e.message));
    await loadPicks();
  }
</script>

<div class="toolbar">
  <div class="seg" aria-label="Select page view">
    <button aria-pressed={tab === 'shortlist'} onclick={() => router.set({ tab: null })}
      >Shortlist{#if data}<span class="count">{data.front_count}</span>{/if}</button
    >
    <button aria-pressed={tab === 'compare'} onclick={() => router.set({ tab: 'compare' })}
      >Compare<span class="count">{compared.length}</span></button
    >
    <button aria-pressed={tab === 'picks'} onclick={() => router.set({ tab: 'picks' })}
      >Picks<span class="count">{shownPicks.length}</span></button
    >
  </div>
  <span class="muted hint">Which run at which step to take forward, when runs win on different scalars.</span>
</div>

{#if tab === 'picks'}
  <div class="card list">
    {#if !shownPicks.length}
      <div class="empty">No picks yet. Compare a few steps from the shortlist and choose <b>Pick this step</b>.</div>
    {:else}
      <table>
        <thead
          ><tr
            ><th class="l">Run</th><th>Step</th><th class="l">Scalars when picked</th><th class="l">Checkpoint</th><th
              class="l">Why</th
            ><th class="l">When</th><th></th></tr
          ></thead
        >
        <tbody>
          {#each [...shownPicks].reverse() as p (p.project + p.id)}
            <tr>
              <td class="l"
                ><span class="flag"><Icon name="flag" size={13} /></span>
                <span class="mono">{p.run_name || p.run}</span>
                {#if projects.length > 1}<span class="faint"> · {p.project}</span>{/if}
                {#if !p.key}<span class="chip chip-warn sm">run not found</span>{/if}</td
              >
              <td class="mono">{p.step.toLocaleString()}</td>
              <td class="l mono small"
                >{#each Object.entries(p.metrics) as [m, v] (m)}<span class="kv"
                    >{m} {p.directions[m] ? arrow(p.directions[m]) : ''} <b>{fmtNum(v)}</b></span
                  >{/each}</td
              >
              <td class="l"
                >{#if p.checkpoint}<button
                    class="chip"
                    onclick={() =>
                      router.go('artifacts', {
                        art: `${p.project}|${p.checkpoint!.artifact}|${p.checkpoint!.version}`,
                        cmp: null,
                        tab: null,
                      })}
                    ><Icon name="artifact" size={12} /> {p.checkpoint.artifact} v{p.checkpoint.version ?? '?'}</button
                  >{:else}<span class="faint">None</span>{/if}</td
              >
              <td class="l note">{p.note || '—'}</td>
              <td class="l faint">{fmtDate(p.edited ?? p.created)}</td>
              <td class="actions">
                {#if p.key}<button
                    class="btn btn-ghost sm"
                    onclick={() => router.go('charts', { sel: p.key!, tab: null })}>Charts</button
                  >{/if}
                <button class="btn btn-ghost sm" onclick={() => editNote(p)}>Edit</button>
                <button class="btn btn-ghost sm" aria-label="Remove pick" onclick={() => removePick(p)}
                  ><Icon name="trash" size={14} /></button
                >
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{:else if tab !== 'compare'}
  <div class="body">
    <aside class="card crit">
      <div class="row"><span class="label">Better means</span></div>
      {#if !metrics.length}
        <p class="faint small">Choose the scalars that matter for the decision, such as accuracy, loss or latency.</p>
      {/if}
      {#each metrics as m, i (m)}
        {@const g = dirInfo[i]}
        {@const n = data?.coverage[m]}
        <div class="mrow">
          <div class="mname">
            <span class="mono trunc" title={m}>{m}</span>
            {#if n !== undefined}<span class="cov" class:part={n < runs.length}>{n} of {runs.length} runs</span>{/if}
          </div>
          <button
            class="dir"
            class:guess={!g.set && !overrides[i]}
            class:mixed={!!g.mixed && !overrides[i]}
            title={g.mixed && !overrides[i]
              ? `The projects shown disagree on ${m}. Click to choose for this view.`
              : `${dirs[i] === 'min' ? 'Lower' : 'Higher'} is better${g.set ? '' : ' (a guess from the name)'}. Click to flip it for this view.`}
            aria-label="Direction of {m}: {dirs[i]}"
            onclick={() => flip(i)}>{g.mixed && !overrides[i] ? '↕' : arrow(dirs[i])}</button
          >
          <button class="x" aria-label="Remove {m}" onclick={() => removeMetric(m)}><Icon name="x" size={13} /></button>
        </div>
      {/each}
      <ScalarPicker
        metrics={allMetrics.filter((m) => !metrics.includes(m))}
        value=""
        label={metrics.length ? 'Add a scalar' : 'Choose a scalar'}
        onpick={addMetric}
      />
      {#if !metrics.length && suggestions.length}
        <div class="suggest">
          {#each suggestions as s (s)}<button class="chip mono" onclick={() => addMetric(s)}>+ {s}</button>{/each}
        </div>
      {/if}
      {#if metrics.length}
        <p class="note-line">
          <Icon name="info" size={14} /><span
            >A step counts only when {metrics.length === 1 ? 'it was' : `all ${metrics.length} were`} logged at it, with a
            finite value.</span
          >
        </p>
      {/if}
      {#if data}
        <div class="funnel">
          <div><b>{data.complete.toLocaleString()}</b> complete steps in {data.runs.length} runs</div>
          <div><b>{data.front_count.toLocaleString()}</b> not beaten on every scalar</div>
        </div>
      {/if}
    </aside>

    <div class="main">
      {#if !runs.length}
        <div class="card empty">No runs with scalars. Pick a project or loosen the query.</div>
      {:else if !metrics.length}
        <div class="card empty">
          <h3>Choose what “best” means</h3>
          <p>
            Add the scalars you would judge a model by, and say which way is better for each. Every run at every step
            where all of them were logged is scored, and the steps no other step beats on every scalar make the
            shortlist. You then compare a few side by side and pick one, with a note saying why.
          </p>
        </div>
      {:else if error}
        <div class="card empty err">{error}</div>
      {:else if !data}
        <div class="card empty">{loading ? 'Scoring steps…' : ''}</div>
      {:else}
        <div class="card plot">
          <div class="chead">
            <h2>Trade-off</h2>
            <span class="muted small"
              >Each dot is a run at a step. Big dots are on the shortlist; click one to compare it.</span
            >
            <span class="grow"></span>
            <label class="axis"
              ><span class="faint">x</span>
              <select class="input sm mono" value={ax} onchange={(e) => router.set({ x: e.currentTarget.value })}>
                {#each axes as a (a)}<option value={a}>{a}{a === 'step' ? '' : ` ${arrow(dirOn(a)!)}`}</option>{/each}
              </select></label
            >
            <label class="axis"
              ><span class="faint">y</span>
              <select class="input sm mono" value={ay} onchange={(e) => router.set({ y: e.currentTarget.value })}>
                {#each axes as a (a)}<option value={a}>{a}{a === 'step' ? '' : ` ${arrow(dirOn(a)!)}`}</option>{/each}
              </select></label
            >
          </div>
          {#if !data.complete}
            <div class="empty">
              No run logged {metrics.length === 1 ? 'this scalar' : 'all of these scalars at the same step'}.
            </div>
          {:else}
            <div class="svgwrap" bind:clientWidth={plotW}>
              <svg width={plotW} height={PH} role="img" aria-label="Trade-off between {ax} and {ay}">
                {#each niceTicks(xr[0], xr[1], Math.max(3, Math.floor(plotW / 110))) as t (t)}
                  <line class="grid" x1={X(t)} x2={X(t)} y1={PT} y2={PH - PB} />
                  <text class="tick" x={X(t)} y={PH - PB + 15} text-anchor="middle">{fmtAxis(t)}</text>
                {/each}
                {#each niceTicks(yr[0], yr[1], 5) as t (t)}
                  <line class="grid" x1={PL} x2={plotW - PR} y1={Y(t)} y2={Y(t)} />
                  <text class="tick" x={PL - 6} y={Y(t) + 4} text-anchor="end">{fmtAxis(t)}</text>
                {/each}
                <text class="axt" x={(PL + plotW - PR) / 2} y={PH - 6} text-anchor="middle"
                  >{ax}{dirOn(ax) ? ` ${arrow(dirOn(ax)!)} better →` : ''}</text
                >
                <text class="axt" transform="translate(13 {(PT + PH - PB) / 2}) rotate(-90)" text-anchor="middle"
                  >{ay}{dirOn(ay) ? ` ${arrow(dirOn(ay)!)} better →` : ''}</text
                >
                {#each others.filter(inside) as r (r.id)}
                  <circle class="pt" cx={X(valueOn(r, ax))} cy={Y(valueOn(r, ay))} r="2.6" style="fill:{color(r)}" />
                {/each}
                {#if edge}<path class="edge" d={edge} />{/if}
                {#each front as r (r.id)}
                  {@const cx = X(valueOn(r, ax))}
                  {@const cy = Y(valueOn(r, ay))}
                  {#if pickedIds.has(r.id)}<circle class="ring pick" {cx} {cy} r="11" />{/if}
                  {#if chosen.includes(r.id)}<circle class="ring" {cx} {cy} r="9" />{/if}
                  <circle
                    class="fp"
                    {cx}
                    {cy}
                    r="5.5"
                    style="fill:{color(r)}"
                    role="button"
                    tabindex="-1"
                    aria-label="{runOf(r).name} at step {r.step}"
                    onpointerenter={() => (hover = r)}
                    onpointerleave={() => (hover = null)}
                    onclick={() => toggleRow(r.id)}
                    onkeydown={(e) => e.key === 'Enter' && toggleRow(r.id)}
                  />
                {/each}
              </svg>
              {#if hover}
                {@const hx = X(valueOn(hover, ax))}
                <div
                  class="tip"
                  style="top:{Y(valueOn(hover, ay)) + 12}px;{hx > plotW / 2
                    ? `right:${plotW - hx + 12}px`
                    : `left:${hx + 12}px`}"
                >
                  <div class="th">
                    <i style="background:{color(hover)}"></i><span class="mono">{runOf(hover).name}</span>
                    <span class="faint">step {hover.step.toLocaleString()}</span>
                  </div>
                  {#each metrics as m, k (m)}
                    <div class="tr">
                      <span class="mono faint">{m}</span><span
                        class="mono"
                        class:best={best[k] >= 0 && front[best[k]] === hover}>{fmtNum(hover.values[k])}</span
                      >
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
            <div class="legend">
              {#each data.runs.slice(0, 16) as r, i (r.key)}
                <span><i style="background:{seriesVar(i)}"></i><span class="mono">{r.name}</span></span>
              {/each}
              {#if data.runs.length > 16}<span class="faint">+{data.runs.length - 16} more</span>{/if}
              <span class="grow"></span>
              {#if offPlot}<span class="faint">{offPlot.toLocaleString()} steps far behind are off the plot</span>{/if}
              {#if edge}<span class="faint"><i class="dash"></i>trade-off edge on these two axes</span>{/if}
            </div>
          {/if}
        </div>

        <div class="card list">
          <div class="chead">
            <h2>Shortlist</h2>
            <span class="muted small"
              >{data.front_count.toLocaleString()} step{data.front_count === 1 ? '' : 's'} that no other step beats on
              {metrics.length === 1 ? 'this scalar' : `all ${metrics.length} scalars`}, out of {data.complete.toLocaleString()}.</span
            >
          </div>
          {#if front.length}
            <div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th></th><th class="l">Run</th><th>Step</th>
                    {#each metrics as m, k (m)}
                      <th
                        ><button class="sort mono" class:on={sortBy === m} onclick={() => router.set({ sort: m })}
                          >{m} {arrow(dirs[k])}</button
                        ></th
                      >
                    {/each}
                    <th class="l">Checkpoints</th><th class="l"></th>
                  </tr>
                </thead>
                <tbody>
                  {#each showAll ? sorted : sorted.slice(0, SHOWN) as r (r.id)}
                    {@const ck = checkpointsAt(r)}
                    <tr class:chosen={chosen.includes(r.id)} class:picked={pickedIds.has(r.id)}>
                      <td
                        ><input
                          type="checkbox"
                          aria-label="Compare {runOf(r).name} at step {r.step}"
                          checked={chosen.includes(r.id)}
                          onchange={() => toggleRow(r.id)}
                        /></td
                      >
                      <td class="l"
                        ><i class="dot" style="background:{color(r)}"></i><span class="mono">{runOf(r).name}</span
                        >{#if projects.length > 1}<span class="faint"> · {runOf(r).project}</span>{/if}</td
                      >
                      <td class="mono">{r.step.toLocaleString()}</td>
                      {#each metrics as m, k (m)}
                        <td class="mono" class:best={front[best[k]] === r}>{fmtNum(r.values[k])}</td>
                      {/each}
                      <td class="l">
                        {#each ck as c (c.artifact + c.version)}
                          <button
                            class="chip ck"
                            title={c.exact
                              ? `Made at step ${c.step}`
                              : `Made after step ${c.step}: its step was not recorded`}
                            onclick={() => openCheckpoint(c)}><Icon name="artifact" size={11} /> {ckptLabel(c)}</button
                          >
                        {:else}
                          <span class="faint small">none</span>
                        {/each}
                      </td>
                      <td class="l tags">
                        {#if pickedIds.has(r.id)}<span class="badge pick"><Icon name="flag" size={11} /> picked</span
                          >{/if}
                        {#each metrics as m, k (m)}
                          {#if front[best[k]] === r}<span class="badge best" title="Best {m} on the shortlist"
                              >best {m.split('/').pop()}</span
                            >{/if}
                        {/each}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
            {#if sorted.length > SHOWN}
              <button class="btn btn-ghost more" onclick={() => (showAll = !showAll)}
                >{showAll ? 'Show fewer' : `Show all ${sorted.length.toLocaleString()}`}</button
              >
            {/if}
            {#if data.front_count > front.length}
              <p class="faint small pad">The first {front.length} by {metrics[0]} are listed.</p>
            {/if}
          {/if}
          {#if data.unranked.length}
            <details class="unranked">
              <summary>
                <b>Not ranked</b><span class="chip chip-warn sm"
                  >{data.unranked.length} run{data.unranked.length === 1 ? '' : 's'}</span
                >
                <span class="muted">A scalar is missing, so these runs cannot be compared fairly.</span>
              </summary>
              <ul>
                {#each data.unranked as u (u.run)}
                  <li>
                    <span class="mono">{u.name}</span>
                    {#if projects.length > 1}<span class="faint"> · {u.project}</span>{/if}
                    {#if u.missing.length}
                      never logs {#each u.missing as m, i (m)}{i ? ', ' : ''}<span class="mono">{m}</span>{/each}
                    {:else}
                      logs these scalars, but never at the same step
                    {/if}
                  </li>
                {/each}
              </ul>
              {#each metrics.filter((m) => data!.unranked.some((u) => u.missing.includes(m))) as m (m)}
                <button class="btn btn-ghost sm" onclick={() => removeMetric(m)}>Remove {m} to rank them</button>
              {/each}
            </details>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  {#if tab !== 'compare' && chosen.length}
    <div class="selbar">
      <span><b>{compared.length}</b> step{compared.length === 1 ? '' : 's'} chosen</span>
      <button class="btn" onclick={() => router.set({ rows: null })}>Clear</button>
      <button class="btn btn-primary" onclick={() => router.set({ tab: 'compare' })}
        ><Icon name="compare" size={14} /> Compare side by side</button
      >
    </div>
  {/if}
{/if}

{#if tab === 'compare'}
  {#if !compared.length}
    <div class="card empty">
      Choose steps to compare on the shortlist: tick their boxes, or click their dots on the plot.
      <button class="btn" onclick={() => router.set({ tab: null })}>Back to the shortlist</button>
    </div>
  {:else}
    <div class="card cmp" style="grid-template-columns: 190px repeat({compared.length}, minmax(180px, 1fr))">
      <div class="ch"><span class="label">{compared.length} step{compared.length === 1 ? '' : 's'}</span></div>
      {#each compared as r (r.id)}
        <div class="ch">
          <div class="nm">
            <i class="dot" style="background:{color(r)}"></i><span class="mono trunc">{runOf(r).name}</span>
            <span class="grow"></span>
            <button
              class="x"
              aria-label="Stop comparing {runOf(r).name} at step {r.step}"
              onclick={() => toggleRow(r.id)}><Icon name="x" size={13} /></button
            >
          </div>
          <div class="faint small">step {r.step.toLocaleString()} · {runOf(r).project}</div>
          <div class="tags">
            {#if pickedIds.has(r.id)}<span class="badge pick"><Icon name="flag" size={11} /> picked</span>{/if}
            {#if !r.front}<span class="badge">beaten on every scalar</span>{/if}
            {#each metrics as m, k (m)}
              {#if front[best[k]] === r}<span class="badge best">best {m.split('/').pop()}</span>{/if}
            {/each}
          </div>
        </div>
      {/each}

      <div class="grp label">
        Scalars at that step <span class="sub">· the dashed line marks the step on the whole run</span>
      </div>
      {#each metrics as m, k (m)}
        <div class="rh mono">{m} {arrow(dirs[k])}</div>
        {#each compared as r (r.id)}
          {@const top = compared.every((o) => !better(o.values[k], r.values[k], dirs[k]))}
          {@const sp = spark(r.key, m, r.step)}
          <div class="val">
            <span class="mono v" class:best={top && compared.length > 1}>{fmtNum(r.values[k])}</span>
            {#if sp}
              <svg width={sp.w} height={sp.h} aria-hidden="true"
                ><path d={sp.d} class="spark" style="stroke:{color(r)}" /><line
                  x1={sp.at}
                  x2={sp.at}
                  y1="0"
                  y2={sp.h}
                  class="at"
                /></svg
              >
            {/if}
            <span class="faint small"
              >#{rankOf(
                front.map((f) => f.values[k]),
                r.values[k],
                dirs[k],
              )} of {front.length}</span
            >
          </div>
        {/each}
      {/each}

      {#if configDiff.length}
        <div class="grp label">Config <span class="sub">· only the keys that differ</span></div>
        {#each configDiff.slice(0, 30) as key (key)}
          <div class="rh mono trunc" title={key}>{key}</div>
          {#each compared as r (r.id)}
            <div class="mono cfg trunc">{fmtValue(config?.values[key]?.[r.key])}</div>
          {/each}
        {/each}
      {/if}

      <div class="grp label">Checkpoints</div>
      <div class="rh">at that step</div>
      {#each compared as r (r.id)}
        {@const ck = checkpointsAt(r)}
        {@const near = ck.length ? null : nearest(r)}
        <div class="cks">
          {#each ck as c (c.artifact + c.version)}
            <button class="chip ck" onclick={() => openCheckpoint(c)}
              ><Icon name="artifact" size={11} /> {ckptLabel(c)}</button
            >
          {:else}
            <span class="faint small"
              >none{near ? ` · nearest is ${ckptLabel(near)} at step ${near.step!.toLocaleString()}` : ''}</span
            >
          {/each}
        </div>
      {/each}

      <div class="rh last"></div>
      {#each compared as r (r.id)}
        <div class="last">
          <button class="btn" class:picked={pickedIds.has(r.id)} onclick={() => pickRow(r)}
            ><Icon name="flag" size={14} /> {pickedIds.has(r.id) ? 'Edit pick' : 'Pick this step'}</button
          >
        </div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
  }
  .seg button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .count {
    font-size: 11px;
    font-weight: 600;
    border-radius: 9px;
    padding: 0 6px;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .hint,
  .muted {
    color: var(--muted);
  }
  .hint {
    font-size: 13px;
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12.5px;
  }
  .grow {
    flex: 1;
  }
  .trunc {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .label .sub,
  .sub {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    color: var(--faint);
  }
  .body {
    display: grid;
    grid-template-columns: 290px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  @media (max-width: 900px) {
    .body {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  .crit {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    position: sticky;
    top: 12px;
  }
  .crit .row {
    display: flex;
    align-items: center;
  }
  .mrow {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 6px 6px 10px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
  }
  .mname {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: 13px;
  }
  .cov {
    font-size: 11px;
    color: var(--faint);
  }
  .cov.part {
    color: var(--warn);
  }
  .dir {
    width: 30px;
    height: 26px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 700;
  }
  .dir.guess {
    background: var(--panel);
    border-style: dashed;
  }
  .dir.mixed {
    color: var(--warn);
    background: var(--warn-bg);
  }
  .x {
    border: 0;
    background: none;
    color: var(--faint);
    display: grid;
    place-items: center;
    padding: 2px;
  }
  .x:hover {
    color: var(--text);
  }
  .suggest {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .suggest .chip {
    cursor: pointer;
    color: var(--accent);
  }
  .note-line {
    display: flex;
    gap: 7px;
    font-size: 12.5px;
    color: var(--muted);
    margin: 4px 0 0;
    line-height: 1.45;
  }
  .note-line :global(svg) {
    flex: none;
    margin-top: 2px;
  }
  .funnel {
    border-top: 1px solid var(--border);
    margin-top: 6px;
    padding-top: 10px;
    font-size: 12.5px;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .funnel b {
    color: var(--text);
  }
  .main {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
  }
  .empty {
    padding: 28px;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.55;
  }
  .empty h3 {
    margin: 0 0 6px;
    color: var(--text);
  }
  .empty p {
    margin: 0;
    max-width: 70ch;
  }
  .empty.err {
    color: var(--err);
  }
  .plot {
    padding: 12px 14px 10px;
  }
  .chead {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .list .chead {
    padding: 12px 14px 6px;
  }
  h2 {
    font-size: 15px;
    margin: 0;
    font-weight: 600;
  }
  .axis {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .input.sm {
    height: 28px;
    font-size: 12.5px;
  }
  .svgwrap {
    position: relative;
    margin-top: 6px;
  }
  svg {
    display: block;
  }
  .grid {
    stroke: var(--grid);
  }
  .tick {
    font-size: 11px;
    fill: var(--faint);
    font-family: var(--mono);
  }
  .axt {
    font-size: 12px;
    fill: var(--muted);
    font-family: var(--mono);
  }
  .pt {
    opacity: 0.4;
  }
  .fp {
    stroke: var(--panel);
    stroke-width: 2;
    cursor: pointer;
  }
  .ring {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.8;
  }
  .ring.pick {
    stroke: var(--warn);
    stroke-dasharray: 3 2;
  }
  .edge {
    fill: none;
    stroke: var(--text);
    stroke-opacity: 0.35;
    stroke-dasharray: 4 3;
    stroke-width: 1.3;
  }
  .tip {
    position: absolute;
    z-index: 5;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
    padding: 7px 9px;
    font-size: 12px;
    pointer-events: none;
    min-width: 200px;
  }
  .th {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    margin-bottom: 3px;
  }
  .th i,
  .legend i,
  .dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
  }
  .dot {
    margin-right: 7px;
    vertical-align: -1px;
  }
  .tr {
    display: flex;
    justify-content: space-between;
    gap: 14px;
    line-height: 1.6;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 14px;
    font-size: 12px;
    color: var(--muted);
    align-items: center;
    margin-top: 4px;
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .legend .dash {
    width: 16px;
    height: 0;
    border-top: 1.5px dashed var(--muted);
    border-radius: 0;
  }
  .list {
    overflow: hidden;
  }
  .scroll {
    overflow-x: auto;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
  }
  th {
    font-weight: 550;
    color: var(--muted);
    text-align: right;
    font-size: 12px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  td {
    padding: 7px 10px;
    border-bottom: 1px solid var(--grid);
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  th.l,
  td.l {
    text-align: left;
  }
  td.note {
    white-space: normal;
    max-width: 40ch;
    color: var(--muted);
  }
  td.actions {
    white-space: nowrap;
  }
  .kv {
    margin-right: 12px;
  }
  .flag {
    display: inline-flex;
    color: var(--warn);
    vertical-align: -2px;
    margin-right: 4px;
  }
  tr.chosen td {
    background: var(--accent-soft);
  }
  tr.picked td {
    background: var(--warn-bg);
  }
  .best {
    color: var(--accent);
    font-weight: 650;
  }
  .sort {
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 12px;
    padding: 0;
    cursor: pointer;
  }
  .sort.on {
    color: var(--accent);
  }
  .chip.ck {
    height: 22px;
    font-size: 11.5px;
    cursor: pointer;
    margin-right: 4px;
    color: var(--text);
  }
  .chip.sm {
    height: 20px;
    font-size: 11px;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  td.tags {
    display: table-cell;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10.5px;
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    border-radius: 6px;
    padding: 1px 6px;
    margin-right: 4px;
    background: var(--panel-2);
    color: var(--muted);
  }
  .badge.best {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .badge.pick {
    background: var(--warn-bg);
    color: var(--warn);
  }
  .more {
    margin: 6px 8px;
  }
  .pad {
    padding: 0 14px;
  }
  .unranked {
    background: var(--panel-2);
    padding: 10px 14px;
    font-size: 13px;
  }
  .unranked summary {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
    flex-wrap: wrap;
  }
  .unranked ul {
    margin: 8px 0;
    padding-left: 20px;
    color: var(--muted);
    line-height: 1.7;
  }
  .selbar {
    position: sticky;
    bottom: 14px;
    align-self: center;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 8px 16px;
    border-radius: 12px;
    background: var(--text);
    color: var(--bg);
    font-size: 13px;
    box-shadow: 0 10px 30px -10px rgb(0 0 0 / 0.4);
    z-index: 4;
  }
  .selbar .btn:not(.btn-primary) {
    background: transparent;
    color: var(--bg);
    border-color: color-mix(in srgb, var(--bg) 30%, transparent);
  }
  .selbar .btn-primary {
    background: var(--bg);
    color: var(--text);
    border-color: var(--bg);
  }
  .cmp {
    display: grid;
    overflow-x: auto;
  }
  .cmp > div {
    padding: 9px 14px;
    border-bottom: 1px solid var(--grid);
    min-width: 0;
  }
  .cmp .ch {
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 4px;
    justify-content: flex-end;
  }
  .nm {
    display: flex;
    align-items: center;
    font-weight: 600;
    font-size: 14px;
  }
  .cmp .grp {
    grid-column: 1 / -1;
    background: var(--panel-2);
    border-bottom: 1px solid var(--border);
    padding: 7px 14px;
  }
  .rh {
    color: var(--muted);
    font-size: 12.5px;
    align-self: center;
  }
  .val {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .val .v {
    min-width: 62px;
  }
  .spark {
    fill: none;
    stroke-width: 1.4;
  }
  .at {
    stroke: var(--text);
    stroke-opacity: 0.5;
    stroke-dasharray: 2 2;
  }
  .cfg {
    font-size: 12.5px;
  }
  .cks {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
  }
  .cmp .last {
    border-bottom: 0;
    padding: 12px 14px;
  }
  .btn.sm {
    height: 28px;
    padding: 0 9px;
    font-size: 12.5px;
  }
  .btn.picked {
    background: var(--warn-bg);
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 45%, transparent);
  }
</style>
