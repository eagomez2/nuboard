<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import ScalarPicker from '../components/ScalarPicker.svelte';
  import { api, type SavedPick, type StepCheckpoint, type StepRows, type StepsResult } from '../lib/api';
  import { seriesVar } from '../lib/colors';
  import { ask, confirmAction, notice } from '../lib/dialog.svelte';
  import { directionOf } from '../lib/directions.svelte';
  import { FullScreen } from '../lib/fullscreen.svelte';
  import { fmtAxis, fmtDate, fmtNum, fmtValue, tailName } from '../lib/format';
  import { onLive } from '../lib/live';
  import { addSnapshotToReport } from '../lib/reports.svelte';
  import { router } from '../lib/router.svelte';
  import { bestIndex, better, edge2d, niceTicks, padded, rankOf, rowId, type Dir } from '../lib/selection';
  import { svgToPng } from '../lib/snapshot';
  import { app } from '../lib/state.svelte';

  // The Shortlist page: which run at which step to take forward, when runs win on different scalars.
  // A row is a run at a step where every chosen scalar was logged; the shortlist holds the rows no
  // other row beats on every scalar (the server finds it, see nuboard/selection.py). Rows can be
  // compared side by side and picked with a note, saved in the project's picks.json.
  // URL: `m` the scalars, `dirs` this view's own direction of each (empty: the project's), `tx` and
  // `ty` the scatter axes, `rows` the rows to compare, `order` the shortlist's column, `pane` the
  // tab. Names other pages use (`x`, `sort`, `tab`) are avoided, as the URL is kept across pages.

  const MAX_COMPARE = 6;
  const SHOWN = 100; // shortlist rows shown before "Show all"

  const runs = $derived(app.visibleRuns().filter((r) => r.metric_count > 0));
  const runKeys = $derived(runs.map((r) => r.key));
  const projects = $derived([...new Set(runs.map((r) => r.project))].sort());
  const allMetrics = $derived(app.runs?.metrics ?? []);
  const tab = $derived(router.get('pane', 'shortlist'));

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
  // the scalars a shortlisted step is best on, for its badge
  const bestOn = (r: StepRows) => metrics.filter((_, k) => front[best[k]] === r);

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
  // For each compared step, the scalars it is best (or worst) on among the steps compared, as the
  // bold values show; a scalar on which all of them are equal counts for none.
  function standing(worst: boolean): string[][] {
    return compared.map((r) =>
      metrics.filter((_, k) => {
        if (compared.length < 2 || compared.every((o) => o.values[k] === r.values[k])) return false;
        return compared.every(
          (o) => !better(worst ? r.values[k] : o.values[k], worst ? o.values[k] : r.values[k], dirs[k]),
        );
      }),
    );
  }
  const wins = $derived(standing(false));
  const losses = $derived(standing(true));

  // ---- the shortlist table ----
  const sortBy = $derived(metrics.includes(router.get('order')) ? router.get('order') : metrics[0]);
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
  const ax = $derived(axes.includes(router.get('tx')) ? router.get('tx') : (metrics[0] ?? 'step'));
  const ay = $derived(
    axes.includes(router.get('ty'))
      ? router.get('ty')
      : metrics.length > 1
        ? metrics[1]
        : metrics[0] === ax
          ? 'step'
          : metrics[0],
  );
  const valueOn = (r: StepRows, axis: string) => (axis === 'step' ? r.step : r.values[metrics.indexOf(axis)]);
  const dirOn = (axis: string): Dir | null => (axis === 'step' ? null : dirs[metrics.indexOf(axis)]);
  let plotW = $state(800);
  let innerHeight = $state(900);
  const fs = new FullScreen();
  onMount(() => fs.listen());
  const PH = $derived(fs.on ? Math.max(300, innerHeight - 170) : 300);
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
  // The zoomed ranges, in data units. They belong to the axes and directions they were set on, so
  // changing either shows the whole plot again.
  const zoomKey = $derived(JSON.stringify([ax, ay, dirOn(ax), dirOn(ay)]));
  let zoom = $state<{ key: string; x: [number, number]; y: [number, number] } | null>(null);
  const zoomed = $derived(zoom?.key === zoomKey ? zoom : null);
  const xr = $derived(zoomed?.x ?? axisRange(ax));
  const yr = $derived(zoomed?.y ?? axisRange(ay));
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
  // the value at a pixel, the inverse of X and Y
  const xAt = (px: number) => {
    const t = (px - PL) / (plotW - PL - PR);
    return xr[0] + (dirOn(ax) === 'min' ? 1 - t : t) * (xr[1] - xr[0]);
  };
  const yAt = (py: number) => {
    const t = (py - PT) / (PH - PT - PB);
    return yr[0] + (dirOn(ay) === 'min' ? t : 1 - t) * (yr[1] - yr[0]);
  };
  const span = (a: number, b: number): [number, number] => (a < b ? [a, b] : [b, a]);
  function setZoom(x0: number, x1: number, y0: number, y1: number) {
    zoom = { key: zoomKey, x: span(xAt(x0), xAt(x1)), y: span(yAt(y0), yAt(y1)) };
  }
  const inPlot = (px: number, py: number) => px >= PL && px <= plotW - PR && py >= PT && py <= PH - PB;

  let hover = $state<Row | null>(null);
  // the scalars the tooltip lists: the two on the axes first, then the others, at most TIP_MAX
  const TIP_MAX = 6;
  const tipCols = $derived(
    [...new Set([ax, ay, ...metrics])]
      .map((m) => metrics.indexOf(m))
      .filter((k) => k >= 0)
      .slice(0, TIP_MAX),
  );
  let legendRun = $state<number | null>(null);
  // the run whose dots stand out: the one under the cursor, on the plot or in the legend
  const litRun = $derived(hover ? hover.run : legendRun);
  /** The dot nearest the cursor: a shortlist dot within 14px, else another within 8px. */
  function dotAt(px: number, py: number): Row | null {
    const find = (rows: Row[], radius: number) => {
      let best: Row | null = null;
      let bd = radius * radius;
      for (const r of rows) {
        const x = X(valueOn(r, ax));
        const y = Y(valueOn(r, ay));
        if (!inPlot(x, y)) continue;
        const d = (x - px) ** 2 + (y - py) ** 2;
        if (d < bd) [best, bd] = [r, d];
      }
      return best;
    };
    return find(front, 14) ?? find(others, 8);
  }

  // Drag draws a box to zoom into; Shift + drag pans; a click without a drag compares the dot.
  let drag = $state<{ mode: 'box' | 'pan'; x0: number; y0: number; x1: number; y1: number } | null>(null);
  let dragStart: { x: [number, number]; y: [number, number] } = { x: [0, 1], y: [0, 1] };
  const pos = (e: PointerEvent | WheelEvent) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  function plotDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const [x, y] = pos(e);
    (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
    drag = { mode: e.shiftKey ? 'pan' : 'box', x0: x, y0: y, x1: x, y1: y };
    dragStart = { x: [...xr], y: [...yr] };
  }
  function plotMove(e: PointerEvent) {
    const [x, y] = pos(e);
    if (!drag) {
      hover = inPlot(x, y) ? dotAt(x, y) : null;
      return;
    }
    drag = { ...drag, x1: x, y1: y };
    if (drag.mode === 'pan') {
      hover = null;
      const w = plotW - PL - PR;
      const h = PH - PT - PB;
      const sx = (dirOn(ax) === 'min' ? -1 : 1) * ((x - drag.x0) / w) * (dragStart.x[1] - dragStart.x[0]);
      const sy = (dirOn(ay) === 'min' ? 1 : -1) * ((y - drag.y0) / h) * (dragStart.y[1] - dragStart.y[0]);
      zoom = {
        key: zoomKey,
        x: [dragStart.x[0] - sx, dragStart.x[1] - sx],
        y: [dragStart.y[0] - sy, dragStart.y[1] - sy],
      };
    }
  }
  function plotUp() {
    const d = drag;
    drag = null;
    if (!d) return;
    const moved = Math.abs(d.x1 - d.x0) > 5 || Math.abs(d.y1 - d.y0) > 5;
    if (d.mode === 'box' && moved) {
      const cx = (v: number) => Math.min(Math.max(v, PL), plotW - PR);
      const cy = (v: number) => Math.min(Math.max(v, PT), PH - PB);
      if (Math.abs(d.x1 - d.x0) > 5 && Math.abs(d.y1 - d.y0) > 5) setZoom(cx(d.x0), cx(d.x1), cy(d.y0), cy(d.y1));
    } else if (!moved && hover) toggleRow(hover.id);
  }
  /** Ctrl/⌘ or Alt + wheel (or a trackpad pinch) zooms around the cursor; Shift + wheel pans along x. */
  function plotWheel(e: WheelEvent) {
    const zooming = e.ctrlKey || e.metaKey || e.altKey;
    if (!zooming && !e.shiftKey) return;
    e.preventDefault();
    const delta = (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1) * (e.deltaY || e.deltaX);
    if (zooming) {
      const [px, py] = pos(e);
      const f = Math.min(Math.max(Math.exp(delta * 0.002), 0.5), 2);
      const [cx, cy] = [xAt(px), yAt(py)];
      zoom = {
        key: zoomKey,
        x: [cx - (cx - xr[0]) * f, cx + (xr[1] - cx) * f],
        y: [cy - (cy - yr[0]) * f, cy + (yr[1] - cy) * f],
      };
    } else {
      const shift = (xr[1] - xr[0]) * Math.min(Math.max(delta * 0.001, -0.25), 0.25);
      zoom = { key: zoomKey, x: [xr[0] + shift, xr[1] + shift], y: [...yr] };
    }
  }

  let plotSvg = $state<SVGSVGElement>();
  async function plotToReport() {
    const project = runs[0]?.project ?? router.get('project');
    if (!plotSvg || !project) return;
    const png = await svgToPng(plotSvg, `${ay} against ${ax}`);
    if (fs.on) await fs.toggle(); // dialogs are not shown over a full-screen element
    await addSnapshotToReport(project, png, `Trade-off between ${ax} and ${ay}`, {
      page: 'select',
      params: { ...router.params },
    });
  }

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
              label: 'Artifact to go with it',
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

<svelte:window bind:innerHeight />

<div class="toolbar">
  <div class="seg" aria-label="Shortlist page view">
    <button aria-pressed={tab === 'shortlist'} onclick={() => router.set({ pane: null })}
      >Candidates{#if data}<span class="count">{data.front_count}</span>{/if}</button
    >
    <button aria-pressed={tab === 'compare'} onclick={() => router.set({ pane: 'compare' })}
      >Compare<span class="count">{compared.length}</span></button
    >
    <button aria-pressed={tab === 'picks'} onclick={() => router.set({ pane: 'picks' })}
      >Picks<span class="count">{shownPicks.length}</span></button
    >
  </div>
  <span class="muted hint">Which run at which step to take forward, when runs win on different scalars.</span>
</div>

{#if tab === 'picks'}
  <div class="card list">
    {#if !shownPicks.length}
      <div class="empty">No picks yet. Compare a few of the candidates and choose <b>Pick this step</b>.</div>
    {:else}
      <table>
        <thead
          ><tr
            ><th class="l">Run</th><th>Step</th><th class="l">Scalars when picked</th><th class="l">Artifact</th><th
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
                >{#each Object.entries(p.metrics) as [m, v] (m)}<span class="kv" title={m}
                    >{tailName(m, 30)} {p.directions[m] ? arrow(p.directions[m]) : ''} <b>{fmtNum(v)}</b></span
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
                    class="btn btn-ghost sm icon-btn"
                    title="Open this run in Charts"
                    aria-label="Open {p.run_name || p.run} in Charts"
                    onclick={() =>
                      router.go('charts', { sel: p.key!, metric: Object.keys(p.metrics)[0] ?? null, tab: null })}
                    ><Icon name="charts" size={14} /></button
                  >{/if}
                <button
                  class="btn btn-ghost sm icon-btn"
                  title="Edit the note and artifact"
                  aria-label="Edit pick"
                  onclick={() => editNote(p)}><Icon name="edit" size={14} /></button
                >
                <button
                  class="btn btn-ghost sm icon-btn"
                  title="Remove this pick"
                  aria-label="Remove pick"
                  onclick={() => removePick(p)}><Icon name="trash" size={14} /></button
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
            <span class="mono trunc" title={m}>{tailName(m, 21)}</span>
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
          {#each suggestions as s (s)}<button class="chip mono" title={s} onclick={() => addMetric(s)}
              >+<span class="tail"><span dir="ltr">{s}</span></span></button
            >{/each}
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
            where all of them were logged is scored, and the steps no other step beats on every scalar are the
            candidates. You then compare a few side by side and pick one, with a note saying why.
          </p>
        </div>
      {:else if error}
        <div class="card empty err">{error}</div>
      {:else if !data}
        <div class="card empty">{loading ? 'Scoring steps…' : ''}</div>
      {:else}
        <div class="card plot" class:full={fs.on} bind:this={fs.el}>
          <div class="chead">
            <h2>Trade-off</h2>
            <span class="grow"></span>
            <span class="axis"
              ><span class="faint">x</span>
              <ScalarPicker
                metrics={axes}
                value={ax}
                size="sm"
                ariaLabel="X axis"
                onpick={(m) => router.set({ tx: m })}
              /></span
            >
            <span class="axis"
              ><span class="faint">y</span>
              <ScalarPicker
                metrics={axes}
                value={ay}
                size="sm"
                ariaLabel="Y axis"
                onpick={(m) => router.set({ ty: m })}
              /></span
            >
            {#if zoomed}<button class="btn" onclick={() => (zoom = null)}>Reset zoom</button>{/if}
            <button
              class="btn btn-ghost icon-btn"
              title="Add this plot to a report"
              aria-label="Add the trade-off plot to a report"
              disabled={!data.complete}
              onclick={plotToReport}><Icon name="bookmark" size={15} /></button
            >
            <button
              class="btn btn-ghost icon-btn"
              title={fs.on ? 'Exit full screen (Esc)' : 'Full screen'}
              aria-label={fs.on ? 'Exit full screen' : 'Full screen'}
              aria-pressed={fs.on}
              onclick={() => fs.toggle()}><Icon name={fs.on ? 'shrink' : 'expand'} size={15} /></button
            >
          </div>
          <p class="muted small sub">
            Each dot is a run at a step; big dots are candidates. Click a dot to compare it, drag to zoom, Shift + drag
            to pan, double-click to see it all.
          </p>
          {#if !data.complete}
            <div class="empty">
              No run logged {metrics.length === 1 ? 'this scalar' : 'all of these scalars at the same step'}.
            </div>
          {:else}
            <div class="svgwrap" bind:clientWidth={plotW}>
              <svg
                bind:this={plotSvg}
                width={plotW}
                height={PH}
                role="application"
                aria-label="Trade-off between {ax} and {ay}"
                class:panning={drag?.mode === 'pan'}
                class:pointing={!!hover && !drag}
                onpointerdown={plotDown}
                onpointermove={plotMove}
                onpointerup={plotUp}
                onpointercancel={() => (drag = null)}
                onpointerleave={() => !drag && (hover = null)}
                ondblclick={() => (zoom = null)}
                onwheel={plotWheel}
              >
                <defs
                  ><clipPath id="tradeoff-clip"
                    ><rect x={PL} y={PT} width={Math.max(0, plotW - PL - PR)} height={PH - PT - PB} /></clipPath
                  ></defs
                >
                {#each niceTicks(xr[0], xr[1], Math.max(3, Math.floor(plotW / 110))) as t (t)}
                  <line class="grid" x1={X(t)} x2={X(t)} y1={PT} y2={PH - PB} />
                  <text class="tick" x={X(t)} y={PH - PB + 15} text-anchor="middle">{fmtAxis(t)}</text>
                {/each}
                {#each niceTicks(yr[0], yr[1], 5) as t (t)}
                  <line class="grid" x1={PL} x2={plotW - PR} y1={Y(t)} y2={Y(t)} />
                  <text class="tick" x={PL - 6} y={Y(t) + 4} text-anchor="end">{fmtAxis(t)}</text>
                {/each}
                <text class="axt" x={(PL + plotW - PR) / 2} y={PH - 6} text-anchor="middle"
                  >{tailName(ax, Math.max(12, Math.floor((plotW - PL - PR) / 7.2) - 12))}{dirOn(ax)
                    ? ` ${arrow(dirOn(ax)!)} better →`
                    : ''}<title>{ax}</title></text
                >
                <text class="axt" transform="translate(13 {(PT + PH - PB) / 2}) rotate(-90)" text-anchor="middle"
                  >{tailName(ay, Math.max(12, Math.floor((PH - PT - PB) / 7.2) - 12))}{dirOn(ay)
                    ? ` ${arrow(dirOn(ay)!)} better →`
                    : ''}<title>{ay}</title></text
                >
                <g clip-path="url(#tradeoff-clip)">
                  {#each others.filter(inside) as r (r.id)}
                    <circle
                      class="pt"
                      class:dim={litRun !== null && r.run !== litRun}
                      class:lit={r.run === litRun}
                      cx={X(valueOn(r, ax))}
                      cy={Y(valueOn(r, ay))}
                      r={hover === r ? 4.5 : 2.6}
                      style="fill:{color(r)}"
                    />
                  {/each}
                  {#if edge}<path class="edge" d={edge} />{/if}
                  {#each front as r (r.id)}
                    {@const cx = X(valueOn(r, ax))}
                    {@const cy = Y(valueOn(r, ay))}
                    {#if pickedIds.has(r.id)}<circle class="ring pick" {cx} {cy} r="11" />{/if}
                    {#if chosen.includes(r.id)}<circle class="ring" {cx} {cy} r="9" />{/if}
                    <circle
                      class="fp"
                      class:dim={litRun !== null && r.run !== litRun}
                      {cx}
                      {cy}
                      r={hover === r ? 7 : 5.5}
                      style="fill:{color(r)}"
                    />
                  {/each}
                </g>
                {#if drag?.mode === 'box'}
                  <rect
                    class="zoom-select"
                    x={Math.min(drag.x0, drag.x1)}
                    y={Math.min(drag.y0, drag.y1)}
                    width={Math.abs(drag.x1 - drag.x0)}
                    height={Math.abs(drag.y1 - drag.y0)}
                  />
                {/if}
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
                  {#if runOf(hover).project !== runOf(hover).name && projects.length > 1}
                    <div class="faint small">{runOf(hover).project}</div>
                  {/if}
                  {#each tipCols as k (k)}
                    {@const m = metrics[k]}
                    <div class="tr">
                      <span class="mono faint" title={m}>{tailName(m, 34)}</span><span
                        class="mono"
                        class:best={best[k] >= 0 && front[best[k]] === hover}>{fmtNum(hover.values[k])}</span
                      >
                    </div>
                  {/each}
                  {#if metrics.length > tipCols.length}
                    <div class="faint small">
                      +{metrics.length - tipCols.length} more scalars in the candidates table
                    </div>
                  {/if}
                  <div class="foot faint">
                    {hover.front ? 'A candidate' : 'Not a candidate'} · {chosen.includes(hover.id)
                      ? 'click to stop comparing'
                      : 'click to compare'}
                  </div>
                </div>
              {/if}
            </div>
            <div class="legend">
              {#each data.runs.slice(0, 16) as r, i (r.key)}
                <span
                  role="presentation"
                  class:dim={litRun !== null && litRun !== i}
                  onpointerenter={() => (legendRun = i)}
                  onpointerleave={() => (legendRun = null)}
                  ><i style="background:{seriesVar(i)}"></i><span class="mono">{r.name}</span></span
                >
              {/each}
              {#if data.runs.length > 16}<span class="faint">+{data.runs.length - 16} more</span>{/if}
              <span class="grow"></span>
              {#if zoomed}<span class="faint">Zoomed in; double-click the plot to see it all</span>
              {:else if offPlot}<span class="faint">{offPlot.toLocaleString()} steps far behind are off the plot</span
                >{/if}
              {#if edge}<span class="faint"><i class="dash"></i>trade-off edge on these two axes</span>{/if}
            </div>
          {/if}
        </div>

        <div class="card list">
          <div class="chead">
            <h2>Candidates</h2>
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
                        ><button
                          class="sort mono"
                          class:on={sortBy === m}
                          onclick={() => router.set({ order: m })}
                          title={m}>{tailName(m, 26)} {arrow(dirs[k])}</button
                        ></th
                      >
                    {/each}
                    <th class="l">Artifacts</th><th class="l"></th>
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
                        ><i class="dot" style="background:{color(r)}"></i><span
                          class="mono runname"
                          title={runOf(r).name}>{runOf(r).name}</span
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
                          <span
                            class="faint small"
                            title="No artifact logged at this step. A checkpoint saved only to disk shows here once it is logged with run.add_artifact(..., step=step)"
                            >none</span
                          >
                        {/each}
                      </td>
                      <td class="l tags">
                        {#if pickedIds.has(r.id)}<span class="badge pick"><Icon name="flag" size={11} /> picked</span
                          >{/if}
                        {#if bestOn(r).length === 1}<span
                            class="badge best"
                            title="Best {bestOn(r)[0]} among the candidates"
                            >Best <span class="mono">{tailName(bestOn(r)[0], 26)}</span></span
                          >{:else if bestOn(r).length > 1}<span
                            class="badge best"
                            title={`Best among the candidates for:\n${bestOn(r).join('\n')}`}
                            >Best on {bestOn(r).length === metrics.length ? 'all' : bestOn(r).length} scalars</span
                          >{/if}
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
    <div class="selpad" aria-hidden="true"></div>
    <div class="selbar" role="toolbar" aria-label="Chosen steps">
      <span class="selcount">{compared.length} step{compared.length === 1 ? '' : 's'} chosen</span>
      <span class="sep" aria-hidden="true"></span>
      <button class="btn btn-primary" onclick={() => router.set({ pane: 'compare' })}
        ><Icon name="compare" size={15} /> Compare side by side</button
      >
      <button
        class="btn btn-ghost icon"
        title="Clear the chosen steps"
        aria-label="Clear"
        onclick={() => router.set({ rows: null })}><Icon name="x" size={16} /></button
      >
    </div>
  {/if}
{/if}

{#if tab === 'compare'}
  {#if !compared.length}
    <div class="card empty">
      Choose candidates to compare: tick their boxes, or click their dots on the plot.
      <button class="btn" onclick={() => router.set({ pane: null })}>Back to the candidates</button>
    </div>
  {:else}
    <div class="card cmp" style="grid-template-columns: 230px repeat({compared.length}, minmax(180px, 1fr))">
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
            {#if !r.front}<span class="badge">not a candidate</span>{/if}
          </div>
        </div>
      {/each}

      <div class="grp label">
        Scalars at that step <span class="sub">· the dashed line marks the step on the whole run</span>
      </div>
      {#each metrics as m, k (m)}
        <div class="rh mono" title={m}>{tailName(m, 24)}&nbsp;{arrow(dirs[k])}</div>
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

      {#if compared.length > 1}
        <div class="grp label">Summary <span class="sub">· among the steps compared</span></div>
        {#each [['Best on', wins], ['Worst on', losses]] as const as [label, lists] (label)}
          <div class="rh top">{label}</div>
          {#each compared as r, i (r.id)}
            <div class="sum">
              {#if lists[i].length}
                <span class="count" class:win={label === 'Best on'}>{lists[i].length} of {metrics.length}</span>
                {#each lists[i] as m (m)}<span class="mono small" title={m}>{tailName(m, 34)}</span>{/each}
              {:else}<span class="faint small">none</span>{/if}
            </div>
          {/each}
        {/each}
      {/if}

      {#if configDiff.length}
        <div class="grp label">Config <span class="sub">· only the keys that differ</span></div>
        {#each configDiff.slice(0, 30) as key (key)}
          <div class="rh mono" title={key}><span class="trunc">{tailName(key, 26)}</span></div>
          {#each compared as r (r.id)}
            <div class="mono cfg trunc">{fmtValue(config?.values[key]?.[r.key])}</div>
          {/each}
        {/each}
      {/if}

      <div class="grp label">Artifacts <span class="sub">· logged by the run</span></div>
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
            <span
              class="faint small"
              title="No artifact logged at this step. A checkpoint saved only to disk shows here once it is logged with run.add_artifact(..., step=step)"
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
    z-index: 2; /* sticky makes its own layer: keep it, and the scalar list it opens, above the plot */
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
    max-width: 100%;
    gap: 4px;
  }
  .suggest .tail {
    min-width: 0;
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
  .plot.full {
    position: fixed;
    inset: 0;
    z-index: 50;
    border-radius: 0;
    overflow: auto;
    background: var(--panel);
  }
  .icon-btn {
    height: 32px;
    width: 34px;
    padding: 0;
    display: inline-grid;
    place-items: center;
    flex: none;
  }
  .svgwrap svg {
    cursor: crosshair;
    touch-action: none;
    user-select: none;
  }
  .svgwrap svg.pointing {
    cursor: pointer;
  }
  .svgwrap svg.panning {
    cursor: grabbing;
  }
  .pt.dim,
  .fp.dim {
    opacity: 0.12;
  }
  .pt.lit {
    opacity: 0.9;
  }
  .legend .dim {
    opacity: 0.45;
  }
  .plot .sub {
    margin: 2px 0 0;
  }
  .tip .foot {
    margin-top: 4px;
    font-size: 11.5px;
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
    max-width: 360px;
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
  .sum {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sum .count {
    align-self: flex-start;
    font-weight: 600;
    font-size: 12.5px;
  }
  .sum .count.win {
    color: var(--accent);
  }
  .runname {
    display: inline-block;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
  }
  td.actions {
    white-space: nowrap;
  }
  .icon-btn.sm {
    height: 28px;
    width: 30px;
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
  /* the scalar's name as logged and as its column shows it, never recased */
  .badge.best {
    background: var(--accent-soft);
    color: var(--accent);
    text-transform: none;
    letter-spacing: 0;
    font-weight: 600;
  }
  .badge.best .mono {
    font-size: 11px;
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
  /* row labels fill their grid row, so their divider lines up with the cells beside them */
  .rh {
    color: var(--muted);
    font-size: 12.5px;
    display: flex;
    align-items: center;
    overflow: hidden;
    white-space: nowrap;
  }
  .rh.top {
    align-items: flex-start;
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
