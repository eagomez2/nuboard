<script lang="ts">
  import { onMount } from 'svelte';
  import LineChart, { type CursorValue } from '../components/LineChart.svelte';
  import Marker from '../components/Marker.svelte';
  import SmallChart from '../components/SmallChart.svelte';
  import { api, type Alert, type ChartData } from '../lib/api';
  import Icon from '../components/Icon.svelte';
  import { seriesColor } from '../lib/colors';
  import { defaultMetric, fmtAgo, fmtDuration, fmtNum, fmtValue, lowerIsBetter } from '../lib/format';
  import { onLive } from '../lib/live';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import { encodeSpec } from '../lib/chartspec';
  import { baselineLines } from '../lib/baselines';
  import { appendToReport, askReport } from '../lib/reports.svelte';

  const MAX_LINES = 60;

  // ---- view state (URL) and preferences (localStorage) ----
  const xKind = $derived(router.get('x', 'step'));
  const smoothing = $derived(Number(router.get('smooth', String(prefs.get('smooth', 0.6)))));
  const showRaw = $derived(router.get('raw', '1') === '1');
  const showDots = $derived(router.get('dots', '1') === '1');
  const robust = $derived(router.get('robust', '1') === '1');
  const logY = $derived(router.get('log') === '1');
  const showBase = $derived(router.get('base', '1') === '1');
  const showBands = $derived(router.get('bands', '1') === '1');
  const zoom = $derived.by((): [number, number] | null => {
    const z = router.get('zoom');
    if (!z) return null;
    const [a, b] = z.split('~').map(Number);
    return Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null;
  });

  const runs = $derived(app.visibleRuns());
  const groupBy = $derived(
    router.get('group') === 'none' ? null : router.get('group') || app.runs?.query.group_by || null,
  );
  const agg = $derived(router.get('agg') || app.runs?.query.agg || 'std');
  const hasBaselines = $derived(runs.some((r) => r.baselines?.length));
  const runKeys = $derived(groupBy ? runs.map((r) => r.key) : runs.slice(0, MAX_LINES).map((r) => r.key));

  let metrics = $state<string[]>([]);
  let focusData = $state<ChartData | null>(null);
  // Offer the Ranges toggle only when something draws a range around a curve.
  const hasRanges = $derived(
    (!!groupBy && agg !== 'none') || !!focusData?.series.some((s) => s.band || (s.n ?? 1) > 1),
  );
  let loading = $state(false);
  let tick = $state(0);
  let hidden = $state(new Set<string>());
  let highlight = $state<string | null>(null);
  let cursorX = $state<number | null>(null);
  let cursorValues = $state<CursorValue[]>([]);
  let pinned = $state(false);

  $effect(() => {
    const keys = runKeys;
    if (!keys.length) {
      metrics = [];
      return;
    }
    api.metrics(keys).then((r) => (metrics = r.metrics.map((m) => m.name)));
  });

  const focus = $derived.by(() => {
    const m = router.get('metric');
    if (m && metrics.includes(m)) return m;
    return defaultMetric(metrics);
  });
  const tabs = $derived.by(() => {
    const prefix = focus.split('/')[0];
    const same = metrics.filter((m) => m.split('/')[0] === prefix || /loss/.test(m));
    const list = [...new Set([...same, ...metrics])].slice(0, 6);
    return list.includes(focus) || !focus ? list : [...list.slice(0, 5), focus];
  });

  // Colors are stable per label across all charts, assigned in focus-chart order.
  const colorIndex = $derived(new Map((focusData?.series ?? []).map((s, i) => [s.label, i])));
  const colorOf = (label: string, i: number) => seriesColor(colorIndex.get(label) ?? i);

  $effect(() => {
    if (!focus || !runKeys.length) {
      focusData = null;
      return;
    }
    void tick;
    const ctrl = new AbortController();
    loading = true;
    api
      .chart({
        runs: runKeys,
        metric: focus,
        x: xKind,
        group: groupBy,
        agg,
        // a zoomed chart also gets half a view on each side, so smoothing is warmed up at the
        // edges and a small pan or zoom out shows data before the next fetch arrives
        points: zoom ? 2800 : 1400,
        xmin: zoom ? zoom[0] - (zoom[1] - zoom[0]) / 2 : undefined,
        xmax: zoom ? zoom[1] + (zoom[1] - zoom[0]) / 2 : undefined,
        signal: ctrl.signal,
      })
      .then((d) => {
        focusData = d;
        loading = false;
      })
      .catch((e) => {
        if (e.name !== 'AbortError') loading = false;
      });
    return () => ctrl.abort();
  });

  // Live: new points redraw the charts (at most every 2 s) unless updates are paused or you
  // are working with the chart (zoomed, pinned or hovering it); then an Update button
  // waits, and it applies by itself once you stop hovering a chart that is not zoomed or pinned.
  let live = $state(prefs.get('chartsLive', true));
  let stale = $state(false);
  const interacting = $derived(zoom !== null || pinned || cursorX !== null);
  function setLive(on: boolean) {
    live = on;
    prefs.set('chartsLive', on);
  }
  function update() {
    stale = false;
    tick++;
  }
  $effect(() => {
    if (stale && live && !interacting) update();
  });

  onMount(() => {
    let last = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    return onLive('data', (changed) => {
      if (!changed.some((k) => runKeys.includes(k))) return;
      if (!live || interacting) {
        stale = true;
        return;
      }
      const wait = Math.max(0, 2000 - (Date.now() - last));
      clearTimeout(timer);
      timer = setTimeout(() => {
        last = Date.now();
        tick++;
      }, wait);
    });
  });

  // ---- health alerts (stored at compaction, computed live for running runs) ----
  let alerts = $state<{ key: string; name: string; alert: Alert }[]>([]);
  $effect(() => {
    const keys = runs.slice(0, 200).map((r) => r.key);
    void tick;
    if (!keys.length) {
      alerts = [];
      return;
    }
    api
      .alerts(keys)
      .then((res) => {
        alerts = Object.entries(res.alerts).flatMap(([key, list]) =>
          list.map((alert) => ({ key, name: app.runByKey(key)?.name ?? key, alert })),
        );
      })
      .catch(() => (alerts = []));
  });
  const regions = $derived(
    xKind !== 'step'
      ? []
      : alerts
          .filter((a) => a.alert.metric === focus && a.alert.kind !== 'nonfinite' && runKeys.includes(a.key))
          .map((a) => ({
            x0: a.alert.step,
            x1: a.alert.end_step ?? a.alert.step,
            label: `${a.alert.kind} · ${a.name}`,
          })),
  );
  function showAlert(a: { key: string; alert: Alert }) {
    const span = Math.max((a.alert.end_step ?? a.alert.step) - a.alert.step, 200);
    router.set({
      metric: a.alert.metric,
      x: null,
      zoom: `${Math.max(0, a.alert.step - 3 * span)}~${(a.alert.end_step ?? a.alert.step) + 3 * span}`,
    });
  }

  // ---- derived summaries ----
  const lower = $derived(lowerIsBetter(focus));
  const best = $derived.by(() => {
    const finite = (focusData?.series ?? []).filter((s) => s.last !== null && !s.nonfinite);
    if (!finite.length) return null;
    return finite.reduce((a, b) => ((lower ? b.last! < a.last! : b.last! > a.last!) ? b : a));
  });
  const running = $derived(runs.filter((r) => r.status === 'running'));
  const lastBeat = $derived(Math.max(0, ...running.map((r) => r.heartbeat ?? 0)));
  const nonfinite = $derived(runs.filter((r) => r.nonfinite.length));
  // ---- full screen for the focus chart (with the inspector) ----
  let focusEl = $state<HTMLElement>();
  let full = $state(false);
  let innerHeight = $state(900);
  async function toggleFull() {
    if (full) {
      full = false;
      if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
      return;
    }
    full = true; // the overlay works even where the Fullscreen API is blocked
    await focusEl?.requestFullscreen?.().catch(() => {});
  }
  onMount(() => {
    const sync = () => {
      if (!document.fullscreenElement && full) full = false;
    };
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  });

  // ---- saving the focus chart to a report: a PNG snapshot plus the view to draw it live ----
  function snapshot(): string | null {
    const src = focusEl?.querySelector<HTMLCanvasElement>('.main canvas');
    if (!src) return null;
    const css = getComputedStyle(focusEl!);
    const dpr = src.width / Math.max(1, src.clientWidth);
    const labels = (focusData?.series ?? []).filter((x) => !hidden.has(x.label));
    const perRow = Math.max(1, Math.floor(src.clientWidth / 220));
    const legendH = Math.ceil(labels.length / perRow) * 20 + 8;
    const out = document.createElement('canvas');
    out.width = src.width;
    out.height = src.height + (36 + legendH) * dpr;
    const ctx = out.getContext('2d')!;
    ctx.fillStyle = css.getPropertyValue('--panel').trim() || '#fff';
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.scale(dpr, dpr);
    ctx.fillStyle = css.getPropertyValue('--text').trim() || '#111';
    ctx.font = `600 14px ${css.getPropertyValue('--mono') || 'monospace'}`;
    ctx.fillText(focus + (groupBy ? `  ·  grouped by ${groupBy}` : ''), 12, 22);
    ctx.drawImage(src, 0, 36, src.clientWidth, src.clientHeight);
    ctx.font = '12px system-ui, sans-serif';
    labels.forEach((x, i) => {
      const cx = 12 + (i % perRow) * 220;
      const cy = 36 + src.clientHeight + 16 + Math.floor(i / perRow) * 20;
      ctx.fillStyle = colorOf(x.label, i);
      ctx.beginPath();
      ctx.arc(cx + 4, cy - 4, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = css.getPropertyValue('--muted').trim() || '#555';
      const name = x.label.length > 30 ? x.label.slice(0, 29) + '…' : x.label;
      ctx.fillText(name, cx + 14, cy);
    });
    return out.toDataURL('image/png');
  }
  let savingChart = $state(false);
  async function addChartToReport() {
    const project = app.runByKey(runKeys[0])?.project ?? router.get('project');
    const png = snapshot();
    if (!project || !png || !focus) return;
    if (full) await toggleFull(); // dialogs are not shown over a full-screen element
    const res = await askReport(
      project,
      `${focus}${groupBy ? ` by ${groupBy}` : ''}`,
      `The chart as shown now; reports draw it live and keep a PNG copy for exports.`,
    );
    if (!res) return;
    savingChart = true;
    try {
      const shot = await api.saveSnapshot(project, res.name, png);
      if (!shot.path) return;
      const spec = encodeSpec({
        metric: focus,
        runs: runKeys,
        x: xKind,
        group: groupBy,
        agg,
        smooth: smoothing,
        raw: showRaw,
        robust,
        log: logY,
        base: showBase,
        bands: showBands,
        zoom,
        hidden: [...hidden],
      });
      const caption = res.caption.replace(/[[\]\n]/g, ' ');
      await appendToReport(project, res.name, `![${caption}](${shot.path} "chart:${spec}")`);
    } finally {
      savingChart = false;
    }
  }

  // ---- the grid of small charts: columns and rows per page, like the Media page ----
  const gridCols = $derived(Number(router.get('ccols', String(prefs.get('ccols', 0)))) || 0); // 0: fit
  const gridRows = $derived(Number(router.get('crows', String(prefs.get('crows', 0)))) || 0); // 0: all
  function setGrid(k: 'ccols' | 'crows', v: string) {
    prefs.set(k, Number(v));
    router.set({ [k]: v === '0' ? null : v });
  }
  let gridWidth = $state(1200);
  const perRow = $derived(gridCols || Math.max(1, Math.floor((gridWidth + 14) / (330 + 14))));
  let gridPages = $state<Record<string, number>>({});

  // Regex filter of the All scalars grid (as in TensorBoard); an invalid pattern matches as plain text.
  const metricFind = $derived(router.get('cfind'));
  const metricRe = $derived.by(() => {
    if (!metricFind) return null;
    try {
      return new RegExp(metricFind, 'i');
    } catch {
      return new RegExp(metricFind.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    }
  });
  const shownMetrics = $derived(metricRe ? metrics.filter((m) => metricRe.test(m)) : metrics);
  // Sections fold like on the Media page; the choice is kept in localStorage per prefix.
  // Unset, all are open when there are few, else the first three; a filter opens every match.
  let folded = $state<Record<string, boolean>>(prefs.get('chartFolds', {}));
  function sectionOpen(prefix: string, i: number): boolean {
    if (metricFind) return true;
    return folded[prefix] === undefined ? sections.length <= 6 || i < 3 : !folded[prefix];
  }
  function setFolded(next: Record<string, boolean>) {
    folded = next;
    prefs.set('chartFolds', next);
  }
  const sections = $derived.by(() => {
    const map = new Map<string, string[]>();
    for (const m of shownMetrics) {
      const p = m.includes('/') ? m.split('/')[0] : 'other';
      if (!map.has(p)) map.set(p, []);
      map.get(p)!.push(m);
    }
    return [...map.entries()];
  });

  // Without a hover, the inspector shows each shown series' latest value (in the zoomed range).
  const lastValues = $derived(
    (focusData?.series ?? []).flatMap((s, i) => {
      if (hidden.has(s.label)) return [];
      for (let k = s.y.length - 1; k >= 0; k--)
        if (Number.isFinite(s.y[k]) && (!zoom || s.x[k] <= zoom[1]))
          return [{ series: i, label: s.label, value: s.y[k], lo: s.lo[k], hi: s.hi[k], x: s.x[k] }];
      return [];
    }),
  );
  // In the inspector's order: lowest first when lower is better
  const baseRows = $derived(
    showBase
      ? baselineLines(focusData?.series ?? [], hidden).sort((a, b) => (lower ? a.value - b.value : b.value - a.value))
      : [],
  );
  const inspector = $derived.by(() => {
    const list = [...(cursorX === null ? lastValues : cursorValues)].sort((a, b) =>
      lower ? a.value - b.value : b.value - a.value,
    );
    const vals = list.map((v) => v.value);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    return list.map((v) => ({
      ...v,
      frac: max > min ? (lower ? (max - v.value) / (max - min) : (v.value - min) / (max - min)) * 0.85 + 0.15 : 1,
    }));
  });

  // Any metric can be the x axis (matched by step); counters like tokens or epochs come first.
  const xMetric = $derived(xKind.startsWith('metric:') ? xKind.slice(7) : null);
  const xCandidates = $derived.by(() => {
    const counter = (m: string) => /token|epoch|sample|example|seen|images|flop|step|iter/i.test(m);
    return [...metrics.filter(counter), ...metrics.filter((m) => !counter(m))];
  });

  // The x readout as a name (may be a long metric, so it truncates) and a value (never truncated).
  function fmtX(x: number | null): { name: string; value: string } {
    if (x === null) return { name: '', value: '—' };
    if (xKind === 'time') return { name: '', value: new Date(x * 1000).toLocaleTimeString() };
    if (xKind === 'relative' || xKind === 'active') return { name: '', value: fmtDuration(x) };
    if (xMetric) return { name: xMetric, value: fmtNum(x) };
    return { name: 'Step', value: Math.round(x).toLocaleString() };
  }
  const xRead = $derived.by(() => {
    if (cursorX !== null) return { prefix: '', ...fmtX(cursorX) };
    if (!lastValues.length) return { prefix: '', name: '', value: '—' };
    const last = fmtX(Math.max(...lastValues.map((v) => v.x)));
    return { prefix: 'Latest ·', ...last, name: last.name === 'Step' ? 'step' : last.name };
  });
  function setSmooth(v: number) {
    prefs.set('smooth', v);
    router.set({ smooth: v });
  }
  function toggleSeries(label: string) {
    const next = new Set(hidden);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    hidden = next;
  }
  const seriesLabels = $derived((focusData?.series ?? []).map((s) => s.label));
  // show only this series; soloing the one already alone brings all back
  function soloSeries(label: string) {
    const alone = !hidden.has(label) && seriesLabels.every((l) => l === label || hidden.has(l));
    hidden = alone ? new Set() : new Set(seriesLabels.filter((l) => l !== label));
  }
  function chipClick(e: MouseEvent, label: string) {
    if (e.altKey || e.metaKey || e.ctrlKey) soloSeries(label);
    else toggleSeries(label);
  }
  const groupOptions = $derived.by(() => {
    const keys = new Map<string, Set<string>>();
    for (const r of runs)
      for (const [k, v] of Object.entries(r.config)) {
        if (!keys.has(k)) keys.set(k, new Set());
        keys.get(k)!.add(JSON.stringify(v));
      }
    return [...keys.entries()].filter(([, s]) => s.size > 1 && s.size < runs.length).map(([k]) => `config.${k}`);
  });
  // ---- metric picker for the focus chart: every scalar, searchable ----
  let pickOpen = $state(false);
  let pickFind = $state('');
  let pickIndex = $state(0);
  let pickEl = $state<HTMLElement>();
  let pickInput = $state<HTMLInputElement>();
  $effect(() => {
    if (pickOpen) pickInput?.focus();
  });
  const pickList = $derived.by(() => {
    const q = pickFind.trim().toLowerCase();
    return (q ? metrics.filter((m) => m.toLowerCase().includes(q)) : metrics).slice(0, 300);
  });
  function pick(m: string) {
    router.set({ metric: m, zoom: null });
    pickOpen = false;
    pickFind = '';
  }
  function pickKey(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = pickList.length;
      if (n) pickIndex = (pickIndex + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
      pickEl?.querySelector(`[data-i="${pickIndex}"]`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && pickList[pickIndex]) pick(pickList[pickIndex]);
    else if (e.key === 'Escape') {
      e.stopPropagation();
      pickOpen = false;
    }
  }
  $effect(() => {
    if (!pickOpen) return;
    const close = (e: PointerEvent) => {
      if (!pickEl?.contains(e.target as Node)) pickOpen = false;
    };
    window.addEventListener('pointerdown', close, true);
    return () => window.removeEventListener('pointerdown', close, true);
  });

  // ---- legend: with many series, a filter and only the first few chips until expanded ----
  const LEGEND_MAX = 12;
  const LEGEND_SHOWN = 10;
  let legendFind = $state('');
  let legendOpen = $state(false);
  // A series matches on its label, its runs' names and their config, such as `lr=3e-4`
  const seriesText = $derived.by(() => {
    const byKey = new Map(runs.map((r) => [r.key, r]));
    return new Map(
      (focusData?.series ?? []).map((s) => {
        const parts = [s.label];
        for (const key of s.runs) {
          const r = byKey.get(key);
          if (!r) continue;
          parts.push(r.name);
          for (const [k, v] of Object.entries(r.config))
            parts.push(`${k}=${fmtValue(v)}`, `${k.split('.').slice(-1)[0]}=${fmtValue(v)}`);
        }
        return [s.label, parts.join('\n').toLowerCase()];
      }),
    );
  });
  const legendMatch = (label: string) => {
    const q = legendFind.trim().toLowerCase();
    return !q || (seriesText.get(label) ?? label.toLowerCase()).includes(q);
  };
  const legendItems = $derived.by(() => {
    const all = (focusData?.series ?? []).map((s, i) => ({ s, i }));
    if (all.length <= LEGEND_MAX) return all;
    const shown = all.filter(({ s }) => legendMatch(s.label));
    return legendFind.trim() || legendOpen ? shown : shown.slice(0, LEGEND_SHOWN);
  });
  const legendMatching = $derived(seriesLabels.filter(legendMatch));
  const groupLabel = (g: string | null) => (g ? g.split('.').slice(-1)[0] : '');
  const seriesTitle = (label: string) => (groupBy ? `${groupLabel(groupBy)} ${label}` : label);
</script>

<svelte:window
  bind:innerHeight
  onkeydown={(e) => {
    if (e.key === 'Escape' && full) toggleFull();
  }}
/>

<!-- A series name: when grouped, the (often long) group key shrinks before the value that tells series apart. -->
{#snippet seriesName(label: string, cls: string)}
  <span class="sname {cls}" title={seriesTitle(label)}>
    {#if groupBy}<span class="gkey">{groupLabel(groupBy)}</span>{/if}<span class="gval">{label}</span>
  </span>
{/snippet}

{#if !runs.length}
  <div class="card empty">No runs to plot. Select runs on the Runs page, or change the query.</div>
{:else}
  <section class="stats">
    <div class="card stat">
      <div class="label lrow">
        <span class="trunc" title="Best {focus || 'metric'}">Best {focus || 'metric'}</span>
        <span class="faint keep">({lower ? 'Lowest' : 'Highest'} last)</span>
      </div>
      <div class="big mono">{best ? fmtNum(best.last) : '—'}</div>
      {#if best}
        <div class="sub nowrap">
          <Marker index={colorIndex.get(best.label) ?? 0} color={colorOf(best.label, 0)} />
          {@render seriesName(best.label, '')}
          {#if best.n}<span class="keep">· mean of {best.n}</span>{/if}
        </div>
      {/if}
    </div>
    <div class="card stat">
      <div class="label">Running</div>
      <div class="big mono">{running.length} <span class="faint">/ {runs.length}</span></div>
      <div class="sub">{running.length ? `Last heartbeat ${fmtAgo(lastBeat)} · updates live` : 'No live runs'}</div>
    </div>
    <div class="card stat">
      <div class="label">Non-finite values</div>
      <div class="big mono" class:errc={nonfinite.length}>{nonfinite.length}</div>
      <div class="sub nowrap">
        {#if nonfinite.length}
          {#each nonfinite.slice(0, 2) as r (r.key)}<span
              class="chip chip-err nf"
              title="{r.name}: {r.nonfinite.join(', ')}"
              ><span class="trunc nfname">{r.name}:</span><span class="trunc nfmetric">{r.nonfinite[0]}</span></span
            >{/each}
        {:else}No NaN or Inf logged{/if}
      </div>
    </div>
    <div class="card stat">
      <div class="label">Shown</div>
      <div class="big mono">{runKeys.length} <span class="faint">run{runKeys.length === 1 ? '' : 's'}</span></div>
      <div class="sub nowrap">
        {#if groupBy}
          <span class="trunc" title="Grouped by {groupBy}">Grouped by {groupBy}</span>
        {:else}
          {runs.length > MAX_LINES ? `First ${MAX_LINES} of ${runs.length}; group to see all` : 'One line per run'}
        {/if}
      </div>
    </div>
  </section>

  <section class="controls">
    <div class="legend">
      {#if seriesLabels.length > 1}
        <div class="seg showall" role="group" aria-label="Show series">
          <button aria-pressed={hidden.size === 0} title="Show every series" onclick={() => (hidden = new Set())}
            >All</button
          >
          <button
            aria-pressed={seriesLabels.every((l) => hidden.has(l))}
            title="Hide every series, then click chips to add them back"
            onclick={() => (hidden = new Set(seriesLabels))}>None</button
          >
        </div>
      {/if}
      {#if seriesLabels.length > LEGEND_MAX}
        <input
          class="input sm mono legendfind"
          placeholder="Filter series, e.g. lr=3e-4"
          aria-label="Filter series"
          bind:value={legendFind}
          onkeydown={(e) => e.key === 'Escape' && (legendFind = '')}
        />
        {#if legendFind.trim()}
          <span class="faint small legendcount">{legendMatching.length} of {seriesLabels.length}</span>
          <button
            class="btn btn-ghost sm"
            disabled={!legendMatching.length}
            title="Show only the series that match, hide the rest"
            onclick={() => (hidden = new Set(seriesLabels.filter((l) => !legendMatching.includes(l))))}
            >Only these</button
          >
        {/if}
      {/if}
      {#each legendItems as { s, i } (s.label)}
        <button
          class="chip legend-chip"
          class:off={hidden.has(s.label)}
          onclick={(e) => chipClick(e, s.label)}
          ondblclick={() => soloSeries(s.label)}
          onmouseenter={() => (highlight = s.label)}
          onmouseleave={() => (highlight = null)}
          title={`${s.runs.length > 1 ? s.runs.join('\n') : s.runs[0]}\n\nClick to hide · double-click or Alt-click to solo`}
        >
          <Marker index={i} color={colorOf(s.label, i)} />
          {@render seriesName(s.label, 'lab')}
          {#if s.n}<span class="faint">n={s.n}</span>{/if}
          <span class="mono" class:errc={s.nonfinite}>· {s.nonfinite ? 'NaN' : fmtNum(s.last)}</span>
        </button>
      {/each}
      {#if seriesLabels.length > LEGEND_MAX && !legendFind.trim()}
        <button class="btn btn-ghost sm legendmore" onclick={() => (legendOpen = !legendOpen)}
          >{legendOpen ? 'Show fewer' : `+${seriesLabels.length - LEGEND_SHOWN} more`}</button
        >
      {/if}
    </div>
    <div class="knobrows">
      <div class="knobs">
        <select
          class="input sm groupsel"
          value={router.get('group') || (groupBy ?? 'none')}
          title={groupBy ? `group by ${groupBy}` : 'no grouping'}
          onchange={(e) => router.set({ group: (e.currentTarget as HTMLSelectElement).value })}
          aria-label="Group by"
        >
          <option value="none">No grouping</option>
          {#each [...new Set([...(groupBy ? [groupBy] : []), ...groupOptions])] as g (g)}<option value={g}
              >Group by {g}</option
            >{/each}
        </select>
        {#if groupBy}
          <select
            class="input sm"
            value={agg}
            onchange={(e) => router.set({ agg: (e.currentTarget as HTMLSelectElement).value })}
            aria-label="Band"
          >
            <option value="std">Mean ± std</option>
            <option value="sem">Mean ± sem</option>
            <option value="minmax">Mean · min–max</option>
            <option value="median">Median · min–max</option>
            <option value="none">Mean only</option>
          </select>
        {/if}
        <div class="seg" role="group" aria-label="X axis">
          {#each [['step', 'Step'], ['time', 'Wall time'], ['relative', 'Relative'], ['active', 'Active time']] as [k, label] (k)}
            <button aria-pressed={xKind === k} onclick={() => router.set({ x: k === 'step' ? null : k, zoom: null })}
              >{label}</button
            >
          {/each}
        </div>
        <select
          class="input sm mono xmetric"
          class:on={xMetric !== null}
          value={xMetric ?? ''}
          onchange={(e) => {
            const v = (e.currentTarget as HTMLSelectElement).value;
            router.set({ x: v ? `metric:${v}` : null, zoom: null });
          }}
          aria-label="X axis scalar"
          title="Plot against another scalar, matched by step"
        >
          <option value="">X by scalar…</option>
          {#each xCandidates as m (m)}<option value={m}>X = {m}</option>{/each}
        </select>
      </div>
      <div class="knobs">
        <label class="smooth"
          >Smooth
          <input
            type="range"
            min="0"
            max="0.99"
            step="0.01"
            value={smoothing}
            oninput={(e) => setSmooth(Number((e.currentTarget as HTMLInputElement).value))}
          />
          <span class="mono">{smoothing.toFixed(2)}</span>
        </label>
        <label class="tg"
          ><button
            class="switch"
            role="switch"
            aria-checked={showRaw}
            aria-label="Show raw"
            onclick={() => router.set({ raw: showRaw ? '0' : null })}
          ></button>Raw</label
        >
        {#if hasRanges}
          <label
            class="tg"
            title="Shade the range around each curve: the group's band, logged low/high bounds or the min–max across ranks"
            ><button
              class="switch"
              role="switch"
              aria-checked={showBands}
              aria-label="Ranges"
              onclick={() => router.set({ bands: showBands ? '0' : null })}
            ></button>Ranges</label
          >
        {/if}
        <label class="tg" title="A dot on each curve at the logged point under the cursor (or the pinned one)"
          ><button
            class="switch"
            role="switch"
            aria-checked={showDots}
            aria-label="Points"
            onclick={() => router.set({ dots: showDots ? '0' : null })}
          ></button>Points</label
        >
        {#if hasBaselines}
          <label class="tg" title="Dashed lines at the reference values set with add_scalar_baseline"
            ><button
              class="switch"
              role="switch"
              aria-checked={showBase}
              aria-label="Baseline"
              onclick={() => router.set({ base: showBase ? '0' : null })}
            ></button>Baseline</label
          >
        {/if}
        <label
          class="tg"
          title="Fit the y-axis to the 1st–99th percentile of the values, so a few spikes (such as a huge first loss) don't flatten the curves. Off: the axis fits every point."
          ><button
            class="switch"
            role="switch"
            aria-checked={robust}
            aria-label="Ignore outliers"
            onclick={() => router.set({ robust: robust ? '0' : null })}
          ></button>Ignore outliers</label
        >
        <label class="tg"
          ><button
            class="switch"
            role="switch"
            aria-checked={logY}
            aria-label="Log y"
            onclick={() => router.set({ log: logY ? null : '1' })}
          ></button>Log y</label
        >
        <label
          class="tg"
          title="Draw new points as runs log them. Off, or while you zoom, pin or hover a chart, an Update button appears instead."
          ><button class="switch" role="switch" aria-checked={live} aria-label="Live" onclick={() => setLive(!live)}
          ></button>Live</label
        >
      </div>
    </div>
  </section>

  <section class="focus" class:full bind:this={focusEl}>
    <div class="card main">
      <div class="tabs">
        {#each tabs as m (m)}
          <button
            class="mono tab"
            aria-pressed={m === focus}
            title={m}
            onclick={() => router.set({ metric: m, zoom: null })}>{m}</button
          >
        {/each}
        {#if metrics.length > tabs.length}
          <div class="picker" bind:this={pickEl}>
            <button
              class="btn btn-ghost sm"
              aria-expanded={pickOpen}
              title="Pick any of the {metrics.length} scalars"
              onclick={() => {
                pickOpen = !pickOpen;
                pickIndex = 0;
              }}><Icon name="search" size={14} /> All {metrics.length}</button
            >
            {#if pickOpen}
              <div class="card pickpop" role="dialog" aria-label="Pick a scalar">
                <input
                  class="input sm mono"
                  placeholder="Search scalars"
                  aria-label="Search scalars"
                  bind:this={pickInput}
                  bind:value={pickFind}
                  oninput={() => (pickIndex = 0)}
                  onkeydown={pickKey}
                />
                <div class="picklist" role="listbox" aria-label="Scalars">
                  {#each pickList as m, i (m)}
                    <button
                      class="pickopt mono"
                      role="option"
                      data-i={i}
                      aria-selected={i === pickIndex}
                      class:on={m === focus}
                      title={m}
                      onmouseenter={() => (pickIndex = i)}
                      onclick={() => pick(m)}>{m}</button
                    >
                  {:else}
                    <p class="faint small">No scalar matches “{pickFind}”.</p>
                  {/each}
                </div>
                {#if pickList.length === 300}<p class="faint small">Showing the first 300; type to narrow.</p>{/if}
              </div>
            {/if}
          </div>
        {/if}
        <span class="note">
          {#if stale}<button class="btn sm newdata" title="New points were logged; draw them" onclick={update}
              >New data · Update</button
            >{/if}
          {#if zoom}<button class="btn btn-ghost sm" onclick={() => router.set({ zoom: null })}>Reset zoom</button>{/if}
          {loading
            ? 'loading…'
            : groupBy
              ? agg === 'std'
                ? 'mean ± std'
                : agg
              : 'Drag or Ctrl+wheel to zoom · Shift+drag to pan · double-click to reset'}
          <button
            class="btn btn-ghost sm icon-btn"
            title="Add this chart to a report"
            aria-label="Add chart to a report"
            disabled={savingChart || !focusData}
            onclick={addChartToReport}><Icon name="bookmark" size={15} /></button
          >
          <button
            class="btn btn-ghost sm icon-btn"
            title={full ? 'Exit full screen (Esc)' : 'Full screen'}
            aria-label={full ? 'Exit full screen' : 'Full screen'}
            aria-pressed={full}
            onclick={toggleFull}><Icon name={full ? 'shrink' : 'expand'} size={15} /></button
          >
        </span>
      </div>
      <LineChart
        data={focusData}
        {smoothing}
        {showRaw}
        {showBands}
        {robust}
        {logY}
        {zoom}
        {hidden}
        {highlight}
        {colorOf}
        themeVersion={app.themeVersion}
        height={full ? Math.max(320, innerHeight - (alerts.length ? 190 : 120)) : 420}
        onCursor={(x, v) => {
          if (!pinned) {
            cursorX = x;
            cursorValues = v;
          }
        }}
        onPin={() => (pinned = !pinned)}
        onZoom={(r) => router.set({ zoom: r ? `${r[0]}~${r[1]}` : null })}
        {regions}
        markers={showDots}
        {pinned}
        baselines={showBase}
      />
      {#if alerts.length}
        <div class="alerts" aria-label="Health alerts">
          <span class="label">Alerts</span>
          {#each alerts.slice(0, 12) as a, i (i)}
            <button
              class="alert"
              class:err={a.alert.severity === 'error'}
              title="{a.name}{a.alert.rank ? ` · rank ${a.alert.rank}` : ''}: {a.alert.message}"
              onclick={() => showAlert(a)}
            >
              <Icon name="alert" size={13} />
              <span class="mono aname">{a.name}</span>
              <span class="amsg">{a.alert.message}</span>
              {#if a.alert.rank}<span class="mono faint keep">Rank {a.alert.rank}</span>{/if}
            </button>
          {/each}
          {#if alerts.length > 12}<span class="faint">+{alerts.length - 12} more</span>{/if}
        </div>
      {/if}
    </div>
    <aside class="card inspector">
      <div class="ih">
        <span class="label">Inspector</span><span class="faint"
          >{pinned ? 'Pinned · click chart to release' : 'Hover · click to pin'}</span
        >
      </div>
      <div class="ix mono">
        {#if xRead.prefix}<span class="keep">{xRead.prefix}</span>{/if}
        {#if xRead.name}<span class="trunc" title={xRead.name}>{xRead.name}</span>{/if}
        <span class="keep">{xRead.value}</span>
      </div>
      <div class="im">
        <span class="mono trunc" title={focus}>{focus}</span><span class="faint keep"
          >{lower ? 'Lowest first' : 'Highest first'}</span
        >
      </div>
      {#each inspector as v (v.label)}
        <div class="irow" class:hl={highlight === v.label}>
          <div class="itop">
            <Marker index={colorIndex.get(v.label) ?? v.series} color={colorOf(v.label, v.series)} />
            {@render seriesName(v.label, 'ilab')}
            <span class="mono ival keep">{fmtNum(v.value)}</span>
            {#if groupBy && v.lo !== null && v.hi !== null && agg === 'std'}<span class="mono faint keep"
                >±{fmtNum((v.hi - v.lo) / 2, 2)}</span
              >{:else if !groupBy && focusData?.series[v.series]?.band && v.lo !== null && v.hi !== null && Number.isFinite(v.lo) && Number.isFinite(v.hi)}<span
                class="mono faint keep">{fmtNum(v.lo)} to {fmtNum(v.hi)}</span
              >{/if}
          </div>
          <div class="bar"><span style="width:{v.frac * 100}%; background:{colorOf(v.label, v.series)}"></span></div>
        </div>
      {:else}
        <p class="faint hint">
          Hover a chart to inspect a step; click to pin it. Hover a legend chip to highlight a series, click it to hide,
          double-click (or Alt-click) to show it alone. All and None show or hide every series.
        </p>
      {/each}
      {#each baseRows as b (b.labels.join('\n'))}
        {@const color = b.series.length === 1 ? colorOf(b.labels[0], b.series[0]) : 'var(--muted)'}
        <div class="irow base" class:hl={highlight !== null && b.labels.includes(highlight)}>
          <div class="itop">
            <span class="dash" style="border-color:{color}"></span>
            <span class="ilab">Baseline</span>
            <span class="mono ival keep">{fmtNum(b.value)}</span>
            {#if b.low !== undefined && b.high !== undefined}<span class="mono faint keep"
                >{fmtNum(b.low)} to {fmtNum(b.high)}</span
              >{/if}
          </div>
          <div class="mono faint trunc runs" title={b.labels.join(', ')}>{b.labels.join(', ')}</div>
        </div>
      {/each}
    </aside>
  </section>

  <section class="all">
    <div class="all-head">
      <h3>All scalars <span class="faint">Click one to bring it into focus</span></h3>
      <input
        class="input sm mono cfind"
        placeholder="Filter scalars (regex)"
        aria-label="Filter scalars"
        value={metricFind}
        oninput={(e) => router.set({ cfind: e.currentTarget.value || null })}
      />
      {#if metricFind}<span class="faint small">{shownMetrics.length} of {metrics.length}</span>{/if}
      <span class="label">Grid</span>
      <label class="opt"
        ><span class="faint">Columns</span>
        <select
          class="input sm"
          aria-label="Chart columns"
          value={String(gridCols)}
          onchange={(e) => setGrid('ccols', e.currentTarget.value)}
        >
          <option value="0">Fit</option>
          {#each [1, 2, 3, 4, 5, 6] as n (n)}<option value={String(n)}>{n}</option>{/each}
        </select></label
      >
      <label class="opt"
        ><span class="faint">Rows</span>
        <select
          class="input sm"
          aria-label="Chart rows per page"
          value={String(gridRows)}
          onchange={(e) => setGrid('crows', e.currentTarget.value)}
        >
          {#each [1, 2, 3, 4, 6] as n (n)}<option value={String(n)}>{n}</option>{/each}
          <option value="0">All</option>
        </select></label
      >
      {#if sections.length > 1}
        <button
          class="btn btn-ghost sm"
          onclick={() => setFolded(Object.fromEntries(sections.map(([p]) => [p, false])))}>Expand all</button
        >
        <button class="btn btn-ghost sm" onclick={() => setFolded(Object.fromEntries(sections.map(([p]) => [p, true])))}
          >Collapse all</button
        >
      {/if}
    </div>
    {#if metricFind && !shownMetrics.length}<p class="faint">No scalar matches “{metricFind}”.</p>{/if}
    {#each sections as [prefix, list], si (prefix)}
      {@const open = sectionOpen(prefix, si)}
      {@const size = gridRows ? perRow * gridRows : list.length}
      {@const pageCount = Math.max(1, Math.ceil(list.length / size))}
      {@const page = Math.min(gridPages[prefix] ?? 0, pageCount - 1)}
      <div class="sect">
        <div class="sect-head">
          <button
            class="fold"
            aria-expanded={open}
            title={prefix}
            onclick={() => setFolded({ ...folded, [prefix]: open })}
          >
            <span class="chev" class:closed={!open}><Icon name="chevron" size={16} /></span>
            <span class="label trunc">{prefix}</span>
            <span class="faint nchart">{list.length} chart{list.length === 1 ? '' : 's'}</span>
          </button>
          {#if open && pageCount > 1}
            <span class="pager">
              <button
                class="btn btn-ghost sm"
                aria-label="Previous charts of {prefix}"
                disabled={page === 0}
                onclick={() => (gridPages = { ...gridPages, [prefix]: page - 1 })}>‹</button
              >
              <span class="mono faint">{page + 1} / {pageCount}</span>
              <button
                class="btn btn-ghost sm"
                aria-label="Next charts of {prefix}"
                disabled={page >= pageCount - 1}
                onclick={() => (gridPages = { ...gridPages, [prefix]: page + 1 })}>›</button
              >
            </span>
          {/if}
        </div>
        {#if open}<div
            class="grid"
            bind:clientWidth={gridWidth}
            style={gridCols ? `grid-template-columns: repeat(${gridCols}, minmax(0, 1fr))` : ''}
          >
            {#each list.slice(page * size, page * size + size) as m (m)}
              <SmallChart
                metric={m}
                runs={runKeys}
                x={xKind}
                group={groupBy}
                {agg}
                {smoothing}
                {showRaw}
                {showBands}
                {robust}
                baselines={showBase}
                {hidden}
                {highlight}
                {colorOf}
                themeVersion={app.themeVersion}
                {tick}
                onFocus={() => {
                  router.set({ metric: m, zoom: null });
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
              />
            {/each}
          </div>{/if}
      </div>
    {/each}
  </section>
{/if}

<style>
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
  .sname {
    display: flex;
    gap: 0.35em;
    min-width: 0;
    flex: 0 1 auto;
  }
  .gkey,
  .gval {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .gkey {
    flex: 0 8 auto;
    min-width: 3.5em;
    max-width: 45%;
    color: var(--muted);
  }
  .gval {
    flex: 0 1 auto;
  }
  .sub .nfname {
    flex: 0 8 auto;
    min-width: 5em;
  }
  .sub .nfmetric {
    flex: 0 1 auto;
  }
  .groupsel {
    max-width: 260px;
  }
  .xmetric {
    max-width: 210px;
    font-size: 12.5px;
  }
  .xmetric.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .alerts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 10px 14px 12px;
    border-top: 1px solid var(--border);
  }
  .alerts .label {
    margin-right: 4px;
  }
  .alert {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 0;
    border-radius: 8px;
    padding: 4px 9px;
    font-size: 12.5px;
    color: var(--warn);
    background: var(--warn-bg);
    max-width: 100%;
    min-width: 0;
    text-align: left;
  }
  .alert .aname,
  .alert .amsg {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* the run name gives way before the message does */
  .alert .aname {
    flex: 0 8 auto;
  }
  .alert .amsg {
    flex: 0 1 auto;
  }
  .alert.err {
    color: var(--err);
    background: var(--err-bg);
  }
  .alert .mono {
    font-weight: 600;
  }
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }
  .faint {
    color: var(--faint);
  }
  .errc {
    color: var(--err);
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }
  .stat {
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .lrow {
    display: flex;
    gap: 6px;
    align-items: baseline;
    min-width: 0;
  }
  .stat .label .faint {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
  }
  .big {
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .big .faint {
    font-size: 18px;
    font-weight: 400;
  }
  .sub {
    color: var(--muted);
    font-size: 13px;
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
    min-height: 20px;
    min-width: 0;
  }
  .sub.nowrap {
    flex-wrap: nowrap;
  }
  .sub .nf {
    min-width: 0;
    max-width: 100%;
    flex: 0 1 auto;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: space-between;
  }
  .legend {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .showall {
    align-self: center;
  }
  .legend-chip {
    height: 32px;
    padding: 0 12px;
    background: var(--panel);
    color: var(--text);
    font-size: 13.5px;
    box-shadow: var(--lift);
    max-width: 100%;
  }
  .small {
    font-size: 12px;
  }
  .legendfind {
    width: 220px;
    align-self: center;
  }
  .legendcount {
    align-self: center;
  }
  .legendmore {
    align-self: center;
  }
  .picker {
    position: relative;
  }
  .pickpop {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 20;
    width: 360px;
    max-width: calc(100vw - 32px);
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: var(--lift);
  }
  .picklist {
    max-height: 320px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .pickopt {
    border: 0;
    background: none;
    text-align: left;
    padding: 5px 8px;
    border-radius: 6px;
    font-size: 12.5px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: none;
  }
  .pickopt[aria-selected='true'] {
    background: var(--panel-2);
  }
  .pickopt.on {
    color: var(--accent);
    font-weight: 600;
  }
  .legend-chip.off {
    opacity: 0.4;
  }
  .legend-chip .lab {
    max-width: 220px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .newdata {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: transparent;
    font-weight: 600;
  }
  .knobrows {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
  }
  .knobs {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .sm {
    height: 32px;
    font-size: 13px;
  }
  .smooth,
  .tg {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 13.5px;
  }
  .smooth input {
    width: 120px;
    accent-color: var(--accent);
  }
  .focus {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 330px;
    gap: 16px;
  }
  .main {
    padding: 12px 16px 8px;
    min-width: 0;
  }
  .tabs {
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 6px;
  }
  .tab {
    border: 0;
    background: none;
    padding: 6px 12px;
    border-radius: 8px;
    color: var(--muted);
    font-size: 13.5px;
    max-width: 280px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tab[aria-pressed='true'] {
    background: var(--panel-2);
    color: var(--text);
    font-weight: 600;
    box-shadow: inset 0 0 0 1px var(--border);
  }
  .note {
    margin-left: auto;
    color: var(--faint);
    font-size: 12.5px;
    display: inline-flex;
    gap: 8px;
    align-items: center;
  }
  .inspector {
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .ih {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
  }
  .ix {
    display: flex;
    gap: 8px;
    align-items: baseline;
    min-width: 0;
    font-size: 19px;
    font-weight: 600;
  }
  .im {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
    font-size: 12.5px;
  }
  .irow {
    background: var(--panel-2);
    border-radius: 10px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    border: 1px solid transparent;
    min-width: 0;
  }
  .irow.hl {
    border-color: var(--accent);
  }
  .irow.base {
    background: transparent;
    border: 1px dashed var(--border);
  }
  .irow.base.hl {
    border-color: var(--accent);
  }
  .dash {
    width: 14px;
    flex: none;
    border-top: 2px dashed;
  }
  .runs {
    font-size: 12px;
  }
  .itop {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13.5px;
    min-width: 0;
  }
  .ilab {
    flex: 1;
  }
  .ival {
    font-weight: 600;
  }
  .bar {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    border-radius: 2px;
  }
  .hint {
    font-size: 13px;
    margin-top: auto;
  }
  .all-head {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin: 8px 0 10px;
  }
  .cfind {
    width: 220px;
  }
  .all-head .small {
    font-size: 12px;
  }
  .all-head h3 {
    margin: 0 auto 0 0;
  }
  .all h3 {
    font-size: 16px;
    font-weight: 650;
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
  .sect-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .sect-head .label {
    min-width: 0;
  }
  .fold {
    display: flex;
    align-items: center;
    gap: 6px;
    border: 0;
    background: none;
    padding: 0;
    min-width: 0;
    text-align: left;
  }
  .fold .label {
    margin: 4px 0;
  }
  .nchart {
    flex: none;
    font-size: 12px;
  }
  .chev {
    display: inline-grid;
    color: var(--muted);
    transition: transform 0.15s;
  }
  .chev.closed {
    transform: rotate(-90deg);
  }
  .pager {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    flex: none;
  }
  .pager .btn {
    height: 26px;
    padding: 0 8px;
  }
  .icon-btn {
    height: 28px;
    width: 30px;
    padding: 0;
    display: inline-grid;
    place-items: center;
    flex: none;
  }
  .focus.full {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: var(--bg);
    padding: 16px;
    overflow: auto;
    grid-template-columns: minmax(0, 1fr) 330px;
  }
  .all h3 .faint {
    font-size: 13px;
    font-weight: 400;
    margin-left: 8px;
  }
  .sect {
    margin-bottom: 14px;
    min-width: 0;
  }
  .sect .label {
    margin: 4px 2px 8px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
    gap: 14px;
  }
  @media (max-width: 1200px) {
    .stats {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .focus {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
