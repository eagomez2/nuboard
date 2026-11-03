<script lang="ts">
  // The Timing tab of a run's details: where the run's time went, from its timers
  // (`run.timer`). A findings line, a table of timers with a per-step line each (a row
  // opens into a full chart) and a timeline of one step with a lane per rank.
  import LineChart from './LineChart.svelte';
  import Icon from './Icon.svelte';
  import {
    api,
    type ChartData,
    type RunDetail,
    type TimingSeries,
    type TimingSpans,
    type TimingSummary,
  } from '../lib/api';
  import { cssVar } from '../lib/colors';
  import { fmtCount, fmtSeconds } from '../lib/format';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  let { detail }: { detail: RunDetail } = $props();
  const key = $derived(detail.run.key);

  // ---- which rank: one rank, or every rank (mean, with min-max bands) --------------------
  const rankParam = $derived(router.get('trank', '0'));
  const rank = $derived<number | 'all'>(rankParam === 'all' ? 'all' : Number(rankParam) || 0);

  let summary = $state<TimingSummary | null>(null);
  let error = $state('');
  // Reload on live updates of the run (its heartbeat moves while it runs)
  const beat = $derived(app.runByKey(key)?.heartbeat ?? detail.run.heartbeat);
  $effect(() => {
    void beat;
    const k = key;
    const r = rank;
    api
      .timing(k, r)
      .then((s) => {
        if (k === key) {
          summary = s;
          error = '';
        }
      })
      .catch((e) => (error = String(e)));
  });
  const ranks = $derived(summary?.ranks ?? []);
  const multiRank = $derived(ranks.length > 1);

  // ---- the timeline's step ----------------------------------------------------------------
  const stepParam = $derived(router.get('tstep'));
  const wantStep = $derived(stepParam === '' ? null : Number(stepParam));
  let spans = $state<TimingSpans | null>(null);
  $effect(() => {
    void beat;
    const k = key;
    api
      .timingSpans(k, wantStep)
      .then((s) => {
        if (k === key) spans = s;
      })
      .catch(() => (spans = null));
  });
  const shownStep = $derived(spans?.step ?? null);
  function setStep(step: number | null) {
    router.set({ tstep: step === null ? null : String(step) });
  }

  // ---- table -------------------------------------------------------------------------------
  let open = $state<string | null>(null);
  const COLORS = [
    'var(--s1)',
    'var(--s2)',
    'var(--s4)',
    'var(--s3)',
    'var(--s8)',
    'var(--s6)',
    'var(--s5)',
    'var(--s7)',
  ];
  const colorOf = $derived.by(() => {
    const map = new Map<string, string>();
    (summary?.timers ?? []).forEach((t, i) => map.set(t.name, COLORS[i % COLORS.length]));
    return (name: string) => map.get(name) ?? 'var(--faint)';
  });
  // the chart draws on a canvas, which cannot read CSS variables
  const canvasColor = (c: string) => (c.startsWith('var(') ? cssVar(c.slice(4, -1)) || '#0072b2' : c);
  const pct = (share: number | null | undefined) =>
    share === null || share === undefined ? '—' : share > 0 && share < 0.001 ? '<0.1%' : `${(share * 100).toFixed(1)}%`;
  const shareBar = (share: number | null | undefined) => Math.max(1.5, Math.min(1, share ?? 0) * 70);

  // ---- per-step line (sparkline) -------------------------------------------------------------
  const SW = 300;
  const SH = 28;
  const xRange = $derived.by(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const t of summary?.timers ?? []) {
      if (t.series.x.length) {
        lo = Math.min(lo, t.series.x[0]);
        hi = Math.max(hi, t.series.x[t.series.x.length - 1]);
      }
    }
    return Number.isFinite(lo) ? ([lo, hi === lo ? lo + 1 : hi] as [number, number]) : ([0, 1] as [number, number]);
  });
  const sx = (x: number) => ((x - xRange[0]) / (xRange[1] - xRange[0])) * SW;
  function sparkPaths(s: TimingSeries) {
    let top = 0;
    for (let i = 0; i < s.y.length; i++) top = Math.max(top, s.hi[i] ?? s.y[i] ?? 0, s.y[i] ?? 0);
    top = top * 1.1 || 1;
    const sy = (v: number) => SH - 2 - (v / top) * (SH - 4);
    let line = '';
    let up = '';
    let down = '';
    let pen = false;
    for (let i = 0; i < s.x.length; i++) {
      const y = s.y[i];
      if (y === null) {
        pen = false;
        continue;
      }
      line += `${pen ? 'L' : 'M'}${sx(s.x[i]).toFixed(1)},${sy(y).toFixed(1)}`;
      pen = true;
      const lo = s.lo[i] ?? y;
      const hi = s.hi[i] ?? y;
      up += `${up ? 'L' : 'M'}${sx(s.x[i]).toFixed(1)},${sy(hi).toFixed(1)}`;
      down = `L${sx(s.x[i]).toFixed(1)},${sy(lo).toFixed(1)}` + down;
    }
    const band = up && up !== down ? `${up}${down}Z` : '';
    return { line, band, sy };
  }
  function nearest(s: TimingSeries, step: number): number {
    let best = -1;
    let gap = Infinity;
    for (let i = 0; i < s.x.length; i++) {
      const d = Math.abs(s.x[i] - step);
      if (d < gap) {
        gap = d;
        best = i;
      }
    }
    return best;
  }
  let hover = $state<{ row: string; step: number; value: number | null; lo: number | null; hi: number | null } | null>(
    null,
  );
  function onSparkMove(e: MouseEvent, row: string, s: TimingSeries) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const step = xRange[0] + ((e.clientX - r.left) / r.width) * (xRange[1] - xRange[0]);
    const i = nearest(s, step);
    if (i >= 0) hover = { row, step: s.x[i], value: s.y[i], lo: s.lo[i], hi: s.hi[i] };
  }
  function onSparkClick(e: MouseEvent, row: string, s: TimingSeries) {
    e.stopPropagation();
    onSparkMove(e, row, s);
    if (hover) setStep(Math.round(hover.step));
  }

  // ---- expanded row: a full chart ---------------------------------------------------------------
  function chartOf(name: string, s: TimingSeries): ChartData {
    const arr = (a: (number | null)[]) => Float64Array.from(a, (v) => (v === null ? NaN : v));
    const y = arr(s.y);
    return {
      metric: name,
      xKind: 'step',
      series: [
        {
          label: name,
          runs: [key],
          group: null,
          band: rank === 'all',
          last: y.length ? y[y.length - 1] : null,
          nonfinite: false,
          x: Float64Array.from(s.x),
          y,
          lo: arr(s.lo),
          hi: arr(s.hi),
        },
      ],
    };
  }
  const regions = $derived(
    (summary?.sessions ?? []).map((s) => ({
      x0: s.step,
      x1: s.step,
      label: `session ${s.session}${s.host ? ` · ${s.host}` : ''}`,
    })),
  );
  let cursor = $state<{ x: number; value: number } | null>(null);
  function openInCharts(metric: string) {
    router.go('charts', { sel: key, metric, cmp: null, pair: null, tab: null, tstep: null, trank: null });
  }

  // ---- timeline ----------------------------------------------------------------------------------
  const LANE = 24;
  const SUB = 9; // height of a nested row below a span
  const TL = 64;
  let tlWidth = $state(1000);
  const tlEnd = $derived.by(() => {
    let end = 0;
    for (const r of spans?.ranks ?? []) for (const s of r.spans) end = Math.max(end, s.end);
    return end || 1;
  });
  const maxDepth = $derived(Math.max(0, ...(spans?.ranks ?? []).flatMap((r) => r.spans.map((s) => s.depth))));
  const laneH = $derived(LANE + maxDepth * SUB);
  const tx = (t: number) => TL + (t / tlEnd) * (tlWidth - TL - 8);
  const ticks = $derived.by(() => {
    const raw = tlEnd / 6;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((m) => m * mag).find((m) => m >= raw) ?? raw;
    const out = [];
    for (let t = 0; t <= tlEnd + 1e-9; t += step) out.push(t);
    return out;
  });
  // Where each rank had no top-level span while another rank had one: waiting
  const waits = $derived.by(() => {
    const lanes = spans?.ranks ?? [];
    if (lanes.length < 2) return new Map<number, [number, number][]>();
    const top = (r: (typeof lanes)[number]) =>
      r.spans.filter((s) => s.depth === 0 && !s.accumulated).map((s) => [s.start, s.end] as [number, number]);
    const merge = (iv: [number, number][]) => {
      const sorted = [...iv].sort((a, b) => a[0] - b[0]);
      const out: [number, number][] = [];
      for (const [a, b] of sorted) {
        const last = out[out.length - 1];
        if (last && a <= last[1]) last[1] = Math.max(last[1], b);
        else out.push([a, b]);
      }
      return out;
    };
    const all = merge(lanes.flatMap(top));
    const map = new Map<number, [number, number][]>();
    for (const r of lanes) {
      const mine = merge(top(r));
      const gaps: [number, number][] = [];
      for (const [a, b] of all) {
        let cur = a;
        for (const [c, d] of mine) {
          if (d <= cur || c >= b) continue;
          if (c > cur) gaps.push([cur, c]);
          cur = Math.max(cur, d);
        }
        if (cur < b) gaps.push([cur, b]);
      }
      map.set(
        r.rank,
        gaps.filter(([a, b]) => b - a > tlEnd / 2000),
      );
    }
    return map;
  });
  function spanTitle(s: TimingSpans['ranks'][number]['spans'][number], r: number) {
    const what = s.accumulated
      ? `${fmtSeconds(s.seconds)} summed over ${fmtCount(s.count)} calls`
      : `${fmtSeconds(s.seconds)}, from ${fmtSeconds(s.start)} to ${fmtSeconds(s.end)}`;
    return `${s.name} · rank ${r} · step ${shownStep}\n${what}`;
  }
</script>

{#if error}
  <p class="muted small">Could not load the timers: {error}</p>
{:else if !summary}
  <p class="muted small">Loading timers…</p>
{:else if !summary.timers.length}
  <p class="muted small">This run logged no timers. Time parts of the code with <code>run.timer(name)</code>.</p>
{:else}
  <div class="tm">
    <div class="find">
      <span class="sum">
        <b>{pct(summary.untimed ? 1 - (summary.untimed.share ?? 0) : null)}</b> of
        <b>{fmtSeconds(summary.wall)}</b> timed · <b>{summary.steps.toLocaleString('en')}</b>
        {summary.steps === 1 ? 'step' : 'steps'}{#if multiRank}
          · <b>{ranks.length}</b> ranks{/if}{#if summary.sessions.length}
          · <b>{summary.sessions.length + 1}</b> sessions{/if}
      </span>
      {#each summary.findings as f, i (i)}
        <button
          class="chip"
          title={f.step !== undefined ? 'Show this step in the timeline' : f.message}
          onclick={() => {
            if (f.step !== undefined) setStep(f.step);
            else if (f.rank !== undefined) router.set({ trank: 'all' });
          }}><Icon name="alert" size={13} /> {f.message}</button
        >
      {/each}
      {#if multiRank}
        <span class="seg" role="group" aria-label="Ranks">
          <span class="seglabel">Ranks</span>
          <button aria-pressed={rank === 'all'} onclick={() => router.set({ trank: 'all' })}
            >All {ranks.length} · min–mean–max</button
          >
          <select
            class:on={rank !== 'all'}
            aria-label="One rank"
            value={rank === 'all' ? '' : String(rank)}
            onchange={(e) => router.set({ trank: (e.currentTarget as HTMLSelectElement).value || 'all' })}
          >
            {#if rank === 'all'}<option value="">One rank…</option>{/if}
            {#each ranks as r (r)}<option value={String(r)}>Rank {r}</option>{/each}
          </select>
        </span>
      {/if}
    </div>

    <div class="box">
      <div class="head">
        <b>Timers</b>
        <span
          >{rank === 'all' ? 'mean over ranks, shaded min–max across ranks' : `rank ${rank}`} · line: duration per step{summary
            .sessions.length
            ? ', │ session start'
            : ''} · click a row to open its chart</span
        >
      </div>
      <table>
        <thead>
          <tr>
            <th>Timer</th>
            <th title="Spans timed; a summed timer counts each span it summed">Calls</th>
            <th title="Mean time per step">Mean / step</th>
            <th title="95th percentile of the time per step">p95</th>
            <th>Total</th>
            <th title="Share of the run's wall time">Share</th>
            <th class="l"
              >Per step, {Math.round(xRange[0]).toLocaleString('en')} → {Math.round(xRange[1]).toLocaleString('en')}</th
            >
          </tr>
        </thead>
        <tbody>
          {#each summary.timers as t (t.key)}
            {@const p = sparkPaths(t.series)}
            <tr class="row" class:open={open === t.name} onclick={() => (open = open === t.name ? null : t.name)}>
              <td class="name">
                <span class="chev">{open === t.name ? '▾' : '▸'}</span>
                <span style="padding-left: {t.depth * 14}px"></span>
                {#if t.depth}<span class="tree">└</span>{/if}
                <span class="sw" style="background: {colorOf(t.name)}"></span><span class="mono">{t.name}</span>
                {#if t.accumulated}<span class="acc" title="Logged with accumulate=True: summed per step">summed</span
                  >{/if}
              </td>
              <td class="num" title={Math.round(t.calls).toLocaleString('en')}>{fmtCount(t.calls)}</td>
              <td class="num">{fmtSeconds(t.mean)}</td>
              <td class="num">{fmtSeconds(t.p95)}</td>
              <td class="num">{fmtSeconds(t.total)}</td>
              <td class="num"
                ><span class="bar" style="width: {shareBar(t.share)}px; background: {colorOf(t.name)}"></span>{pct(
                  t.share,
                )}</td
              >
              <td class="spark">
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (a mouse shortcut; the step stepper does it by keyboard) -->
                <svg
                  width="100%"
                  preserveAspectRatio="none"
                  height={SH}
                  viewBox="0 0 {SW} {SH}"
                  role="img"
                  aria-label="{t.name} per step"
                  onmousemove={(e) => onSparkMove(e, t.name, t.series)}
                  onmouseleave={() => (hover = null)}
                  onclick={(e) => onSparkClick(e, t.name, t.series)}
                >
                  {#each summary.sessions as s (s.session)}
                    <line class="sess" x1={sx(s.step)} x2={sx(s.step)} y1="0" y2={SH} />
                  {/each}
                  {#if p.band}<path d={p.band} fill={colorOf(t.name)} opacity="0.18" />{/if}
                  <path d={p.line} fill="none" stroke={colorOf(t.name)} stroke-width="1.2" />
                  {#if shownStep !== null}
                    {@const i = nearest(t.series, shownStep)}
                    <line class="at" x1={sx(shownStep)} x2={sx(shownStep)} y1="0" y2={SH} />
                    {#if i >= 0 && t.series.y[i] !== null}
                      <circle class="dot" cx={sx(t.series.x[i])} cy={p.sy(t.series.y[i] ?? 0)} r="2.5" />
                    {/if}
                  {/if}
                </svg>
                {#if hover && hover.row === t.name}
                  <span class="tip mono"
                    >step {Math.round(hover.step).toLocaleString('en')} · {fmtSeconds(
                      hover.value,
                    )}{#if rank === 'all' && hover.lo !== hover.hi}
                      · ranks {fmtSeconds(hover.lo)}–{fmtSeconds(hover.hi)}{/if}</span
                  >
                {/if}
              </td>
            </tr>
            {#if open === t.name}
              <tr class="big">
                <td colspan="7">
                  <div class="bighead">
                    <b class="mono">{t.name}</b>
                    <span
                      >per step{rank === 'all' ? ' · mean over ranks, shaded min–max' : ''}{#if cursor}
                        · step {Math.round(cursor.x).toLocaleString('en')}:
                        <b class="mono">{fmtSeconds(cursor.value)}</b>{/if}</span
                    >
                    <button class="link" onclick={() => openInCharts(t.key)}
                      >Open in Charts <Icon name="external" size={12} /></button
                    >
                  </div>
                  <div class="bigplot">
                    <LineChart
                      data={chartOf(t.name, t.series)}
                      height={220}
                      smoothing={0}
                      showRaw={false}
                      robust={false}
                      colorOf={() => canvasColor(colorOf(t.name))}
                      syncKey="timing"
                      themeVersion={app.themeVersion}
                      {regions}
                      yFormat={fmtSeconds}
                      onCursor={(x, v) => (cursor = x === null || !v.length ? null : { x, value: v[0].value })}
                    />
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
          {#if summary.waiting}
            {@const p = sparkPaths(summary.waiting.series)}
            <tr class="extra">
              <td class="name"><span class="chev"></span><span class="sw hatch"></span>waiting for other ranks</td>
              <td class="num"></td>
              <td class="num">{fmtSeconds(summary.waiting.mean)}</td>
              <td class="num">{fmtSeconds(summary.waiting.p95)}</td>
              <td class="num">{fmtSeconds(summary.waiting.total)}</td>
              <td class="num"
                ><span class="bar" style="width: {shareBar(summary.waiting.share)}px; background: var(--faint)"
                ></span>{pct(summary.waiting.share)}</td
              >
              <td class="spark">
                <svg
                  width="100%"
                  preserveAspectRatio="none"
                  height={SH}
                  viewBox="0 0 {SW} {SH}"
                  role="img"
                  aria-label="waiting per step"
                >
                  {#if p.band}<path d={p.band} fill="var(--faint)" opacity="0.2" />{/if}
                  <path d={p.line} fill="none" stroke="var(--faint)" stroke-width="1.2" />
                </svg>
              </td>
            </tr>
          {/if}
          {#if summary.untimed}
            <tr class="extra">
              <td class="name" title="Wall time when no timer was running"
                ><span class="chev"></span><span class="sw empty"></span>not under a timer</td
              >
              <td class="num"></td>
              <td class="num">{fmtSeconds(summary.untimed.mean)}</td>
              <td class="num"></td>
              <td class="num">{fmtSeconds(summary.untimed.total)}</td>
              <td class="num"
                ><span class="bar" style="width: {shareBar(summary.untimed.share)}px; background: var(--border)"
                ></span>{pct(summary.untimed.share)}</td
              >
              <td></td>
            </tr>
          {/if}
        </tbody>
      </table>
    </div>

    {#if spans && spans.step !== null}
      <div class="box">
        <div class="head">
          <b>Timeline</b>
          <span class="stepper mono">
            <button aria-label="Previous step" disabled={spans.prev === null} onclick={() => setStep(spans!.prev)}
              >‹</button
            >
            <span>step {spans.step.toLocaleString('en')}</span>
            <button aria-label="Next step" disabled={spans.next === null} onclick={() => setStep(spans!.next)}>›</button
            >
          </span>
          <span>hover a span for its times · click a line above to pick a step</span>
          <span class="legend">
            {#if spans.ranks.length > 1}<span><i class="hatch"></i>waiting</span>{/if}
            <span><i class="strip"></i>summed (no position in time)</span>
          </span>
        </div>
        <div class="timeline" bind:clientWidth={tlWidth}>
          <svg
            width={tlWidth}
            height={spans.ranks.length * laneH + 26}
            viewBox="0 0 {tlWidth} {spans.ranks.length * laneH + 26}"
          >
            <defs>
              <pattern id="tm-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="var(--panel-2)" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--border)" stroke-width="2.5" />
              </pattern>
            </defs>
            {#each ticks as t (t)}
              <line class="grid" x1={tx(t)} x2={tx(t)} y1="0" y2={spans.ranks.length * laneH} />
              <text class="axis" x={tx(t)} y={spans.ranks.length * laneH + 16} text-anchor="middle"
                >{fmtSeconds(t)}</text
              >
            {/each}
            {#each spans.ranks as lane, li (lane.rank)}
              {@const y0 = li * laneH}
              <text class="axis" x={TL - 8} y={y0 + 16} text-anchor="end">rank {lane.rank}</text>
              {#each waits.get(lane.rank) ?? [] as [a, b], wi (wi)}
                <rect
                  x={tx(a)}
                  y={y0 + 3}
                  width={Math.max(tx(b) - tx(a), 1)}
                  height={LANE - 6}
                  rx="3"
                  fill="url(#tm-hatch)"><title>rank {lane.rank} waiting {fmtSeconds(b - a)}</title></rect
                >
              {/each}
              {#each lane.spans as s, si (si)}
                {#if s.accumulated}
                  {@const parent = lane.spans.find(
                    (p) => p.depth === s.depth - 1 && !p.accumulated && p.start <= s.start && p.end >= s.start,
                  )}
                  {@const x0 = parent ? tx(parent.start) : tx(s.start)}
                  {@const w = parent
                    ? Math.min(
                        ((tx(parent.end) - tx(parent.start)) * s.seconds) / Math.max(parent.end - parent.start, 1e-9),
                        tx(parent.end) - tx(parent.start),
                      )
                    : Math.max(tx(s.seconds) - TL, 2)}
                  <rect
                    class="span"
                    x={x0}
                    y={y0 + LANE - 6 + (s.depth - 1) * SUB + 2}
                    width={Math.max(w, 2)}
                    height="4"
                    fill={colorOf(s.name)}><title>{spanTitle(s, lane.rank)}</title></rect
                  >
                {:else}
                  {@const w = Math.max(tx(s.end) - tx(s.start), 1)}
                  {@const h = s.depth === 0 ? LANE - 6 : SUB - 2}
                  {@const y = s.depth === 0 ? y0 + 3 : y0 + LANE - 3 + (s.depth - 1) * SUB}
                  <rect class="span" x={tx(s.start)} {y} width={w} height={h} rx="3" fill={colorOf(s.name)}
                    ><title>{spanTitle(s, lane.rank)}</title></rect
                  >
                  {#if s.depth === 0 && w > 60}
                    <text class="lab" x={tx(s.start) + 6} y={y0 + 16}
                      >{s.name}{w > 140 ? ` · ${fmtSeconds(s.seconds)}` : ''}</text
                    >
                  {/if}
                {/if}
              {/each}
            {/each}
          </svg>
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .tm {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .find {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
  }
  .sum {
    color: var(--muted);
    margin-right: 6px;
  }
  .sum b {
    color: var(--text);
    font-family: var(--mono);
    font-weight: 600;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: 0;
    background: var(--warn-bg);
    color: var(--warn);
    border-radius: 6px;
    padding: 4px 9px;
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .seg {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 2px;
    background: var(--panel);
  }
  .seglabel {
    font-size: 12px;
    color: var(--faint);
    padding: 0 8px 0 6px;
  }
  .seg button,
  .seg select {
    font: inherit;
    font-size: 12.5px;
    border: 0;
    background: none;
    color: var(--muted);
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
  }
  .seg button[aria-pressed='true'],
  .seg select.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  .box {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
    padding: 12px 14px;
    overflow-x: auto;
  }
  .head {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 6px;
    font-size: 12px;
    color: var(--faint);
  }
  .head b {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .bigplot {
    /* as wide as the table, never wider: the chart sizes itself to its box */
    width: 0;
    min-width: 100%;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
  }
  th {
    font-size: 10.5px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
    text-align: right;
    font-weight: 600;
    padding: 4px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  th:first-child,
  th.l {
    text-align: left;
  }
  td {
    padding: 5px 8px;
    border-bottom: 1px solid var(--grid);
    white-space: nowrap;
    vertical-align: middle;
  }
  td.num {
    text-align: right;
    font-family: var(--mono);
  }
  tr.row {
    cursor: pointer;
  }
  tr.row:hover td,
  tr.open td {
    background: var(--accent-soft);
  }
  .name {
    display: flex;
    align-items: center;
  }
  .chev {
    display: inline-block;
    width: 14px;
    color: var(--faint);
  }
  .tree {
    color: var(--faint);
    margin-right: 4px;
  }
  .sw {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    margin-right: 7px;
    flex: none;
  }
  .sw.hatch,
  .legend i.hatch {
    background: repeating-linear-gradient(45deg, var(--faint) 0 2px, var(--panel-2) 2px 4px);
  }
  .sw.empty {
    background: var(--grid);
    border: 1px solid var(--border);
  }
  .acc {
    font-size: 10.5px;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 0 5px;
    margin-left: 6px;
  }
  .bar {
    display: inline-block;
    height: 6px;
    border-radius: 3px;
    vertical-align: middle;
    margin-right: 6px;
  }
  tr.extra td {
    color: var(--muted);
  }
  td.spark {
    position: relative;
    padding: 2px 8px;
    /* takes the width the other columns leave, so the table never outgrows its box */
    width: 100%;
    min-width: 140px;
  }
  td.spark svg {
    display: block;
    cursor: crosshair;
  }
  td.spark svg :global(path),
  td.spark svg :global(line) {
    vector-effect: non-scaling-stroke;
  }
  .sess {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 3 2;
  }
  .at {
    stroke: var(--accent);
    stroke-width: 1;
    stroke-dasharray: 2 2;
  }
  .dot {
    fill: var(--panel);
    stroke: var(--accent);
    stroke-width: 1.5;
  }
  .tip {
    position: absolute;
    right: 8px;
    top: -18px;
    font-size: 11px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1px 6px;
    pointer-events: none;
    z-index: 2;
  }
  tr.big td {
    background: var(--panel-2);
    padding: 8px 10px 12px;
    white-space: normal;
  }
  .bighead {
    display: flex;
    align-items: baseline;
    gap: 12px;
    font-size: 12px;
    color: var(--muted);
    margin: 0 0 4px 4px;
  }
  .bighead b {
    color: var(--text);
  }
  .link {
    margin-left: auto;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    display: inline-flex;
    gap: 4px;
    align-items: center;
  }
  .stepper {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: 7px;
    font-size: 12px;
    color: var(--text);
  }
  .stepper button {
    border: 0;
    background: none;
    color: var(--muted);
    padding: 1px 8px;
    cursor: pointer;
    font: inherit;
  }
  .stepper button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .legend {
    margin-left: auto;
    display: inline-flex;
    gap: 14px;
    color: var(--muted);
  }
  .legend i {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
    vertical-align: -1px;
    margin-right: 5px;
  }
  .legend i.strip {
    height: 4px;
    vertical-align: 2px;
    background: var(--s6);
  }
  .timeline {
    width: 100%;
    min-width: 520px;
  }
  .timeline svg {
    display: block;
  }
  .grid {
    stroke: var(--grid);
  }
  .axis {
    font-family: var(--mono);
    font-size: 11px;
    fill: var(--muted);
  }
  .lab {
    font-family: var(--sans);
    font-size: 11px;
    fill: var(--panel);
    font-weight: 500;
    pointer-events: none;
  }
  .span:hover {
    opacity: 0.85;
  }
  .small {
    font-size: 13px;
  }
</style>
