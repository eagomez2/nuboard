<script lang="ts">
  import HistChart from '../components/HistChart.svelte';
  import Icon from '../components/Icon.svelte';
  import MediaCard from '../components/MediaCard.svelte';
  import MediaView from '../components/MediaView.svelte';
  import PrChart from '../components/PrChart.svelte';
  import { api, type MediaItem, type RunBrief } from '../lib/api';
  import { seriesVar } from '../lib/colors';
  import { addOverlayToReport, appendToReport, askReport } from '../lib/reports.svelte';
  import { chartToPng } from '../lib/snapshot';
  import { defaultMetric, fmtNum, lowerIsBetter } from '../lib/format';
  import { HIST_MIME, MEDIA_KINDS, PR_MIME, embedLine, kindOf, mediaRef, type MediaKind } from '../lib/media';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const MAX_RUNS = 48;
  const runs = $derived(app.visibleRuns().slice(0, MAX_RUNS));
  const runIndex = $derived(new Map(runs.map((r, i) => [r.key, i])));
  // Runs hidden with the legend chips (All / None, click to hide, double-click or Alt-click to solo)
  let hiddenRuns = $state(new Set<string>());
  const shownRuns = $derived(runs.filter((r) => !hiddenRuns.has(r.key)));
  function toggleRun(key: string) {
    const next = new Set(hiddenRuns);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    hiddenRuns = next;
  }
  function soloRun(key: string) {
    const alone = !hiddenRuns.has(key) && runs.every((r) => r.key === key || hiddenRuns.has(r.key));
    hiddenRuns = alone ? new Set() : new Set(runs.filter((r) => r.key !== key).map((r) => r.key));
  }
  let items = $state<Record<string, MediaItem[]>>({});
  let loaded = $state(false);

  $effect(() => {
    const keys = runs.map((r) => r.key);
    // media cells of tables (kind "cell") are shown inside their table, not as keys
    const own = (list: MediaItem[]) => list.filter((it) => it.kind !== 'cell');
    Promise.all(keys.map((k) => api.media(k).then((res) => [k, own(res.items)] as const))).then((pairs) => {
      items = Object.fromEntries(pairs);
      loaded = true;
    });
  });

  // -- what to show ---------------------------------------------------------------
  const LABELS: Record<MediaKind, string> = {
    image: 'Images',
    audio: 'Audio',
    video: 'Video',
    figure: 'Figures',
    table: 'Tables',
    points: 'Point clouds',
    html: 'HTML',
    text: 'Text',
  };
  const kindCounts = $derived.by(() => {
    const keys: Record<MediaKind, Set<string>> = {
      image: new Set(),
      audio: new Set(),
      video: new Set(),
      figure: new Set(),
      table: new Set(),
      points: new Set(),
      html: new Set(),
      text: new Set(),
    };
    for (const list of Object.values(items)) for (const it of list) keys[kindOf(it)].add(it.key);
    return keys;
  });
  const available = $derived(MEDIA_KINDS.filter((k) => kindCounts[k].size));
  const kinds = $derived.by(() => {
    const picked = router.list('mkinds').filter((k): k is MediaKind => MEDIA_KINDS.includes(k as MediaKind));
    return picked.length ? picked : available;
  });
  function toggleKind(k: MediaKind) {
    const next = kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k];
    router.set({ mkinds: next.length === available.length || !next.length ? null : next.join(',') });
  }
  function onlyKind(k: MediaKind) {
    router.set({ mkinds: kinds.length === 1 && kinds[0] === k ? null : k });
  }
  const find = $derived(router.get('mfind'));
  const findRe = $derived.by(() => {
    try {
      return find ? new RegExp(find, 'i') : null;
    } catch {
      return null;
    }
  });

  // Keys of the chosen kinds before the filter, for the "N of M" count
  const keyTotal = $derived.by(() => {
    const keys = new Set<string>();
    for (const r of shownRuns) for (const it of items[r.key] ?? []) if (kinds.includes(kindOf(it))) keys.add(it.key);
    return keys.size;
  });

  // key -> run key -> items sorted by step
  const byKey = $derived.by(() => {
    const map = new Map<string, { kind: MediaKind; runs: Map<string, MediaItem[]> }>();
    for (const r of shownRuns) {
      for (const it of items[r.key] ?? []) {
        const kind = kindOf(it);
        if (!kinds.includes(kind)) continue;
        if (find && !(findRe ? findRe.test(it.key) : it.key.toLowerCase().includes(find.toLowerCase()))) continue;
        if (!map.has(it.key)) map.set(it.key, { kind, runs: new Map() });
        const per = map.get(it.key)!.runs;
        if (!per.has(r.key)) per.set(r.key, []);
        per.get(r.key)!.push(it);
      }
    }
    for (const v of map.values()) for (const list of v.runs.values()) list.sort((a, b) => a.step - b.step);
    return new Map([...map.entries()].sort(([a], [b]) => a.localeCompare(b)));
  });

  // Sections: one per key (cards are runs) or one per run (cards are keys)
  const by = $derived(router.get('mby', 'key') === 'run' ? 'run' : 'key');
  interface Card {
    id: string;
    run: RunBrief;
    items: MediaItem[];
    title: string;
  }
  interface Section {
    id: string;
    title: string;
    sub: string;
    kind: MediaKind | null;
    cards: Card[];
  }
  const sections = $derived.by((): Section[] => {
    if (by === 'key')
      return [...byKey.entries()].map(([key, v]) => ({
        id: key,
        title: key,
        kind: v.kind,
        sub: `${v.runs.size} of ${shownRuns.length} runs`,
        cards: shownRuns.map((r) => ({ id: r.key, run: r, items: v.runs.get(r.key) ?? [], title: r.name })),
      }));
    return shownRuns
      .map((r) => {
        const cards = [...byKey.entries()]
          .filter(([, v]) => v.runs.has(r.key))
          .map(([key, v]) => ({ id: key, run: r, items: v.runs.get(r.key)!, title: key }));
        return { id: r.key, title: r.name, kind: null, sub: `${cards.length} keys`, cards };
      })
      .filter((s) => s.cards.length);
  });
  // Runs that logged nothing under a key are hidden unless asked for
  const showEmpty = $derived(router.get('mempty') === '1');

  // -- which step -------------------------------------------------------------------
  const mode = $derived(router.get('mmode', 'latest') as 'latest' | 'step' | 'best');
  const allSteps = $derived(
    [...new Set([...byKey.values()].flatMap((v) => [...v.runs.values()].flatMap((l) => l.map((i) => i.step))))].sort(
      (a, b) => a - b,
    ),
  );
  const pickedStep = $derived.by(() => {
    const want = Number(router.get('mstep', ''));
    if (!allSteps.length) return 0;
    if (!router.get('mstep') || !Number.isFinite(want)) return allSteps[allSteps.length - 1];
    return allSteps.reduce((b, s) => (Math.abs(s - want) < Math.abs(b - want) ? s : b), allSteps[0]);
  });
  const metricNames = $derived([...new Set(runs.flatMap((r) => Object.keys(r.summary)))].sort());
  const bestMetric = $derived(
    metricNames.includes(router.get('mmetric')) ? router.get('mmetric') : defaultMetric(metricNames),
  );
  const bestDir = $derived((router.get('mdir') || (lowerIsBetter(bestMetric) ? 'min' : 'max')) as 'min' | 'max');
  let best = $state<Record<string, { step: number; value: number }>>({});
  let bestAsked = 0;
  $effect(() => {
    if (mode !== 'best' || !bestMetric || !runs.length) return;
    // only the newest answer counts: one for an older choice (Lowest before Highest, another
    // scalar, a live refresh) can arrive after it and would show the other end
    const asked = ++bestAsked;
    api
      .best(
        runs.map((r) => r.key),
        bestMetric,
        bestDir,
      )
      .then((res) => {
        if (asked === bestAsked) best = res.best;
      });
  });
  // The item a card shows for the page-wide step (its own slider aside), as MediaCard picks it
  function shownItem(list: MediaItem[], target: number | null, nearest: boolean): MediaItem | null {
    if (!list.length) return null;
    if (target === null) return list[list.length - 1];
    if (nearest) return list.reduce((a, b) => (Math.abs(b.step - target) < Math.abs(a.step - target) ? b : a));
    let found = list[0];
    for (const it of list) if (it.step <= target) found = it;
    return found;
  }
  // PR curves or distributions of every run under one key, overlaid on one chart above the cards
  function prOverlay(cards: { run: RunBrief; items: MediaItem[] }[]) {
    return cards.flatMap((c) => {
      const it = shownItem(c.items, targetFor(c.run.key), mode === 'best');
      return it && it.index !== undefined
        ? [
            {
              name: `${c.run.name} · step ${it.step.toLocaleString()}`,
              color: seriesVar(runIndex.get(c.run.key) ?? 0),
              url: api.mediaUrl(c.run.key, it.index),
              ref: mediaRef(c.run.id, it.key, it.step),
            },
          ]
        : [];
    });
  }

  function targetFor(runKey: string): number | null {
    if (mode === 'step') return pickedStep;
    if (mode === 'best') return best[runKey]?.step ?? null;
    return null;
  }

  // -- grid ---------------------------------------------------------------------------
  const cols = $derived(Number(router.get('mcols', String(prefs.get('mcols', 0)))) || 0); // 0: fit to width
  const rows = $derived(Number(router.get('mrows', String(prefs.get('mrows', 2)))) || 0); // 0: all
  function setGrid(k: 'mcols' | 'mrows', v: string) {
    prefs.set(k, Number(v));
    router.set({ [k]: v });
  }
  let width = $state(1200);
  function minWidth(s: Section): number {
    const k = s.kind ?? (s.cards.some((c) => c.items.some((i) => kindOf(i) === 'audio')) ? 'audio' : 'image');
    return k === 'table' ? 860 : k === 'audio' && player === 'wave' ? 520 : k === 'image' ? 200 : 380;
  }
  function colsFor(s: Section): number {
    return cols || Math.max(1, Math.floor((width + 14) / (minWidth(s) + 14)));
  }
  let pages = $state<Record<string, number>>({});
  let folded = $state<Record<string, boolean>>({});
  function isOpen(s: Section, i: number): boolean {
    return folded[s.id] === undefined ? sections.length <= 6 || i < 3 : !folded[s.id];
  }
  function setAll(open: boolean) {
    folded = Object.fromEntries(sections.map((s) => [s.id, !open]));
  }

  // -- audio player options -------------------------------------------------------------
  const player = $derived(router.get('player', prefs.get('player', 'wave')));
  function setPlayer(p: string) {
    prefs.set('player', p);
    router.set({ player: p === 'wave' ? null : p });
  }
  const AUDIO_DEFAULTS = { cmap: 'theme', fscale: 'linear', fft: '1024', spec: '1', amp: '1' };
  type AudioOpt = keyof typeof AUDIO_DEFAULTS;
  const opt = (k: AudioOpt) => router.get(k, prefs.get(k, AUDIO_DEFAULTS[k]));
  function setOpt(k: AudioOpt, v: string) {
    prefs.set(k, v);
    router.set({ [k]: v === AUDIO_DEFAULTS[k] ? null : v });
  }
  const audioOptions = $derived({
    colormap: opt('cmap'),
    scale: opt('fscale'),
    fftSize: Number(opt('fft')) || 1024,
    spectrogram: opt('spec') !== '0',
    axis: opt('amp') !== '0',
  });
  const showsAudio = $derived(kinds.includes('audio') && kindCounts.audio.size > 0);

  // -- saving to a report and the large view ---------------------------------------------
  async function save(run: RunBrief, it: MediaItem) {
    const res = await askReport(
      run.project,
      `${it.key} · ${run.name} · step ${it.step}`,
      `${it.key} at step ${it.step} of ${run.name}`,
    );
    if (res) await appendToReport(run.project, res.name, embedLine(run.id, it.key, it.step, res.caption));
  }
  let zoom = $state<{ run: RunBrief; item: MediaItem } | null>(null);
  // Save the "All runs on one chart" overlay that holds `button`, with its legend, as a PNG
  async function overlayPng(button: HTMLElement, key: string) {
    const root = button.closest('.prall') ?? button.closest('.big')?.querySelector('.bigbody');
    return root ? await chartToPng(root, `${key} · all runs`) : null;
  }
  async function downloadOverlay(e: MouseEvent, key: string) {
    const png = await overlayPng(e.currentTarget as HTMLElement, key);
    if (!png) return;
    const a = document.createElement('a');
    a.href = png;
    a.download = `${key.replaceAll('/', '_')}-all-runs.png`;
    a.click();
  }
  async function reportOverlay(e: MouseEvent, key: string, curves: { ref: string }[]) {
    const project = router.get('project') ?? runs[0]?.project;
    const png = await overlayPng(e.currentTarget as HTMLElement, key);
    if (!png || !project) return;
    zoomAll = null;
    await addOverlayToReport(
      project,
      png,
      `${key}, all runs`,
      curves.map((c) => c.ref),
    );
  }
  // The "All runs on one chart" overlay of one key, opened large
  let zoomAll = $state<{ title: string; kind: 'pr' | 'hist'; curves: ReturnType<typeof prOverlay> } | null>(null);

  // Several items picked with the card checkboxes, added to one report in the order picked.
  let selecting = $state(false);
  let picked = $state<{ id: string; run: RunBrief; item: MediaItem }[]>([]);
  const pickId = (run: RunBrief, it: MediaItem) => `${run.key}\u0000${it.key}\u0000${it.step}`;
  const pickedIds = $derived(new Set(picked.map((p) => p.id)));
  function pick(run: RunBrief, it: MediaItem, on: boolean) {
    const id = pickId(run, it);
    picked = on ? [...picked.filter((p) => p.id !== id), { id, run, item: it }] : picked.filter((p) => p.id !== id);
  }
  function stopSelecting() {
    selecting = false;
    picked = [];
  }
  async function savePicked() {
    if (!picked.length) return;
    const project = picked[0].run.project;
    const n = picked.length;
    const res = await askReport(project, null, `Add ${n} item${n === 1 ? '' : 's'}, each with its own caption.`);
    if (!res) return;
    const lines = picked.map((p) =>
      embedLine(p.run.id, p.item.key, p.item.step, `${p.item.key} at step ${p.item.step} of ${p.run.name}`),
    );
    await appendToReport(project, res.name, lines.join('\n\n'));
    stopSelecting();
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && ((zoom = null), (zoomAll = null))} />

{#if !runs.length}
  <div class="card empty">No runs selected. Pick runs on the Runs page and press “Media”.</div>
{:else if loaded && !available.length}
  <div class="card empty">
    These runs logged no images, audio, figures, HTML or text. Use <code>run.add_image</code>,
    <code>add_audio</code>, <code>add_figure</code>, <code>add_html</code>
    or <code>add_text</code>.
  </div>
{:else}
  <div class="card bar">
    {#if runs.length > 1}
      <div class="row legend">
        <div class="seg" role="group" aria-label="Show runs">
          <button aria-pressed={hiddenRuns.size === 0} title="Show every run" onclick={() => (hiddenRuns = new Set())}
            >All</button
          >
          <button
            aria-pressed={runs.every((r) => hiddenRuns.has(r.key))}
            title="Hide every run, then click chips to add them back"
            onclick={() => (hiddenRuns = new Set(runs.map((r) => r.key)))}>None</button
          >
        </div>
        {#each runs as r, i (r.key)}
          <button
            class="chip run-chip"
            class:off={hiddenRuns.has(r.key)}
            title="{r.name}&#10;&#10;Click to hide · double-click or Alt-click to solo"
            onclick={(e) => (e.altKey || e.metaKey || e.ctrlKey ? soloRun(r.key) : toggleRun(r.key))}
            ondblclick={() => soloRun(r.key)}
            ><i class="dot" style="background:{seriesVar(i)}"></i><span class="mono rn">{r.name}</span></button
          >
        {/each}
      </div>
    {/if}
    <div class="row">
      <div class="kinds" role="group" aria-label="Kinds of media">
        {#each available as k (k)}
          <button
            class="chip kind"
            aria-pressed={kinds.includes(k)}
            title="Click to show or hide · double-click to show only {LABELS[k].toLowerCase()}"
            onclick={() => toggleKind(k)}
            ondblclick={() => onlyKind(k)}>{LABELS[k]} <span class="n">{kindCounts[k].size}</span></button
          >
        {/each}
      </div>
      <input
        class="input sm find mono"
        placeholder="Filter keys (regex)"
        aria-label="Filter keys"
        value={find}
        oninput={(e) => router.set({ mfind: e.currentTarget.value })}
      />
      {#if find}<span class="faint small">{byKey.size} of {keyTotal}</span>{/if}
      <div class="seg" role="group" aria-label="Arrange by">
        <button aria-pressed={by === 'key'} onclick={() => router.set({ mby: null })}>By key</button>
        <button aria-pressed={by === 'run'} onclick={() => router.set({ mby: 'run' })}>By run</button>
      </div>
    </div>

    <div class="row">
      <span class="label">Step</span>
      <div class="seg" role="group" aria-label="Step to show">
        <button aria-pressed={mode === 'latest'} onclick={() => router.set({ mmode: null })}>Latest</button>
        <button aria-pressed={mode === 'step'} onclick={() => router.set({ mmode: 'step' })}>Pick step</button>
        <button aria-pressed={mode === 'best'} onclick={() => router.set({ mmode: 'best' })}>Best scalar</button>
      </div>
      {#if mode === 'step' && allSteps.length}
        <label class="slider">
          <input
            type="range"
            min="0"
            max={allSteps.length - 1}
            value={allSteps.indexOf(pickedStep)}
            aria-label="Step"
            oninput={(e) => router.set({ mstep: allSteps[Number(e.currentTarget.value)] })}
          />
          <span class="mono">Step {pickedStep.toLocaleString()}</span>
        </label>
      {:else if mode === 'best'}
        <select
          class="input sm mono metric"
          aria-label="Scalar"
          value={bestMetric}
          onchange={(e) => router.set({ mmetric: e.currentTarget.value })}
        >
          {#each metricNames as m (m)}<option value={m}>{m}</option>{/each}
        </select>
        <div class="seg" role="group" aria-label="Best is">
          <button aria-pressed={bestDir === 'min'} onclick={() => router.set({ mdir: 'min' })}>Lowest</button>
          <button aria-pressed={bestDir === 'max'} onclick={() => router.set({ mdir: 'max' })}>Highest</button>
        </div>
        <span class="faint small">each run shows the item logged closest to its best step</span>
      {/if}
      <span class="spacer"></span>
      <span class="label">Grid</span>
      <label class="opt"
        ><span class="faint">Columns</span>
        <select
          class="input sm"
          aria-label="Columns"
          value={String(cols)}
          onchange={(e) => setGrid('mcols', e.currentTarget.value)}
        >
          <option value="0">Fit</option>
          {#each [1, 2, 3, 4, 5, 6, 8] as n (n)}<option value={String(n)}>{n}</option>{/each}
        </select></label
      >
      <label class="opt"
        ><span class="faint">Rows</span>
        <select
          class="input sm"
          aria-label="Rows per page"
          value={String(rows)}
          onchange={(e) => setGrid('mrows', e.currentTarget.value)}
        >
          {#each [1, 2, 3, 4, 6] as n (n)}<option value={String(n)}>{n}</option>{/each}
          <option value="0">All</option>
        </select></label
      >
    </div>

    {#if showsAudio}
      <div class="row">
        <span class="label">Audio</span>
        <div class="seg">
          <button aria-pressed={player === 'wave'} onclick={() => setPlayer('wave')}>Waveform</button>
          <button aria-pressed={player === 'simple'} onclick={() => setPlayer('simple')}>Simple</button>
        </div>
        {#if player === 'wave'}
          <label class="opt"
            ><span class="faint">Colors</span>
            <select
              class="input sm"
              aria-label="Spectrogram colors"
              value={audioOptions.colormap}
              onchange={(e) => setOpt('cmap', e.currentTarget.value)}
            >
              <option value="theme">Theme</option>
              <option value="viridis">Viridis</option>
              <option value="magma">Magma</option>
              <option value="gray">Gray</option>
            </select></label
          >
          <label class="opt"
            ><span class="faint">Frequency</span>
            <select
              class="input sm"
              aria-label="Frequency scale"
              value={audioOptions.scale}
              onchange={(e) => setOpt('fscale', e.currentTarget.value)}
            >
              <option value="linear">Linear</option>
              <option value="logarithmic">Log</option>
              <option value="mel">Mel</option>
            </select></label
          >
          <label class="opt"
            ><span class="faint">Window</span>
            <select
              class="input sm mono"
              aria-label="FFT window"
              value={String(audioOptions.fftSize)}
              onchange={(e) => setOpt('fft', e.currentTarget.value)}
            >
              {#each [256, 512, 1024, 2048, 4096] as n (n)}<option value={String(n)}>{n}</option>{/each}
            </select></label
          >
          <label class="opt"
            ><button
              class="switch"
              role="switch"
              aria-checked={audioOptions.spectrogram}
              aria-label="Spectrogram"
              onclick={() => setOpt('spec', audioOptions.spectrogram ? '0' : '1')}
            ></button>
            <span class="faint">Spectrogram</span></label
          >
          <label class="opt"
            ><button
              class="switch"
              role="switch"
              aria-checked={audioOptions.axis}
              aria-label="Amplitude axis"
              onclick={() => setOpt('amp', audioOptions.axis ? '0' : '1')}
            ></button>
            <span class="faint">Amplitude axis</span></label
          >
          <span class="faint small"
            >Players follow each other's zoom and selection · space plays · ctrl + wheel zooms</span
          >
        {/if}
      </div>
    {/if}
  </div>

  <div class="sections-head">
    <span class="faint"
      >{sections.length}
      {by === 'key' ? 'key' : 'run'}{sections.length === 1 ? '' : 's'}{runs.length === MAX_RUNS
        ? ` · first ${MAX_RUNS} runs`
        : ''}</span
    >
    <label class="opt"
      ><button
        class="switch"
        role="switch"
        aria-checked={showEmpty}
        aria-label="Show runs without this key"
        onclick={() => router.set({ mempty: showEmpty ? null : '1' })}
      ></button>
      <span class="faint">Show runs without the key</span></label
    >
    <span class="spacer"></span>
    <button
      class="btn btn-ghost sm"
      aria-pressed={selecting}
      onclick={() => (selecting ? stopSelecting() : (selecting = true))}
      ><Icon name="bookmark" size={14} /> Select for report</button
    >
    <button class="btn btn-ghost sm" onclick={() => setAll(true)}>Expand all</button>
    <button class="btn btn-ghost sm" onclick={() => setAll(false)}>Collapse all</button>
  </div>

  {#if find && !byKey.size}<p class="faint">No key matches “{find}”.</p>{/if}
  <div class="sections" bind:clientWidth={width}>
    {#each sections as s, si (s.id)}
      {@const open = isOpen(s, si)}
      {@const cards = showEmpty || by === 'run' ? s.cards : s.cards.filter((c) => c.items.length)}
      {@const n = colsFor(s)}
      {@const size = rows ? n * rows : cards.length}
      {@const pageCount = Math.max(1, Math.ceil(cards.length / Math.max(1, size)))}
      {@const page = Math.min(pages[s.id] ?? 0, pageCount - 1)}
      <section class="card section">
        <header>
          <button
            class="fold"
            aria-expanded={open}
            onclick={() => (folded = { ...folded, [s.id]: open })}
            title={s.title}
          >
            <span class="chev" class:closed={!open}><Icon name="chevron" size={16} /></span>
            <span class="mono stitle">{s.title}</span>
            {#if s.kind}<span class="chip kindtag">{LABELS[s.kind]}</span>{/if}
            <span class="faint small">{s.sub}</span>
          </button>
          {#if open && pageCount > 1}
            <span class="pager">
              <button
                class="btn btn-ghost sm"
                aria-label="Previous page"
                disabled={page === 0}
                onclick={() => (pages = { ...pages, [s.id]: page - 1 })}>‹</button
              >
              <span class="mono small">{page + 1} / {pageCount}</span>
              <button
                class="btn btn-ghost sm"
                aria-label="Next page"
                disabled={page >= pageCount - 1}
                onclick={() => (pages = { ...pages, [s.id]: page + 1 })}>›</button
              >
            </span>
          {/if}
        </header>
        {#if open && by === 'key' && cards.length > 1 && cards[0].items[0]?.mime === PR_MIME}
          <div class="prall">
            <span class="prhead"
              ><span class="faint small">All runs on one chart</span>
              <button
                class="icon"
                title="Open large"
                aria-label="Open large"
                onclick={() => (zoomAll = { title: s.title, kind: 'pr', curves: prOverlay(cards) })}
                ><Icon name="search" size={14} /></button
              ><button
                class="icon"
                title="Download as PNG"
                aria-label="Download as PNG"
                onclick={(e) => downloadOverlay(e, s.title)}><Icon name="download" size={14} /></button
              ><button
                class="icon"
                title="Add to a report"
                aria-label="Add to a report"
                onclick={(e) => reportOverlay(e, s.title, prOverlay(cards))}><Icon name="bookmark" size={14} /></button
              ></span
            >
            <PrChart curves={prOverlay(cards)} height={300} label="Precision-recall curves of {s.title} for all runs" />
          </div>
        {:else if open && by === 'key' && cards.length > 1 && cards[0].items[0]?.mime === HIST_MIME}
          <div class="prall">
            <span class="prhead"
              ><span class="faint small">All runs on one chart</span>
              <button
                class="icon"
                title="Open large"
                aria-label="Open large"
                onclick={() => (zoomAll = { title: s.title, kind: 'hist', curves: prOverlay(cards) })}
                ><Icon name="search" size={14} /></button
              ><button
                class="icon"
                title="Download as PNG"
                aria-label="Download as PNG"
                onclick={(e) => downloadOverlay(e, s.title)}><Icon name="download" size={14} /></button
              ><button
                class="icon"
                title="Add to a report"
                aria-label="Add to a report"
                onclick={(e) => reportOverlay(e, s.title, prOverlay(cards))}><Icon name="bookmark" size={14} /></button
              ></span
            >
            <HistChart curves={prOverlay(cards)} height={260} label="Distributions of {s.title} for all runs" />
          </div>
        {/if}
        {#if open}
          <div class="grid" style="grid-template-columns: repeat({n}, minmax(0, 1fr))">
            {#each cards.slice(page * size, page * size + size) as c (c.id)}
              <MediaCard
                run={c.run}
                items={c.items}
                target={targetFor(c.run.key)}
                nearest={mode === 'best'}
                title={c.title}
                color={seriesVar(runIndex.get(c.run.key) ?? 0)}
                {player}
                {audioOptions}
                onsave={(it) => save(c.run, it)}
                onzoom={(it) => (zoom = { run: c.run, item: it })}
                {selecting}
                isSelected={(it) => pickedIds.has(pickId(c.run, it))}
                onselect={(it, on) => pick(c.run, it, on)}
              />
            {/each}
          </div>
          {#if mode === 'best' && by === 'key'}
            <p class="faint small bestnote">
              {bestDir === 'min' ? 'Lowest' : 'Highest'}
              {bestMetric}:
              {#each cards.slice(page * size, page * size + size) as c, i (c.id)}{#if best[c.run.key]}{@const b =
                    best[c.run.key]}{@const shown = shownItem(c.items, b.step, true)}{i ? ' · ' : ''}{c.run.name}
                  {fmtNum(b.value)} at step {b.step.toLocaleString()}{#if shown && shown.step !== b.step}
                    {' '}(item from step {shown.step.toLocaleString()}){/if}{/if}{/each}
            </p>
          {/if}
        {/if}
      </section>
    {/each}
  </div>
{/if}

{#if selecting}
  <div class="card selbar" role="toolbar" aria-label="Selected media">
    <span
      >{picked.length ? `${picked.length} selected` : 'Tick the items to add, then add them to a report together'}</span
    >
    <span class="spacer"></span>
    <button class="btn btn-primary sm" disabled={!picked.length} onclick={savePicked}
      ><Icon name="bookmark" size={14} /> Add {picked.length || ''} to report</button
    >
    <button class="btn btn-ghost sm" onclick={() => (picked = [])} disabled={!picked.length}>Clear</button>
    <button class="btn btn-ghost sm" onclick={stopSelecting}>Done</button>
  </div>
{/if}

{#if zoomAll}
  <div class="overlay" role="presentation" onclick={(e) => e.target === e.currentTarget && (zoomAll = null)}>
    <div class="card big" role="dialog" aria-label="{zoomAll.title}, all runs">
      <header>
        <span class="mono stitle">{zoomAll.title}</span>
        <span class="faint small">All runs on one chart</span>
        <span class="spacer"></span>
        <button class="btn btn-ghost sm" onclick={(e) => zoomAll && downloadOverlay(e, zoomAll.title)}
          ><Icon name="download" size={14} /> Download</button
        >
        <button class="btn btn-ghost sm" onclick={(e) => zoomAll && reportOverlay(e, zoomAll.title, zoomAll.curves)}
          ><Icon name="bookmark" size={14} /> Add to report</button
        >
        <button class="btn btn-ghost sm" aria-label="Close" onclick={() => (zoomAll = null)}
          ><Icon name="x" size={16} /></button
        >
      </header>
      <div class="bigbody">
        {#if zoomAll.kind === 'pr'}
          <PrChart
            curves={zoomAll.curves}
            height={560}
            label="Precision-recall curves of {zoomAll.title} for all runs"
          />
        {:else}
          <HistChart curves={zoomAll.curves} height={520} label="Distributions of {zoomAll.title} for all runs" />
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if zoom}
  <div class="overlay" role="presentation" onclick={(e) => e.target === e.currentTarget && (zoom = null)}>
    <div class="card big" role="dialog" aria-label="{zoom.item.key} at step {zoom.item.step}">
      <header>
        <span class="mono stitle">{zoom.item.key}</span>
        <span class="faint mono small">{zoom.run.name} · step {zoom.item.step.toLocaleString()}</span>
        <span class="spacer"></span>
        <button class="btn btn-ghost sm" onclick={() => zoom && save(zoom.run, zoom.item)}
          ><Icon name="bookmark" size={14} /> Add to report</button
        >
        <button class="btn btn-ghost sm" aria-label="Close" onclick={() => (zoom = null)}
          ><Icon name="x" size={16} /></button
        >
      </header>
      <div class="bigbody">
        <MediaView
          runKey={zoom.run.key}
          runName={zoom.run.name}
          item={zoom.item}
          {player}
          {audioOptions}
          tall
          color={seriesVar(runIndex.get(zoom.run.key) ?? 0)}
        />
      </div>
    </div>
  </div>
{/if}

<style>
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }
  .empty code {
    font-family: var(--mono);
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12px;
  }
  .bar {
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    font-size: 13px;
  }
  .label {
    min-width: 46px;
  }
  .kinds {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .kind {
    height: 30px;
    padding: 0 12px;
    font-size: 13px;
    cursor: pointer;
  }
  .kind[aria-pressed='true'] {
    border-color: color-mix(in srgb, var(--accent) 45%, transparent);
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
  .kind .n {
    font-family: var(--mono);
    font-size: 11.5px;
    opacity: 0.75;
  }
  .find {
    width: 220px;
    height: 30px;
  }
  .sm {
    height: 30px;
  }
  .metric {
    max-width: 260px;
  }
  .slider {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
    min-width: 200px;
  }
  .slider input {
    flex: 1;
    accent-color: var(--accent);
  }
  .legend {
    gap: 6px;
  }
  .run-chip {
    height: 28px;
    padding: 0 10px;
    gap: 6px;
    background: var(--panel);
    color: var(--text);
    font-size: 12.5px;
    box-shadow: var(--lift);
    max-width: 240px;
    min-width: 0;
  }
  .run-chip.off {
    opacity: 0.4;
  }
  .run-chip .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .run-chip .rn {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .opt {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .spacer {
    flex: 1;
  }
  .selbar {
    position: sticky;
    bottom: 12px;
    z-index: 5;
    margin-top: 12px;
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    box-shadow: 0 6px 24px rgb(0 0 0 / 0.18);
  }
  .sections-head {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
    margin-bottom: -6px;
  }
  .sections {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .section {
    padding: 8px 12px 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .section header,
  .big header {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .fold {
    display: flex;
    align-items: center;
    gap: 8px;
    border: 0;
    background: none;
    padding: 4px 2px;
    min-width: 0;
    flex: 1;
    text-align: left;
    font-size: 13.5px;
  }
  .chev {
    display: inline-grid;
    color: var(--muted);
    transition: transform 0.15s;
  }
  .chev.closed {
    transform: rotate(-90deg);
  }
  .stitle {
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .kindtag {
    height: 20px;
    font-size: 11px;
    flex: none;
  }
  .fold .small {
    flex: none;
  }
  .pager {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: none;
  }
  .grid {
    display: grid;
    gap: 12px;
  }
  .bestnote {
    margin: 0;
  }
  .prall {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-width: 760px;
    margin-bottom: 4px;
  }
  .prhead {
    display: flex;
    align-items: center;
    gap: 6px;
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
    cursor: pointer;
  }
  .icon:hover {
    background: var(--panel-2);
    color: var(--accent);
  }
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: color-mix(in srgb, var(--bg) 70%, transparent);
    backdrop-filter: blur(2px);
    display: grid;
    place-items: center;
    padding: 24px;
  }
  .big {
    width: min(1100px, 100%);
    max-height: calc(100vh - 48px);
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: auto;
  }
  .bigbody :global(img) {
    image-rendering: auto;
    max-height: calc(100vh - 160px);
    object-fit: contain;
  }
  .bigbody :global(iframe) {
    height: 70vh;
  }
  .bigbody :global(pre) {
    max-height: none;
  }
</style>
