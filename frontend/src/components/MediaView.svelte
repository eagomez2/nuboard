<script lang="ts">
  import AudioFrame from './AudioFrame.svelte';
  import FigureFrame from './FigureFrame.svelte';
  import { api, type MediaItem } from '../lib/api';
  import type { AudioOptions } from '../lib/media';

  // One logged item (image, audio, figure, HTML or text) of a run.
  let {
    runKey,
    runName,
    item,
    player = 'wave',
    audioOptions = { colormap: 'theme', scale: 'linear', fftSize: 1024, spectrogram: true },
    group = '',
  }: {
    runKey: string;
    runName: string;
    item: MediaItem;
    player?: string;
    audioOptions?: AudioOptions;
    group?: string;
  } = $props();

  const url = $derived(item.index === undefined ? '' : api.mediaUrl(runKey, item.index));
</script>

{#if item.kind === 'text'}
  <pre class="text mono">{item.text}</pre>
{:else if item.mime === 'text/html'}
  <iframe title="{runName} {item.key}" sandbox="allow-scripts" src={url}></iframe>
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
  .cap {
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
