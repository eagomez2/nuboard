<script lang="ts">
  import DownloadMenu, { type DownloadOption } from './DownloadMenu.svelte';
  import Icon from './Icon.svelte';
  import MediaView from './MediaView.svelte';
  import type { MediaItem, RunBrief } from '../lib/api';
  import { api } from '../lib/api';
  import { extensionOf, HIST_MIME, PR_MIME, TABLE_MIME, WAVEFORM_MIME, type AudioOptions } from '../lib/media';
  import { chartToPng } from '../lib/snapshot';
  import { tableCsv, type TableData } from '../lib/tables';
  import { sideBySide, wordDiff, type WordPart } from '../lib/diff';

  // One run's items under one key, with its own step slider (as in TensorBoard).
  let {
    run,
    items,
    target,
    nearest = false,
    title,
    tip = '',
    color,
    player,
    audioOptions,
    onsave,
    onzoom,
    selecting = false,
    isSelected = () => false,
    onselect = () => {},
    pinned = false,
    onpin,
    peers = [],
  }: {
    run: RunBrief;
    items: MediaItem[];
    target: number | null; // null: the latest step
    nearest?: boolean; // closest step to `target` (best-step mode) instead of the last one before it
    title: string;
    tip?: string; // the full key, when the title shows only part of it
    color: string;
    player: string;
    audioOptions: AudioOptions;
    onsave: (it: MediaItem) => void;
    onzoom: (it: MediaItem) => void;
    selecting?: boolean; // show a checkbox to pick the shown item for a report
    isSelected?: (it: MediaItem) => boolean;
    onselect?: (it: MediaItem, on: boolean) => void;
    pinned?: boolean;
    onpin?: () => void; // shows the pin button
    peers?: { run: RunBrief; items: MediaItem[] }[]; // other runs' items under the same key, to diff text with
  } = $props();

  // A step picked on this card's own slider; cleared whenever the page-wide step changes.
  let own = $state<number | null>(null);
  $effect(() => {
    void target;
    own = null;
  });

  const steps = $derived(items.map((i) => i.step));
  const shownIdx = $derived.by(() => {
    if (!items.length) return -1;
    const want = own ?? target;
    if (want === null) return items.length - 1;
    if (nearest && own === null) {
      let best = 0;
      for (let i = 1; i < items.length; i++)
        if (Math.abs(items[i].step - want) < Math.abs(items[best].step - want)) best = i;
      return best;
    }
    let idx = 0;
    for (let i = 0; i < items.length; i++) if (items[i].step <= want) idx = i;
    return idx;
  });
  const it = $derived(shownIdx >= 0 ? items[shownIdx] : null);
  // figures logged as library JSON, named after the library
  const FORMAT: Record<string, string> = {
    '.plotly.json': 'Plotly JSON',
    '.vl.json': 'Vega-Lite JSON',
    '.bokeh.json': 'Bokeh JSON',
  };
  // the formats the shown item downloads as: the file as logged, and for some kinds a second one
  let fig: HTMLElement;
  const downloads = $derived.by((): DownloadOption[] => {
    if (!it || it.index === undefined) return [];
    const url = api.mediaUrl(run.key, it.index);
    const base = `${run.name}-${it.key.replaceAll('/', '_')}-${it.step}`;
    const ext = extensionOf(it.mime);
    const chart = it.mime === PR_MIME || it.mime === HIST_MIME;
    const own: DownloadOption = {
      label: chart ? 'JSON data' : (FORMAT[ext] ?? ext.replace(/^\./, '').toUpperCase()),
      hint: chart
        ? 'The points behind the chart'
        : FORMAT[ext]
          ? 'To open again in its library'
          : it.mime === TABLE_MIME
            ? 'The columns and rows'
            : 'The file as logged',
      filename: base + ext,
      href: url,
    };
    if (it.mime === TABLE_MIME)
      return [
        own,
        {
          label: 'CSV',
          hint: 'For spreadsheets',
          filename: `${base}.csv`,
          make: async () => {
            const r = await fetch(url);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return new Blob([tableCsv((await r.json()) as TableData)], { type: 'text/csv' });
          },
        },
      ];
    if (chart)
      return [
        {
          label: 'PNG',
          hint: 'The chart as shown',
          filename: `${base}.png`,
          make: async () => (await fetch(await chartToPng(fig, `${it.key} · ${run.name}`))).blob(),
        },
        own,
      ];
    return [own];
  });
  // ---- text diffs: the shown text against the step before it, or another run's text ----
  let diffOn = $state(false);
  let against = $state('prev'); // 'prev', or a peer's run key
  const canDiff = $derived(!!it && it.kind === 'text' && (shownIdx > 0 || peers.length > 0));
  /** The item of `list` shown for `step`: the last one at or before it, else the first. */
  const atStep = (list: MediaItem[], step: number) => {
    let found: MediaItem | null = list[0] ?? null;
    for (const x of list) if (x.step <= step) found = x;
    return found;
  };
  const base = $derived.by((): { label: string; text: string } | null => {
    if (!it || !diffOn) return null;
    if (against === 'prev') {
      const prev = shownIdx > 0 ? items[shownIdx - 1] : null;
      return prev ? { label: `step ${prev.step.toLocaleString()}`, text: prev.text ?? '' } : null;
    }
    const peer = peers.find((p) => p.run.key === against);
    const other = peer ? atStep(peer.items, it.step) : null;
    return peer && other
      ? { label: `${peer.run.name} · step ${other.step.toLocaleString()}`, text: other.text ?? '' }
      : null;
  });
  type DiffLine = { sign: ' ' | '+' | '-'; parts: WordPart[] };
  const diffLines = $derived.by((): DiffLine[] => {
    if (!base || !it) return [];
    const out: DiffLine[] = [];
    for (const r of sideBySide(base.text, it.text ?? '')) {
      if (r.kind === 'same') out.push({ sign: ' ', parts: [{ text: r.left ?? '', changed: false }] });
      else if (r.left !== null && r.right !== null) {
        // a changed line: mark the words that differ
        const [a, b] = wordDiff(r.left, r.right);
        out.push({ sign: '-', parts: a }, { sign: '+', parts: b });
      } else if (r.left !== null) out.push({ sign: '-', parts: [{ text: r.left, changed: false }] });
      else if (r.right !== null) out.push({ sign: '+', parts: [{ text: r.right, changed: false }] });
    }
    return out;
  });
  const added = $derived(diffLines.filter((l) => l.sign === '+').length);
  const removed = $derived(diffLines.filter((l) => l.sign === '-').length);

  const zoomable = $derived(!!it && it.kind !== 'audio' && !it.mime.startsWith('audio/'));
</script>

<figure bind:this={fig} class="card cell" class:picked={selecting && !!it && isSelected(it)}>
  <figcaption>
    {#if selecting && it}
      <input
        type="checkbox"
        class="pick"
        aria-label="Select {title} at step {it.step}"
        checked={isSelected(it)}
        onchange={(e) => onselect(it, e.currentTarget.checked)}
      />
    {/if}
    <i class="dot" style="background:{color}"></i>
    <span class="mono name" title="{tip ? `${tip}\n` : ''}{run.name}&#10;{run.path}">{title}</span>
    {#if it}<span class="faint mono step">Step {it.step.toLocaleString()}</span>{/if}
    {#if onpin}
      <button
        class="icon pin"
        class:on={pinned}
        aria-pressed={pinned}
        title={pinned ? 'Unpin' : 'Pin to the top, to compare it with other pinned items'}
        aria-label={pinned ? `Unpin ${title}` : `Pin ${title}`}
        onclick={onpin}><Icon name="pin" size={14} /></button
      >
    {/if}
    {#if it}
      <span class="acts">
        {#if canDiff}
          <button
            class="icon"
            class:on={diffOn}
            aria-pressed={diffOn}
            title={diffOn ? 'Show the text' : 'Show what changed: from the step before, or from another run'}
            aria-label="Show changes"
            onclick={() => (diffOn = !diffOn)}><Icon name="compare" size={14} /></button
          >
        {/if}
        {#if zoomable}
          <button class="icon" title="Open large" aria-label="Open large" onclick={() => onzoom(it)}
            ><Icon name="search" size={14} /></button
          >
        {/if}
        {#if it.index !== undefined && it.mime !== WAVEFORM_MIME}
          <!-- a waveform figure has its own Download menu: the audio, or the audio with its signals -->
          <DownloadMenu options={downloads} />
        {/if}
        <button class="icon" title="Add to a report" aria-label="Add to a report" onclick={() => onsave(it)}
          ><Icon name="bookmark" size={14} /></button
        >
      </span>
    {/if}
  </figcaption>
  {#if !it}
    <div class="none faint">Nothing logged under this key</div>
  {:else if diffOn && canDiff}
    <div class="diffbar">
      <span class="faint">Changes from</span>
      <select class="input sm" aria-label="Compare with" bind:value={against}>
        <option value="prev" disabled={shownIdx < 1}>the step before</option>
        {#each peers as p (p.run.key)}<option value={p.run.key}>{p.run.name}</option>{/each}
      </select>
      {#if base}<span class="mono counts"><span class="plus">+{added}</span> <span class="minus">−{removed}</span></span
        >{/if}
    </div>
    {#if base}
      <pre class="text diff mono" aria-label="Changes from {base.label}">{#each diffLines as l, i (i)}<span
            class="dl"
            class:add={l.sign === '+'}
            class:del={l.sign === '-'}
            >{l.sign} {#each l.parts as w, j (j)}<span class:w={w.changed}>{w.text}</span>{/each}</span
          >{/each}</pre>
    {:else}
      <div class="none faint">Nothing to compare with</div>
    {/if}
  {:else}
    <MediaView runKey={run.key} runName={run.name} item={it} {player} {audioOptions} group={it.key} {color} />
  {/if}
  {#if steps.length > 1}
    <label class="slider">
      <input
        type="range"
        min="0"
        max={steps.length - 1}
        value={shownIdx}
        aria-label="Step of {title}"
        oninput={(e) => (own = steps[Number(e.currentTarget.value)])}
      />
      <span class="faint mono">{shownIdx + 1}/{steps.length}</span>
    </label>
  {/if}
</figure>

<style>
  .cell {
    margin: 0;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .picked {
    outline: 2px solid var(--accent);
    outline-offset: -1px;
  }
  .pick {
    margin: 0;
    accent-color: var(--accent);
    flex: none;
  }
  figcaption {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    min-width: 0;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    flex: 1;
  }
  .step {
    flex: none;
    font-size: 11.5px;
  }
  .acts {
    display: inline-flex;
    gap: 2px;
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
  }
  .icon:hover {
    background: var(--panel-2);
    color: var(--accent);
  }
  .pin {
    flex: none;
  }
  .icon.on {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .diffbar {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    min-width: 0;
  }
  .diffbar select {
    min-width: 0;
    flex: 1;
    max-width: 220px;
  }
  .counts {
    margin-left: auto;
    font-size: 12px;
  }
  .plus {
    color: var(--ansi-2);
  }
  .minus {
    color: var(--err);
  }
  .text {
    margin: 0;
    white-space: pre-wrap;
    font-size: 12.5px;
    background: var(--panel-2);
    border-radius: 8px;
    padding: 10px;
    max-height: 260px;
    overflow: auto;
  }
  .dl {
    display: block;
    min-height: 1.45em;
  }
  .dl.add {
    background: var(--diff-add);
  }
  .dl.del {
    background: var(--diff-del);
  }
  .dl.del .w {
    border-radius: 3px;
    background: color-mix(in srgb, var(--err) 30%, transparent);
  }
  .dl.add .w {
    border-radius: 3px;
    background: color-mix(in srgb, var(--accent) 30%, transparent);
  }
  .pin.on {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .faint {
    color: var(--faint);
  }
  .none {
    padding: 24px 8px;
    text-align: center;
    font-size: 13px;
  }
  .slider {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
  }
  .slider input {
    flex: 1;
    min-width: 0;
    accent-color: var(--accent);
  }
</style>
