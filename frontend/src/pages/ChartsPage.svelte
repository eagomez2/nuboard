<script lang="ts">
  import { onMount } from 'svelte';
  import LineChart, { type CursorValue } from '../components/LineChart.svelte';
  import Marker from '../components/Marker.svelte';
  import SmallChart from '../components/SmallChart.svelte';
  import { api, type Alert, type ChartData } from '../lib/api';
  import Icon from '../components/Icon.svelte';
  import { seriesColor } from '../lib/colors';
  import { defaultMetric, fmtAgo, fmtDuration, fmtNum, lowerIsBetter } from '../lib/format';
  import { onLive } from '../lib/live';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const MAX_LINES = 60;

  // ---- view state (URL) and preferences (localStorage) ----
  const xKind = $derived(router.get('x', 'step'));
  const smoothing = $derived(Number(router.get('smooth', String(prefs.get('smooth', 0.6)))));
  const showRaw = $derived(router.get('raw', '1') === '1');
  const robust = $derived(router.get('robust', '1') === '1');
  const logY = $derived(router.get('log') === '1');
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
  const runKeys = $derived(groupBy ? runs.map((r) => r.key) : runs.slice(0, MAX_LINES).map((r) => r.key));

  let metrics = $state<string[]>([]);
  let focusData = $state<ChartData | null>(null);
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
        points: 1400,
        xmin: zoom?.[0],
        xmax: zoom?.[1],
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

  onMount(() => {
    let last = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    return onLive('data', (changed) => {
      if (!changed.some((k) => runKeys.includes(k))) return;
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
  const sections = $derived.by(() => {
    const map = new Map<string, string[]>();
    for (const m of metrics) {
      const p = m.includes('/') ? m.split('/')[0] : 'other';
      if (!map.has(p)) map.set(p, []);
      map.get(p)!.push(m);
    }
    return [...map.entries()];
  });

  // Without a hover, the inspector shows each series' latest value.
  const lastValues = $derived(
    (focusData?.series ?? []).flatMap((s, i) => {
      for (let k = s.y.length - 1; k >= 0; k--)
        if (Number.isFinite(s.y[k]))
          return [{ series: i, label: s.label, value: s.y[k], lo: s.lo[k], hi: s.hi[k], x: s.x[k] }];
      return [];
    }),
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

  function fmtX(x: number | null) {
    if (x === null) return '—';
    if (xKind === 'time') return new Date(x * 1000).toLocaleTimeString();
    if (xKind === 'relative' || xKind === 'active') return fmtDuration(x);
    if (xMetric) return `${xMetric} ${fmtNum(x)}`;
    return `step ${Math.round(x).toLocaleString()}`;
  }
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
  const groupLabel = (g: string | null) => (g ? g.split('.').slice(-1)[0] : '');
</script>

{#if !runs.length}
  <div class="card empty">No runs to plot. Select runs on the Runs page, or change the query.</div>
{:else}
  <section class="stats">
    <div class="card stat">
      <div class="label">Best {focus || 'metric'} <span class="faint">({lower ? 'lowest' : 'highest'} last)</span></div>
      <div class="big mono">{best ? fmtNum(best.last) : '—'}</div>
      {#if best}
        <div class="sub">
          <Marker index={colorIndex.get(best.label) ?? 0} color={colorOf(best.label, 0)} />
          {groupLabel(groupBy)}
          {best.label}{best.n ? ` · mean of ${best.n}` : ''}
        </div>
      {/if}
    </div>
    <div class="card stat">
      <div class="label">Running</div>
      <div class="big mono">{running.length} <span class="faint">/ {runs.length}</span></div>
      <div class="sub">{running.length ? `last heartbeat ${fmtAgo(lastBeat)} · updates live` : 'no live runs'}</div>
    </div>
    <div class="card stat">
      <div class="label">Non-finite values</div>
      <div class="big mono" class:errc={nonfinite.length}>{nonfinite.length}</div>
      <div class="sub">
        {#if nonfinite.length}
          {#each nonfinite.slice(0, 2) as r (r.key)}<span class="chip chip-err">{r.name}: {r.nonfinite[0]}</span>{/each}
        {:else}no NaN or Inf logged{/if}
      </div>
    </div>
    <div class="card stat">
      <div class="label">Shown</div>
      <div class="big mono">{runKeys.length} <span class="faint">run{runKeys.length === 1 ? '' : 's'}</span></div>
      <div class="sub">
        {groupBy
          ? `grouped by ${groupBy}`
          : runs.length > MAX_LINES
            ? `first ${MAX_LINES} of ${runs.length}; group to see all`
            : 'one line per run'}
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
      {#each focusData?.series ?? [] as s, i (s.label)}
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
          <span class="lab">{groupBy ? `${groupLabel(groupBy)} ${s.label}` : s.label}</span>
          {#if s.n}<span class="faint">n={s.n}</span>{/if}
          <span class="mono" class:errc={s.nonfinite}>· {s.nonfinite ? 'NaN' : fmtNum(s.last)}</span>
        </button>
      {/each}
    </div>
    <div class="knobs">
      <select
        class="input sm"
        value={router.get('group') || (groupBy ?? 'none')}
        onchange={(e) => router.set({ group: (e.currentTarget as HTMLSelectElement).value })}
        aria-label="Group by"
      >
        <option value="none">no grouping</option>
        {#each [...new Set([...(groupBy ? [groupBy] : []), ...groupOptions])] as g (g)}<option value={g}
            >group by {g}</option
          >{/each}
      </select>
      {#if groupBy}
        <select
          class="input sm"
          value={agg}
          onchange={(e) => router.set({ agg: (e.currentTarget as HTMLSelectElement).value })}
          aria-label="Band"
        >
          <option value="std">mean ± std</option>
          <option value="sem">mean ± sem</option>
          <option value="minmax">mean · min–max</option>
          <option value="median">median · min–max</option>
          <option value="none">mean only</option>
        </select>
      {/if}
      <div class="seg" role="group" aria-label="X axis">
        {#each [['step', 'step'], ['time', 'wall time'], ['relative', 'relative'], ['active', 'active time']] as [k, label] (k)}
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
        aria-label="X axis metric"
        title="Plot against another metric, matched by step"
      >
        <option value="">x by metric…</option>
        {#each xCandidates as m (m)}<option value={m}>x = {m}</option>{/each}
      </select>
      <label class="smooth"
        >smooth
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
        ></button>raw</label
      >
      <label class="tg" title="Clip the y-axis to the 1st–99th percentile so spikes don't flatten the curves"
        ><button
          class="switch"
          role="switch"
          aria-checked={robust}
          aria-label="Robust y range"
          onclick={() => router.set({ robust: robust ? '0' : null })}
        ></button>robust y</label
      >
      <label class="tg"
        ><button
          class="switch"
          role="switch"
          aria-checked={logY}
          aria-label="Log y"
          onclick={() => router.set({ log: logY ? null : '1' })}
        ></button>log y</label
      >
    </div>
  </section>

  <section class="focus">
    <div class="card main">
      <div class="tabs">
        {#each tabs as m (m)}
          <button class="mono tab" aria-pressed={m === focus} onclick={() => router.set({ metric: m, zoom: null })}
            >{m}</button
          >
        {/each}
        <span class="note">
          {#if zoom}<button class="btn btn-ghost sm" onclick={() => router.set({ zoom: null })}>reset zoom</button>{/if}
          {loading
            ? 'loading…'
            : groupBy
              ? agg === 'std'
                ? 'mean ± std'
                : agg
              : 'drag to zoom · double-click to reset'}
        </span>
      </div>
      <LineChart
        data={focusData}
        {smoothing}
        {showRaw}
        {robust}
        {logY}
        {hidden}
        {highlight}
        {colorOf}
        themeVersion={app.themeVersion}
        height={420}
        onCursor={(x, v) => {
          if (!pinned) {
            cursorX = x;
            cursorValues = v;
          }
        }}
        onPin={() => (pinned = !pinned)}
        onZoom={(r) => router.set({ zoom: r ? `${r[0]}~${r[1]}` : null })}
        {regions}
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
              <span class="mono">{a.name}</span>
              <span>{a.alert.message}</span>
              {#if a.alert.rank}<span class="mono faint">rank {a.alert.rank}</span>{/if}
            </button>
          {/each}
          {#if alerts.length > 12}<span class="faint">+{alerts.length - 12} more</span>{/if}
        </div>
      {/if}
    </div>
    <aside class="card inspector">
      <div class="ih">
        <span class="label">Inspector</span><span class="faint"
          >{pinned ? 'pinned · click chart to release' : 'hover · click to pin'}</span
        >
      </div>
      <div class="ix mono">
        {cursorX === null
          ? lastValues.length
            ? `latest · ${fmtX(Math.max(...lastValues.map((v) => v.x)))}`
            : '—'
          : fmtX(cursorX)}
      </div>
      <div class="im">
        <span class="mono">{focus}</span><span class="faint">{lower ? 'lowest first' : 'highest first'}</span>
      </div>
      {#each inspector as v (v.label)}
        <div class="irow" class:hl={highlight === v.label}>
          <div class="itop">
            <Marker index={colorIndex.get(v.label) ?? v.series} color={colorOf(v.label, v.series)} />
            <span class="ilab">{groupBy ? `${groupLabel(groupBy)} ${v.label}` : v.label}</span>
            <span class="mono ival">{fmtNum(v.value)}</span>
            {#if groupBy && v.lo !== null && v.hi !== null && agg === 'std'}<span class="mono faint"
                >±{fmtNum((v.hi - v.lo) / 2, 2)}</span
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
    </aside>
  </section>

  <section class="all">
    <h3>All metrics <span class="faint">click one to bring it into focus</span></h3>
    {#each sections as [prefix, list] (prefix)}
      <div class="sect">
        <div class="label">{prefix}</div>
        <div class="grid">
          {#each list as m (m)}
            <SmallChart
              metric={m}
              runs={runKeys}
              x={xKind}
              group={groupBy}
              {agg}
              {smoothing}
              {showRaw}
              {robust}
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
        </div>
      </div>
    {/each}
  </section>
{/if}

<style>
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
    text-align: left;
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
  }
  .legend-chip.off {
    opacity: 0.4;
  }
  .legend-chip .lab {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
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
    font-size: 12px;
  }
  .ix {
    font-size: 19px;
    font-weight: 600;
  }
  .im {
    display: flex;
    justify-content: space-between;
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
  }
  .irow.hl {
    border-color: var(--accent);
  }
  .itop {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13.5px;
  }
  .ilab {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
  .all h3 {
    font-size: 16px;
    font-weight: 650;
    margin: 8px 0 10px;
  }
  .all h3 .faint {
    font-size: 13px;
    font-weight: 400;
    margin-left: 8px;
  }
  .sect {
    margin-bottom: 14px;
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
