<script lang="ts">
  import { onMount } from 'svelte';
  import Status from '../components/Status.svelte';
  import { api, type ArtifactVersion, type RunBrief } from '../lib/api';
  import { seriesVar } from '../lib/colors';
  import { fmtDate, fmtDuration } from '../lib/format';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const ROW = 24;
  const AXIS = 30;
  const MAX_ROWS = 1500;

  let width = $state(900);
  let now = $state(Date.now() / 1000);
  let artifacts = $state<ArtifactVersion[]>([]);
  let hover = $state<{ run: RunBrief; x: number; y: number } | null>(null);
  let drag = $state<{ x0: number; x1: number } | null>(null);
  let svg = $state<SVGSVGElement | null>(null);

  const colorBy = $derived(router.get('color', 'status'));
  const packed = $derived(router.get('layout') === 'packed');
  const LABEL = $derived(packed ? 120 : 210);

  onMount(() => {
    const timer = setInterval(() => (now = Date.now() / 1000), 5000);
    return () => clearInterval(timer);
  });
  $effect(() => {
    void app.runs?.version;
    api
      .artifacts(router.get('project') || null)
      .then((r) => (artifacts = r.artifacts))
      .catch(() => (artifacts = []));
  });

  const runs = $derived(
    app
      .visibleRuns()
      .filter((r) => r.started)
      .sort((a, b) => a.project.localeCompare(b.project) || (a.started ?? 0) - (b.started ?? 0))
      .slice(0, MAX_ROWS),
  );
  const endOf = (r: RunBrief) =>
    r.ended ?? (r.status === 'running' ? now : (r.heartbeat ?? (r.started ?? 0) + (r.duration ?? 0)));

  // Lanes: one per run, or packed so runs that never overlap share a lane (shows concurrency).
  const lanes = $derived.by(() => {
    const lane = new Map<string, number>();
    const headers: { project: string; lane: number }[] = [];
    let next = 0;
    let base = 0;
    let ends: number[] = [];
    const close = () => {
      if (packed) next = base + ends.length;
    };
    for (const r of runs) {
      if (!headers.length || headers[headers.length - 1].project !== r.project) {
        close();
        headers.push({ project: r.project, lane: next });
        base = ++next;
        ends = [];
      }
      if (!packed) {
        lane.set(r.key, next++);
        continue;
      }
      let k = ends.findIndex((e) => e <= (r.started ?? 0));
      if (k < 0) k = ends.push(0) - 1;
      ends[k] = endOf(r);
      lane.set(r.key, base + k);
    }
    close();
    return { lane, headers, count: Math.max(next, 1) };
  });

  const full = $derived.by((): [number, number] => {
    if (!runs.length) return [now - 3600, now];
    let lo = Infinity;
    let hi = -Infinity;
    for (const r of runs) {
      lo = Math.min(lo, r.started ?? Infinity);
      hi = Math.max(hi, endOf(r));
    }
    const pad = Math.max((hi - lo) * 0.02, 60);
    return [lo - pad, hi + pad];
  });
  const range = $derived.by((): [number, number] => {
    const z = router.get('tz');
    if (z) {
      const [a, b] = z.split('~').map(Number);
      if (Number.isFinite(a) && Number.isFinite(b) && b > a) return [a, b];
    }
    return full;
  });
  const plotW = $derived(Math.max(200, width - LABEL - 16));
  const xOf = (t: number) => LABEL + ((t - range[0]) / (range[1] - range[0])) * plotW;
  const tOf = (x: number) => range[0] + ((x - LABEL) / plotW) * (range[1] - range[0]);

  const ticks = $derived.by(() => {
    const span = range[1] - range[0];
    const steps = [60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 2 * 86400, 7 * 86400];
    const step = steps.find((s) => span / s <= Math.max(3, plotW / 110)) ?? 30 * 86400;
    const offset = new Date().getTimezoneOffset() * 60;
    const first = Math.ceil((range[0] - offset) / step) * step + offset;
    const out: { t: number; label: string; day: boolean }[] = [];
    for (let t = first; t <= range[1]; t += step) {
      const d = new Date(t * 1000);
      const midnight = d.getHours() === 0 && d.getMinutes() === 0;
      out.push({
        t,
        day: midnight,
        label:
          step >= 86400 || midnight
            ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
            : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
      });
    }
    return out;
  });

  const projects = $derived([...new Set(runs.map((r) => r.project))]);
  const groups = $derived([...new Set(runs.map((r) => r.group ?? ''))]);
  function color(r: RunBrief): string {
    if (colorBy === 'project') return seriesVar(projects.indexOf(r.project));
    if (colorBy === 'group') return r.group ? seriesVar(groups.indexOf(r.group)) : 'var(--faint)';
    return r.status === 'crashed' || r.status === 'killed'
      ? 'var(--err)'
      : r.status === 'running'
        ? 'var(--accent)'
        : r.status === 'lost'
          ? 'var(--warn)'
          : 'var(--s4)';
  }

  const made = $derived.by(() => {
    const byRun = new Map<string, ArtifactVersion[]>();
    for (const a of artifacts) for (const k of a.producers) byRun.set(k, [...(byRun.get(k) ?? []), a]);
    return byRun;
  });

  // Peak number of runs at once and total run time, for the summary line.
  const stats = $derived.by(() => {
    const events: [number, number][] = [];
    let total = 0;
    for (const r of runs) {
      events.push([r.started ?? 0, 1], [endOf(r), -1]);
      total += endOf(r) - (r.started ?? 0);
    }
    events.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    let cur = 0;
    let peak = 0;
    for (const [, d] of events) peak = Math.max(peak, (cur += d));
    return { peak, total };
  });

  const height = $derived(AXIS + lanes.count * ROW + 8);

  function pointerX(e: PointerEvent): number {
    const rect = svg!.getBoundingClientRect();
    return Math.min(Math.max(e.clientX - rect.left, LABEL), LABEL + plotW);
  }
  function down(e: PointerEvent) {
    if (e.button !== 0 || !svg) return;
    const x = pointerX(e);
    drag = { x0: x, x1: x };
    svg.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (drag) drag = { ...drag, x1: pointerX(e) };
  }
  function up() {
    if (!drag) return;
    const [a, b] = [Math.min(drag.x0, drag.x1), Math.max(drag.x0, drag.x1)];
    drag = null;
    if (b - a > 6) router.set({ tz: `${Math.round(tOf(a))}~${Math.round(tOf(b))}` });
  }
  function laneY(r: RunBrief) {
    return AXIS + (lanes.lane.get(r.key) ?? 0) * ROW;
  }
</script>

<div class="card panel">
  <div class="toolbar">
    <span class="muted">
      {runs.length} runs · up to {stats.peak} at once · {fmtDuration(stats.total)} of run time
    </span>
    <span class="grow"></span>
    <span class="label">Color</span>
    <div class="seg" role="group" aria-label="Color by">
      {#each ['status', 'project', 'group'] as c (c)}
        <button aria-pressed={colorBy === c} onclick={() => router.set({ color: c === 'status' ? null : c })}
          >{c}</button
        >
      {/each}
    </div>
    <div class="seg" role="group" aria-label="Layout">
      <button aria-pressed={!packed} onclick={() => router.set({ layout: null })}>one row per run</button>
      <button aria-pressed={packed} onclick={() => router.set({ layout: 'packed' })}>packed</button>
    </div>
    {#if router.get('tz')}<button class="btn" onclick={() => router.set({ tz: null })}>Reset zoom</button>{/if}
  </div>

  {#if !runs.length}
    <div class="empty">No runs to show. Adjust the query or pick a project.</div>
  {:else}
    <div class="wrap" bind:clientWidth={width}>
      <svg
        bind:this={svg}
        {width}
        {height}
        role="img"
        aria-label="Timeline of {runs.length} runs"
        onpointerdown={down}
        onpointermove={move}
        onpointerup={up}
        ondblclick={() => router.set({ tz: null })}
      >
        {#each ticks as t (t.t)}
          <line class="grid" class:day={t.day} x1={xOf(t.t)} x2={xOf(t.t)} y1={AXIS - 6} y2={height} />
          {#if !(now >= range[0] && now <= range[1] && Math.abs(xOf(t.t) - xOf(now)) < 90)}
            <text class="tick" x={xOf(t.t) + 4} y={16}>{t.label}</text>
          {/if}
        {/each}
        {#if now >= range[0] && now <= range[1]}
          <line class="now" x1={xOf(now)} x2={xOf(now)} y1={AXIS - 6} y2={height} />
          <text class="nowlabel" x={xOf(now) - 4} y={16} text-anchor="end">now</text>
        {/if}
        {#each lanes.headers as h (h.project)}
          <text class="project" x={8} y={AXIS + h.lane * ROW + 16}>{h.project}</text>
          <line class="sep" x1={0} x2={width} y1={AXIS + h.lane * ROW + 0.5} y2={AXIS + h.lane * ROW + 0.5} />
        {/each}
        {#each runs as r (r.key)}
          {@const y = laneY(r)}
          {@const x0 = Math.max(xOf(r.started ?? 0), LABEL)}
          {@const x1 = Math.min(xOf(endOf(r)), LABEL + plotW)}
          {#if !packed}
            <text class="name" class:dim={r.archived} x={20} y={y + 16}>{r.name}</text>
          {/if}
          {#if x1 >= LABEL && x0 <= LABEL + plotW}
            <g
              class="bar"
              role="button"
              tabindex="-1"
              onpointerenter={(e) => (hover = { run: r, x: e.clientX, y: e.clientY })}
              onpointermove={(e) => (hover = { run: r, x: e.clientX, y: e.clientY })}
              onpointerleave={() => (hover = null)}
              onpointerdown={(e) => e.stopPropagation()}
              onclick={() => router.go('runs', { cmp: r.key })}
              onkeydown={() => {}}
            >
              <rect
                x={x0}
                y={y + 5}
                width={Math.max(x1 - x0, 3)}
                height={ROW - 10}
                rx="3"
                fill={color(r)}
                opacity={r.status === 'running' ? 0.85 : 0.7}
              />
              {#if packed && x1 - x0 > 60}
                <text class="inbar" x={x0 + 5} y={y + 16}>{r.name}</text>
              {/if}
              {#if r.status === 'crashed' || r.status === 'killed'}
                <text class="cross" x={x1 + 3} y={y + 16}>✕</text>
              {/if}
              {#if r.alerts?.length}
                <circle class="alertdot" cx={x0 - 6} cy={y + ROW / 2} r="3" />
              {/if}
            </g>
            {#each made.get(r.key) ?? [] as a (`${a.name}:${a.version}`)}
              {@const ax = xOf(Math.min(Math.max(a.manifest.created ?? endOf(r), r.started ?? 0), endOf(r)))}
              <g class="art">
                <rect x={ax - 4} y={y + ROW / 2 - 4} width="8" height="8" transform="rotate(45 {ax} {y + ROW / 2})" />
                <title>{a.name}:v{a.version}</title>
              </g>
            {/each}
          {/if}
        {/each}
        {#if drag}
          <rect
            class="sel"
            x={Math.min(drag.x0, drag.x1)}
            y={AXIS - 6}
            width={Math.abs(drag.x1 - drag.x0)}
            height={height - AXIS + 6}
          />
        {/if}
      </svg>
    </div>
    <p class="hint">
      Drag across the chart to zoom, double-click to reset. Diamonds mark artifact versions a run produced; a dot before
      a bar means the run has health alerts. Click a bar to open the run.
    </p>
  {/if}
</div>

{#if hover}
  <div class="tip card" style="left:{hover.x + 14}px; top:{hover.y + 14}px">
    <div class="tname mono">{hover.run.name}</div>
    <div class="trow"><Status status={hover.run.status} /> <span class="faint">{hover.run.project}</span></div>
    <div class="trow">Started {fmtDate(hover.run.started)}</div>
    <div class="trow">Duration {fmtDuration(endOf(hover.run) - (hover.run.started ?? 0))}</div>
    {#if hover.run.group}<div class="trow faint">group {hover.run.group}</div>{/if}
    {#each hover.run.alerts ?? [] as a, i (i)}<div class="trow warn">{a.message}</div>{/each}
  </div>
{/if}

<style>
  .panel {
    overflow: hidden;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
  }
  .grow {
    flex: 1;
  }
  .muted {
    color: var(--muted);
  }
  .faint {
    color: var(--faint);
  }
  .wrap {
    width: 100%;
    overflow: hidden;
    user-select: none;
  }
  svg {
    display: block;
    touch-action: none;
  }
  .grid {
    stroke: var(--grid);
  }
  .grid.day {
    stroke: var(--border);
  }
  .tick {
    fill: var(--muted);
    font: 11.5px var(--mono);
  }
  .now {
    stroke: var(--accent);
    stroke-dasharray: 3 3;
  }
  .nowlabel {
    fill: var(--accent);
    font: 600 11.5px var(--sans);
  }
  .project {
    fill: var(--text);
    font: 600 12.5px var(--sans);
  }
  .sep {
    stroke: var(--border);
  }
  .name {
    fill: var(--muted);
    font: 12px var(--mono);
  }
  .name.dim {
    opacity: 0.5;
  }
  .bar {
    cursor: pointer;
  }
  .bar:hover rect {
    opacity: 1;
    stroke: var(--text);
    stroke-width: 1;
  }
  .inbar {
    fill: #fff;
    font: 600 11px var(--mono);
    pointer-events: none;
  }
  .cross {
    fill: var(--err);
    font: 700 11px var(--sans);
  }
  .alertdot {
    fill: var(--warn);
  }
  .art rect {
    fill: var(--panel);
    stroke: var(--text);
    stroke-width: 1.3;
  }
  .sel {
    fill: var(--accent-soft);
    opacity: 0.6;
    stroke: var(--accent);
  }
  .hint {
    color: var(--faint);
    font-size: 12.5px;
    margin: 0;
    padding: 10px 14px 14px;
  }
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }
  .tip {
    position: fixed;
    z-index: 20;
    padding: 10px 12px;
    box-shadow: var(--lift);
    font-size: 12.5px;
    max-width: 340px;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .tname {
    font-weight: 600;
  }
  .trow {
    color: var(--muted);
  }
  .warn {
    color: var(--warn);
  }
</style>
