<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { num, type RunBrief } from '../lib/api';
  import { FullScreen } from '../lib/fullscreen.svelte';
  import { addSnapshotToReport } from '../lib/reports.svelte';
  import { svgToPng } from '../lib/snapshot';
  import { defaultMetric, fmtAxis, fmtNum, fmtValue, lowerIsBetter } from '../lib/format';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import { axisTicks, importance, makeAxis, norm, type Axis, type Value } from '../lib/sweep';

  const fs = new FullScreen();
  onMount(() => fs.listen());
  let innerHeight = $state(900);
  const H = $derived(fs.on ? Math.max(380, innerHeight - 200) : 380);
  const TOP = 46;
  const BOTTOM = 30;
  const PAD = 70;

  let width = $state(900);
  let hover = $state<string | null>(null);
  // Brushes per axis key, as [lo, hi] in normalized axis units (0 = bottom).
  let brushes = $state<Record<string, [number, number]>>({});
  let drag = $state<{ key: string; y0: number; y1: number } | null>(null);

  const runs = $derived(app.visibleRuns().filter((r) => r.metric_count > 0));
  const metrics = $derived(app.runs?.metrics ?? []);
  const metric = $derived.by(() => {
    const m = router.get('metric');
    return m && metrics.includes(m) ? m : defaultMetric(metrics);
  });
  const stat = $derived(router.get('stat', 'best'));
  const lower = $derived(lowerIsBetter(metric));

  // ---- snapshots for reports, and the grid of scatter plots ----
  async function saveToReport(svg: SVGSVGElement | null | undefined, title: string, caption: string) {
    const project = runs[0]?.project ?? router.get('project');
    if (!svg || !project) return;
    const png = await svgToPng(svg, title);
    if (fs.on) await fs.toggle(); // dialogs are not shown over a full-screen element
    await addSnapshotToReport(project, png, caption, { page: 'sweeps', params: { ...router.params } });
  }
  let pcSvg = $state<SVGSVGElement>();
  const gridCols = $derived(Number(router.get('scols', String(prefs.get('scols', 0)))) || 0); // 0: fit
  const gridRows = $derived(Number(router.get('srows', String(prefs.get('srows', 0)))) || 0); // 0: all
  function setGrid(k: 'scols' | 'srows', v: string) {
    prefs.set(k, Number(v));
    router.set({ [k]: v === '0' ? null : v });
  }
  let gridWidth = $state(1200);
  let gridPage = $state(0);
  const perRow = $derived(gridCols || Math.max(1, Math.floor((gridWidth + 16) / (300 + 16))));

  function value(r: RunBrief): number | null {
    const s = r.summary[metric];
    if (!s) return null;
    const v = stat === 'last' ? num(s.last) : lower ? s.min : s.max;
    return v !== null && Number.isFinite(v) ? v : null;
  }

  // Parameters: config keys whose values differ between runs, plus properties.
  const candidates = $derived.by(() => {
    const seen = new Map<string, Set<string>>();
    const add = (k: string, v: unknown) => {
      if (!seen.has(k)) seen.set(k, new Set());
      seen.get(k)!.add(JSON.stringify(v ?? null));
    };
    for (const r of runs) {
      for (const [k, v] of Object.entries(r.config)) add(k, v);
      for (const [k, v] of Object.entries(r.fields ?? {})) add(`fields.${k}`, v);
    }
    return [...seen.entries()].filter(([, s]) => s.size > 1 && s.size <= Math.max(runs.length, 2)).map(([k]) => k);
  });
  const params = $derived.by(() => {
    const chosen = router.list('params').filter((p) => candidates.includes(p));
    if (chosen.length) return chosen;
    return candidates.filter((k) => !/seed/i.test(k)).slice(0, 6);
  });
  const get = (r: RunBrief, key: string): Value =>
    key.startsWith('fields.') ? (r.fields?.[key.slice(7)] as Value) : (r.config[key] as Value);

  const values = $derived(runs.map(value));
  const axes = $derived.by((): Axis[] => {
    const list = params.map((p) =>
      makeAxis(
        p,
        runs.map((r) => get(r, p)),
      ),
    );
    const m = makeAxis(metric, values);
    return [...list, { ...m, key: `metric:${metric}` }];
  });
  const scores = $derived(
    new Map(
      params.map((p) => [
        p,
        importance(
          runs.map((r) => get(r, p)),
          values,
        ),
      ]),
    ),
  );

  const plotW = $derived(Math.max(320, width - 2 * PAD));
  const xOf = (i: number) => PAD + (axes.length <= 1 ? plotW / 2 : (i / (axes.length - 1)) * plotW);
  const h = $derived(H - TOP - BOTTOM);
  // The metric axis is flipped for lower-is-better metrics so the best runs are always on top.
  const pos = (axis: Axis, v: Value): number | null => {
    const n = norm(axis, v);
    if (n === null) return null;
    return axis.key.startsWith('metric:') && lower ? 1 - n : n;
  };
  const yOf = (n: number) => TOP + (1 - n) * h;

  const metricAxis = $derived(axes[axes.length - 1]);
  const goodness = (v: number | null) => (v === null ? null : pos(metricAxis, v));
  const colorOf = (g: number | null) =>
    g === null ? 'var(--faint)' : `color-mix(in oklab, var(--s1) ${Math.round(g * 100)}%, var(--s2))`;

  const lines = $derived(
    runs.map((r, i) => {
      const pts = axes.map((a, k) => {
        const v = k === axes.length - 1 ? values[i] : get(r, a.key);
        const n = pos(a, v);
        return { x: xOf(k), n };
      });
      const inBrush = axes.every((a, k) => {
        const b = brushes[a.key];
        const n = pts[k].n;
        return !b || (n !== null && n >= b[0] && n <= b[1]);
      });
      const d = pts.map((p, k) => `${k ? 'L' : 'M'}${p.x.toFixed(1)},${yOf(p.n ?? -0.06).toFixed(1)}`).join('');
      return { run: r, d, keep: inBrush, g: goodness(values[i]), missing: values[i] === null };
    }),
  );
  const kept = $derived(lines.filter((l) => l.keep));
  const ranked = $derived(
    kept.filter((l) => !l.missing).sort((a, b) => (lower ? 1 : -1) * ((value(a.run) ?? 0) - (value(b.run) ?? 0))),
  );

  function brushStart(e: PointerEvent, key: string) {
    const y = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect().top;
    const n = 1 - (e.clientY - y - TOP) / h;
    drag = { key, y0: n, y1: n };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }
  function brushMove(e: PointerEvent) {
    if (!drag) return;
    const y = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect().top;
    drag = { ...drag, y1: Math.min(1, Math.max(0, 1 - (e.clientY - y - TOP) / h)) };
  }
  function brushEnd() {
    if (!drag) return;
    const { key, y0, y1 } = drag;
    drag = null;
    const next = { ...brushes };
    if (Math.abs(y1 - y0) < 0.02) delete next[key];
    else next[key] = [Math.min(y0, y1), Math.max(y0, y1)];
    brushes = next;
  }
  function toggleParam(p: string) {
    const next = params.includes(p) ? params.filter((x) => x !== p) : [...params, p];
    router.set({ params: next.join(',') || null });
  }
  const label = (key: string) => (key.startsWith('metric:') ? key.slice(7) : key);
  const short = (key: string) => label(key).split('.').slice(-2).join('.');
  const fmt = (v: number) => fmtAxis(v);
  // Axis titles are SVG text, which cannot ellipsize: cut them to the room between axes
  // (the outer axes only have the side padding), with the full name in a <title>.
  const cut = (text: string, max: number) => (text.length > max ? text.slice(0, Math.max(1, max - 1)) + '…' : text);
  const spacing = $derived(axes.length > 1 ? plotW / (axes.length - 1) : plotW);
  const fitAxis = (text: string, k: number) => {
    const room = (k === 0 || k === axes.length - 1 ? Math.min(spacing, 2 * PAD) : spacing) - 12;
    return cut(text, Math.max(4, Math.floor(room / 7.6)));
  };
  // Category tick labels sit left of their axis: the first axis only has the side padding.
  const fitTick = (text: string, a: Axis, k: number) =>
    a.numeric ? text : cut(text, Math.max(4, Math.floor(((k === 0 ? PAD : spacing) - 14) / 6.4)));
  // Scatter x labels: categories split the 230-unit axis between them, the outer ones anchored inward.
  const scatterTick = (a: Axis, n: number, text: string) => {
    if (a.numeric) return { text, anchor: 'middle' };
    const room = 230 / Math.max(a.categories.length, 2) - 6;
    return {
      text: cut(text, Math.max(4, Math.floor(room / 6.4))),
      anchor: n === 0 ? 'start' : n === 1 ? 'end' : 'middle',
    };
  };
</script>

<svelte:window bind:innerHeight />

<div class="card panel" class:full={fs.on} bind:this={fs.el}>
  <div class="toolbar">
    <span class="label">Objective</span>
    <select
      class="input mono metric"
      value={metric}
      onchange={(e) => router.set({ metric: (e.currentTarget as HTMLSelectElement).value })}
      aria-label="Metric"
    >
      {#each metrics as m (m)}<option value={m}>{m}</option>{/each}
    </select>
    <div class="seg" role="group" aria-label="Statistic">
      <button aria-pressed={stat === 'best'} onclick={() => router.set({ stat: null })}>best</button>
      <button aria-pressed={stat === 'last'} onclick={() => router.set({ stat: 'last' })}>last</button>
    </div>
    <span class="muted">{lower ? 'lower is better' : 'higher is better'} · {kept.length} of {runs.length} runs</span>
    <span class="grow"></span>
    {#if Object.keys(brushes).length}<button class="btn" onclick={() => (brushes = {})}>Clear filters</button>{/if}
    <button
      class="btn btn-ghost icon-btn"
      title="Add this plot to a report"
      aria-label="Add parallel coordinates to a report"
      disabled={!ranked.length}
      onclick={() =>
        saveToReport(pcSvg, `${metric} (${stat}) · parallel coordinates`, `${metric} across ${params.join(', ')}`)}
      ><Icon name="bookmark" size={15} /></button
    >
    <button
      class="btn btn-ghost icon-btn"
      title={fs.on ? 'Exit full screen (Esc)' : 'Full screen'}
      aria-label={fs.on ? 'Exit full screen' : 'Full screen'}
      aria-pressed={fs.on}
      onclick={() => fs.toggle()}><Icon name={fs.on ? 'shrink' : 'expand'} size={15} /></button
    >
    <button
      class="btn btn-primary"
      disabled={!ranked.length}
      onclick={() => router.go('charts', { sel: ranked.map((l) => l.run.key).join(','), metric })}
    >
      Plot {ranked.length} runs
    </button>
  </div>

  {#if !runs.length || !metric}
    <div class="empty">No runs with metrics to compare. Pick a project or loosen the query.</div>
  {:else}
    <div class="params">
      <span class="label">Parameters</span>
      {#each candidates as p (p)}
        {@const score = scores.get(p)}
        <button class="chip param" aria-pressed={params.includes(p)} onclick={() => toggleParam(p)} title={p}>
          <span class="mono trunc">{short(p)}</span>
          {#if params.includes(p) && score !== null && score !== undefined}
            <span class="imp" title="Rank correlation with {metric}"><span style="width:{score * 100}%"></span></span>
          {/if}
        </button>
      {:else}
        <span class="faint">All runs share the same config; there is nothing to sweep over.</span>
      {/each}
    </div>

    <div class="pc" bind:clientWidth={width}>
      <svg {width} height={H} role="img" aria-label="Parallel coordinates of {runs.length} runs" bind:this={pcSvg}>
        {#each lines.filter((l) => !l.keep) as l (l.run.key)}
          <path class="line dim" d={l.d} />
        {/each}
        {#each kept as l (l.run.key)}
          <path
            class="line"
            class:missing={l.missing}
            class:hl={hover === l.run.key}
            d={l.d}
            style="stroke:{colorOf(l.g)}"
            role="button"
            tabindex="-1"
            onpointerenter={() => (hover = l.run.key)}
            onpointerleave={() => (hover = null)}
            onclick={() => router.go('runs', { cmp: l.run.key })}
            onkeydown={() => {}}><title>{l.run.name}: {fmtNum(value(l.run))}</title></path
          >
        {/each}
        {#each axes as a, k (a.key)}
          {@const x = xOf(k)}
          {@const isMetric = k === axes.length - 1}
          <g class="axis" class:metricaxis={isMetric}>
            <line x1={x} x2={x} y1={TOP} y2={TOP + h} />
            <text class="title mono" {x} y={TOP - 26} text-anchor="middle"
              ><title>{label(a.key)}</title>{fitAxis(short(a.key), k)}</text
            >
            <text class="sub" {x} y={TOP - 12} text-anchor="middle"
              >{isMetric
                ? `${stat} · best on top`
                : a.numeric
                  ? a.log
                    ? 'log scale'
                    : 'linear'
                  : `${a.categories.length} values`}</text
            >
            {#each axisTicks(a, fmt) as [n, text] (text + n)}
              {@const yy = yOf(isMetric && lower ? 1 - n : n)}
              {@const side = isMetric ? 1 : -1}
              <line class="tickmark" x1={x + side * 4} x2={x} y1={yy} y2={yy} />
              <text class="tick mono" x={x + side * 7} y={yy + 4} text-anchor={isMetric ? 'start' : 'end'}
                ><title>{text}</title>{fitTick(text, a, k)}</text
              >
            {/each}
            {#if brushes[a.key]}
              {@const b = brushes[a.key]}
              <rect class="brush" x={x - 9} y={yOf(b[1])} width="18" height={yOf(b[0]) - yOf(b[1])} rx="3" />
            {/if}
            {#if drag?.key === a.key}
              <rect
                class="brush live"
                x={x - 9}
                y={yOf(Math.max(drag.y0, drag.y1))}
                width="18"
                height={Math.abs(drag.y1 - drag.y0) * h}
                rx="3"
              />
            {/if}
            <rect
              class="hit"
              x={x - 14}
              y={TOP - 4}
              width="28"
              height={h + 8}
              role="slider"
              aria-label="Filter {label(a.key)}"
              aria-valuenow={0}
              tabindex="-1"
              onpointerdown={(e) => brushStart(e, a.key)}
              onpointermove={brushMove}
              onpointerup={brushEnd}
            />
          </g>
        {/each}
        <text class="sub" x={xOf(axes.length - 1)} y={TOP + h + 22} text-anchor="middle">missing / NaN</text>
      </svg>
      <p class="hint">
        Drag along an axis to keep only the runs in that range; click an axis to clear its filter. Line color goes from
        orange (worst) to blue (best). The bars next to each parameter show its rank correlation with the objective.
      </p>
    </div>
  {/if}
</div>

{#if runs.length && metric && params.length}
  {@const size = gridRows ? perRow * gridRows : params.length}
  {@const pageCount = Math.max(1, Math.ceil(params.length / size))}
  {@const page = Math.min(gridPage, pageCount - 1)}
  <div class="grid-head">
    <h3>{metric} against each parameter</h3>
    {#if pageCount > 1}
      <span class="pager">
        <button
          class="btn btn-ghost sm"
          aria-label="Previous plots"
          disabled={page === 0}
          onclick={() => (gridPage = page - 1)}>‹</button
        >
        <span class="mono faint">{page + 1} / {pageCount}</span>
        <button
          class="btn btn-ghost sm"
          aria-label="Next plots"
          disabled={page >= pageCount - 1}
          onclick={() => (gridPage = page + 1)}>›</button
        >
      </span>
    {/if}
    <span class="label">Grid</span>
    <label class="opt"
      ><span class="faint">columns</span>
      <select
        class="input sm"
        aria-label="Plot columns"
        value={String(gridCols)}
        onchange={(e) => setGrid('scols', e.currentTarget.value)}
      >
        <option value="0">fit</option>
        {#each [1, 2, 3, 4, 5, 6] as n (n)}<option value={String(n)}>{n}</option>{/each}
      </select></label
    >
    <label class="opt"
      ><span class="faint">rows</span>
      <select
        class="input sm"
        aria-label="Plot rows per page"
        value={String(gridRows)}
        onchange={(e) => setGrid('srows', e.currentTarget.value)}
      >
        {#each [1, 2, 3, 4, 6] as n (n)}<option value={String(n)}>{n}</option>{/each}
        <option value="0">all</option>
      </select></label
    >
  </div>
  <section
    class="grid"
    bind:clientWidth={gridWidth}
    style={gridCols ? `grid-template-columns: repeat(${gridCols}, minmax(0, 1fr))` : ''}
  >
    {#each params.slice(page * size, page * size + size) as p (p)}
      {@const a = axes[params.indexOf(p)]}
      <div class="card scatter">
        <div class="sh">
          <span class="mono trunc" title={p}>{short(p)}</span>
          {#if scores.get(p) !== null && scores.get(p) !== undefined}<span class="faint keep"
              >correlation {fmtNum(scores.get(p)!, 2)}</span
            >{/if}
          <button
            class="icon"
            title="Add this plot to a report"
            aria-label="Add {short(p)} plot to a report"
            onclick={(e) =>
              saveToReport(
                e.currentTarget.closest('.scatter')?.querySelector<SVGSVGElement>('svg[role="img"]'),
                `${metric} against ${p}`,
                `${metric} against ${p}`,
              )}><Icon name="bookmark" size={14} /></button
          >
        </div>
        <svg viewBox="0 0 300 190" role="img" aria-label="{metric} against {p}">
          <line class="frame" x1="40" x2="290" y1="160" y2="160" />
          <line class="frame" x1="40" x2="40" y1="10" y2="160" />
          {#each axisTicks(a, fmt) as [n, text] (text + n)}
            {@const t = scatterTick(a, n, text)}
            <text class="tick mono" x={46 + n * 230} y="176" text-anchor={t.anchor}><title>{text}</title>{t.text}</text>
          {/each}
          {#each axisTicks(metricAxis, fmt).filter((_, i, all) => i === 0 || i === all.length - 1 || all.length <= 3) as [n, text] (text + n)}
            {@const yy = 160 - (lower ? 1 - n : n) * 150}
            <text class="tick mono" x="36" y={yy + 3} text-anchor="end">{text}</text>
          {/each}
          {#each lines as l, i (l.run.key)}
            {@const xn = norm(a, get(l.run, p))}
            {@const g = l.g}
            {#if xn !== null && g !== null}
              {@const jitter = a.numeric ? 0 : (((i * 37) % 11) - 5) * 1.6}
              <circle
                cx={46 + xn * 230 + jitter}
                cy={160 - g * 150}
                r={hover === l.run.key ? 5 : 3.5}
                class:dim={!l.keep}
                style="fill:{l.keep ? colorOf(g) : 'var(--border)'}"
                role="button"
                tabindex="-1"
                onpointerenter={() => (hover = l.run.key)}
                onpointerleave={() => (hover = null)}
                onclick={() => router.go('runs', { cmp: l.run.key })}
                onkeydown={() => {}}
                ><title>{l.run.name}: {fmtValue(get(l.run, p))} → {fmtNum(value(l.run))}</title></circle
              >
            {/if}
          {/each}
        </svg>
      </div>
    {/each}
  </section>

  <section class="card best">
    <div class="sh">
      <span class="label keep">Best runs</span><span class="faint trunc" title="{metric} ({stat}), filtered"
        >{metric} ({stat}), filtered</span
      >
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Run</th>
          {#each params as p (p)}<th class="mono"><span class="trunc cell" title={p}>{short(p)}</span></th>{/each}
          <th class="right mono"><span class="trunc cell" title={metric}>{metric}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each ranked.slice(0, 10) as l, i (l.run.key)}
          <tr
            class:hl={hover === l.run.key}
            onpointerenter={() => (hover = l.run.key)}
            onpointerleave={() => (hover = null)}
          >
            <td class="faint">{i + 1}</td>
            <td
              ><button
                class="link mono trunc runname"
                title={l.run.name}
                onclick={() => router.go('runs', { cmp: l.run.key })}>{l.run.name}</button
              ></td
            >
            {#each params as p (p)}<td class="mono"
                ><span class="trunc cell" title={fmtValue(get(l.run, p))}>{fmtValue(get(l.run, p))}</span></td
              >{/each}
            <td class="right mono nowrap">{fmtNum(value(l.run))}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

<style>
  .panel {
    overflow: hidden;
  }
  .panel.full {
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
  .icon {
    display: inline-grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    border: 0;
    background: none;
    color: var(--muted);
    flex: none;
    margin-left: auto;
  }
  .scatter .sh {
    justify-content: flex-start;
    align-items: center;
  }
  .scatter .sh .keep {
    margin-left: auto;
  }
  .scatter .sh .keep + .icon {
    margin-left: 0;
  }
  .icon:hover {
    background: var(--panel-2);
    color: var(--accent);
  }
  .grid-head {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin: 18px 0 10px;
  }
  .grid-head h3 {
    font-size: 16px;
    font-weight: 650;
    margin: 0 auto 0 0;
  }
  .opt {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
  }
  .opt select {
    height: 30px;
  }
  .pager {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
  }
  .pager .btn {
    height: 26px;
    padding: 0 8px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
  }
  .metric {
    max-width: 240px;
    font-size: 12.5px;
  }
  .grow {
    flex: 1;
  }
  /* Long names shrink with an ellipsis (full text in the title attribute); values never do. */
  .trunc {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .keep {
    flex: none;
    white-space: nowrap;
  }
  .nowrap {
    white-space: nowrap;
  }
  .cell {
    max-width: 200px;
  }
  .right .cell {
    margin-left: auto;
  }
  .runname {
    max-width: 340px;
  }
  .muted {
    color: var(--muted);
    font-size: 13px;
  }
  .faint {
    color: var(--faint);
  }
  .params {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    padding: 12px 14px 4px;
  }
  .params .label {
    margin-right: 6px;
  }
  .param {
    border: 1px solid var(--border);
    background: var(--panel);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    font-size: 12px;
    max-width: 280px;
    min-width: 0;
  }
  .param[aria-pressed='true'] {
    background: var(--accent-soft);
    border-color: transparent;
    color: var(--accent);
  }
  .imp {
    width: 34px;
    height: 5px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
    display: inline-block;
  }
  .imp span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .pc {
    width: 100%;
    overflow: hidden;
    user-select: none;
  }
  svg {
    display: block;
  }
  .line {
    fill: none;
    stroke-width: 1.6;
    opacity: 0.85;
    cursor: pointer;
  }
  .line.dim {
    stroke: var(--border);
    opacity: 0.6;
    pointer-events: none;
  }
  .line.missing {
    stroke-dasharray: 4 4;
  }
  .line.hl {
    stroke-width: 3.5;
    opacity: 1;
  }
  .axis line {
    stroke: var(--muted);
  }
  .axis .tickmark {
    stroke: var(--muted);
  }
  .title {
    fill: var(--text);
    font-size: 12.5px;
    font-weight: 600;
  }
  .metricaxis .title {
    fill: var(--accent);
  }
  .sub {
    fill: var(--faint);
    font-size: 11px;
  }
  .tick {
    fill: var(--muted);
    font-size: 10.5px;
  }
  .hit {
    fill: transparent;
    cursor: ns-resize;
  }
  .brush {
    fill: var(--accent-soft);
    stroke: var(--accent);
    opacity: 0.85;
    pointer-events: none;
  }
  .brush.live {
    opacity: 0.5;
  }
  .hint {
    color: var(--faint);
    font-size: 12.5px;
    margin: 0;
    padding: 4px 14px 14px;
  }
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }
  .scatter {
    padding: 12px 12px 6px;
    min-width: 0;
  }
  .sh {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
    font-size: 13px;
    padding-bottom: 6px;
  }
  .frame {
    stroke: var(--border);
  }
  circle {
    cursor: pointer;
    stroke: var(--panel);
    stroke-width: 1;
  }
  circle.dim {
    opacity: 0.5;
  }
  .best {
    padding: 14px;
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  th {
    text-align: left;
    color: var(--muted);
    font-weight: 600;
    font-size: 11.5px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  tr.hl td {
    background: var(--panel-2);
  }
  .right {
    text-align: right;
  }
  .link {
    border: 0;
    background: none;
    padding: 0;
    color: var(--text);
    font-weight: 600;
  }
  .link:hover {
    color: var(--accent);
    text-decoration: underline;
  }
</style>
