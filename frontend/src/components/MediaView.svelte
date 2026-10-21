<script lang="ts">
  import AudioFrame from './AudioFrame.svelte';
  import FigureFrame from './FigureFrame.svelte';
  import HistView from './HistView.svelte';
  import PointsView from './PointsView.svelte';
  import PrChart from './PrChart.svelte';
  import TableView from './TableView.svelte';
  import VideoView from './VideoView.svelte';
  import WaveformPlot from './WaveformPlot.svelte';
  import { api, type AudioNote, type MediaItem } from '../lib/api';
  import { notice } from '../lib/dialog.svelte';
  import { HIST_MIME, POINTS_MIME, PR_MIME, TABLE_MIME, WAVEFORM_MIME, type AudioOptions } from '../lib/media';

  // One logged item (image, audio, figure, HTML or text) of a run.
  let {
    runKey,
    runName,
    item,
    player = 'wave',
    audioOptions = { colormap: 'theme', scale: 'linear', fftSize: 1024, spectrogram: true },
    group = '',
    tall = false,
    color = 'var(--s1)',
  }: {
    runKey: string;
    runName: string;
    item: MediaItem;
    player?: string;
    audioOptions?: AudioOptions;
    group?: string;
    /** Draw point clouds taller, as in the zoomed view. */
    tall?: boolean;
    /** The run's series color, for curves. */
    color?: string;
  } = $props();

  // Notes on the audio, saved in the run's annotations.json
  let notes = $derived<AudioNote[]>(item.notes ?? []);
  async function saveNotes(next: AudioNote[]) {
    const before = notes;
    notes = next;
    try {
      notes = (await api.setAudioNotes(runKey, `${item.key}@${item.step}`, next)).notes;
      item.notes = notes;
    } catch (e) {
      notes = before;
      notice('Note not saved', String(e instanceof Error ? e.message : e).replace(/^\d+ /, ''));
    }
  }

  const url = $derived(item.index === undefined ? '' : api.mediaUrl(runKey, item.index));

  // Logged HTML: the rendered output, or its source with line numbers
  let htmlView = $state<'output' | 'code'>('output');
  let source = $state<string | null>(null);
  $effect(() => {
    if (htmlView !== 'code' || item.mime !== 'text/html' || !url) return;
    source = null;
    fetch(url)
      .then((r) => r.text())
      .then((t) => (source = t))
      .catch(() => (source = ''));
  });
  const sourceLines = $derived((source ?? '').replace(/\n$/, '').split('\n'));
</script>

{#if item.kind === 'text'}
  <pre class="text mono">{item.text}</pre>
{:else if item.mime === 'text/html'}
  <div class="seg htmlseg" role="group" aria-label="Show HTML as">
    <button aria-pressed={htmlView === 'output'} onclick={() => (htmlView = 'output')}>Output</button>
    <button aria-pressed={htmlView === 'code'} onclick={() => (htmlView = 'code')}>Code</button>
  </div>
  {#if htmlView === 'output'}
    <iframe title="{runName} {item.key}" sandbox="allow-scripts" src={url}></iframe>
  {:else if source === null}
    <div class="none faint">Loading…</div>
  {:else}
    <div class="code mono" role="region" aria-label="HTML source of {item.key}">
      {#each sourceLines as line, i (i)}
        <span class="ln">{i + 1}</span>
        <span class="lc">{line}</span>
      {/each}
    </div>
  {/if}
{:else if item.kind === 'video' || item.mime.startsWith('video/')}
  <VideoView {url} mime={item.mime} label="{runName} {item.key}" caption={item.caption} />
{:else if item.mime.startsWith('image/')}
  <img src={url} alt={item.caption ?? item.key} />
  {#if item.caption}<div class="faint cap">{item.caption}</div>{/if}
{:else if item.kind === 'audio' || item.mime.startsWith('audio/')}
  {#if player === 'wave'}
    <AudioFrame
      {url}
      title="{runName} {item.key}"
      sampleRate={item.sample_rate}
      channels={item.channels}
      duration={item.duration ?? undefined}
      group={group || item.key}
      options={audioOptions}
      header={{ label: runName, name: `${item.key} · step ${item.step}`, tags: item.caption ? [item.caption] : [] }}
      {notes}
      onnotes={saveNotes}
    />
  {:else}
    <audio controls preload="metadata" src={url}></audio>
  {/if}
  <div class="faint cap mono">
    {[
      item.caption,
      item.duration != null ? `${item.duration.toFixed(2)} s` : null,
      item.sample_rate ? `${item.sample_rate / 1000} kHz` : null,
      item.channels ? (item.channels === 1 ? 'mono' : `${item.channels} ch`) : null,
    ]
      .filter(Boolean)
      .join(' · ')}
  </div>
{:else if item.mime === WAVEFORM_MIME}
  <WaveformPlot
    {url}
    title="{runName} {item.key}"
    names={item.signals ?? []}
    range={item.range ?? [-1, 1]}
    offset={item.audio_bytes ?? 0}
    samples={item.samples ?? 0}
    height={tall ? 460 : 240}
  />
  <div class="faint cap mono">
    {#each item.signals ?? [] as name, i (name)}
      <span class="sig"><i style="background:var(--s{(i % 7) + 2})"></i>{name}</span>
    {/each}
    {[
      item.caption,
      item.duration != null ? `${item.duration.toFixed(2)} s` : null,
      item.sample_rate ? `${item.sample_rate / 1000} kHz` : null,
    ]
      .filter(Boolean)
      .join(' · ')}
  </div>
{:else if item.mime === TABLE_MIME}
  <TableView {runKey} {runName} {item} />
{:else if item.mime === PR_MIME}
  <PrChart
    curves={[{ name: runName, color, url }]}
    height={tall ? 460 : 220}
    label="Precision-recall curve of {runName} {item.key} at step {item.step}"
  />
{:else if item.mime === HIST_MIME}
  <HistView {runKey} {runName} {item} {color} height={tall ? 420 : 220} />
  {#if item.caption}<div class="faint cap">{item.caption}</div>{/if}
{:else if item.mime === POINTS_MIME}
  {#key url}
    <PointsView
      {url}
      count={item.points ?? 0}
      colors={!!item.colors}
      axes={item.axes}
      title="{runName} {item.key}"
      height={tall ? 560 : 260}
    />
  {/key}
  {#if item.caption}<div class="faint cap">{item.caption}</div>{/if}
{:else if /plotly|vega|bokeh/.test(item.mime)}
  <FigureFrame {url} mime={item.mime} title="{runName} {item.key}" />
{:else}
  <div class="none"><a href={url} download>{item.mime}</a></div>
{/if}

<style>
  img {
    display: block;
    width: 100%;
    image-rendering: pixelated;
    border-radius: 8px;
    background: var(--panel-2);
  }
  iframe {
    width: 100%;
    height: 220px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: #fff;
  }
  audio {
    width: 100%;
  }
  .htmlseg {
    align-self: flex-start;
    margin-bottom: 6px;
  }
  .htmlseg button {
    height: 24px;
    font-size: 11.5px;
  }
  .code {
    margin: 0;
    height: 220px;
    overflow: auto;
    font-size: 12px;
    line-height: 1.5;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 0;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-content: start;
  }
  .ln {
    color: var(--faint);
    text-align: right;
    padding: 0 10px 0 10px;
    user-select: none;
    border-right: 1px solid var(--border);
  }
  .lc {
    padding: 0 10px;
    white-space: pre;
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
  .none {
    padding: 24px 8px;
    text-align: center;
    font-size: 13px;
  }
  .faint {
    color: var(--faint);
  }
  .sig {
    margin-right: 10px;
  }
  .sig i {
    display: inline-block;
    width: 10px;
    height: 3px;
    border-radius: 2px;
    margin-right: 5px;
    vertical-align: middle;
  }
  .cap {
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
