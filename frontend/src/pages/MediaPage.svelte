<script lang="ts">
  import AudioFrame from '../components/AudioFrame.svelte';
  import FigureFrame from '../components/FigureFrame.svelte';
  import { api, type MediaItem } from '../lib/api';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const MAX_RUNS = 16;
  const runs = $derived(app.visibleRuns().slice(0, MAX_RUNS));
  let items = $state<Record<string, MediaItem[]>>({});

  $effect(() => {
    const keys = runs.map((r) => r.key);
    Promise.all(keys.map((k) => api.media(k).then((res) => [k, res.items] as const))).then((pairs) => {
      items = Object.fromEntries(pairs);
    });
  });

  const mediaKeys = $derived.by(() => {
    const map = new Map<string, { kind: string; runs: number }>();
    for (const list of Object.values(items)) {
      const seen = new Set<string>();
      for (const it of list) {
        if (!map.has(it.key)) map.set(it.key, { kind: it.kind, runs: 0 });
        if (!seen.has(it.key)) {
          map.get(it.key)!.runs++;
          seen.add(it.key);
        }
      }
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  });
  const key = $derived(
    mediaKeys.some(([k]) => k === router.get('mkey')) ? router.get('mkey') : (mediaKeys[0]?.[0] ?? ''),
  );
  const steps = $derived(
    [...new Set(Object.values(items).flatMap((l) => l.filter((i) => i.key === key).map((i) => i.step)))].sort(
      (a, b) => a - b,
    ),
  );
  const stepIdx = $derived(
    Math.min(
      steps.length - 1,
      Math.max(0, router.get('mstep') ? steps.findIndex((s) => s >= Number(router.get('mstep'))) : steps.length - 1),
    ),
  );
  const step = $derived(steps[stepIdx === -1 ? steps.length - 1 : stepIdx]);

  const kind = $derived(mediaKeys.find(([k]) => k === key)?.[1].kind);
  // Waveform player (default) or the browser's own audio controls
  const player = $derived(router.get('player', prefs.get('player', 'wave')));
  function setPlayer(p: string) {
    prefs.set('player', p);
    router.set({ player: p === 'wave' ? null : p });
  }

  function at(runKey: string): MediaItem | null {
    const list = (items[runKey] ?? []).filter((i) => i.key === key && i.step <= step);
    return list.length ? list[list.length - 1] : null;
  }
</script>

{#if !runs.length}
  <div class="card empty">No runs selected. Pick runs on the Runs page and press “Media”.</div>
{:else if !mediaKeys.length}
  <div class="card empty">
    These runs logged no images, audio, figures, HTML or text. Use <code>run.log_image</code>,
    <code>log_audio</code>, <code>log_figure</code>, <code>log_html</code>
    or <code>log_text</code>.
  </div>
{:else}
  <div class="card bar">
    <div class="keys">
      {#each mediaKeys as [k, info] (k)}
        <button class="tab mono" aria-pressed={k === key} onclick={() => router.set({ mkey: k, mstep: null })}
          >{k} <span class="faint">{info.kind}</span></button
        >
      {/each}
    </div>
    {#if kind === 'audio'}
      <div class="players">
        <span class="faint">player</span>
        <div class="seg">
          <button aria-pressed={player === 'wave'} onclick={() => setPlayer('wave')}>waveform</button>
          <button aria-pressed={player === 'simple'} onclick={() => setPlayer('simple')}>simple</button>
        </div>
        {#if player === 'wave'}
          <span class="faint hint"
            >players follow each other's zoom, scroll and selection · space plays · drag to select · ctrl + wheel zooms</span
          >
        {/if}
      </div>
    {/if}
    {#if steps.length > 1}
      <label class="slider">
        <span class="mono">step {step?.toLocaleString()}</span>
        <input
          type="range"
          min="0"
          max={steps.length - 1}
          value={stepIdx}
          oninput={(e) => router.set({ mstep: steps[Number((e.currentTarget as HTMLInputElement).value)] })}
        />
        <span class="faint mono">{steps.length} steps</span>
      </label>
    {/if}
  </div>
  <div class="grid" class:wide={kind !== 'image'} class:audio={kind === 'audio' && player === 'wave'}>
    {#each runs as r (r.key)}
      {@const it = at(r.key)}
      <figure class="card cell">
        <figcaption>
          <span class="mono name">{r.name}</span>{#if it}<span class="faint mono">step {it.step}</span>{/if}
        </figcaption>
        {#if !it}
          <div class="none faint">nothing logged yet</div>
        {:else if it.kind === 'text'}
          <pre class="text mono">{it.text}</pre>
        {:else if it.mime === 'text/html'}
          <iframe title="{r.name} {it.key}" sandbox="allow-scripts" src={api.mediaUrl(r.key, it.index!)}></iframe>
        {:else if it.mime.startsWith('image/')}
          <img src={api.mediaUrl(r.key, it.index!)} alt={it.caption ?? it.key} />
          {#if it.caption}<div class="faint cap">{it.caption}</div>{/if}
        {:else if it.kind === 'audio' || it.mime.startsWith('audio/')}
          {#if player === 'wave'}
            <AudioFrame
              url={api.mediaUrl(r.key, it.index!)}
              title="{r.name} {it.key}"
              sampleRate={it.sample_rate}
              channels={it.channels}
              duration={it.duration ?? undefined}
              group={`${key}`}
              header={{ label: r.name, name: `${it.key} · step ${it.step}`, tags: it.caption ? [it.caption] : [] }}
            />
          {:else}
            <audio controls preload="metadata" src={api.mediaUrl(r.key, it.index!)}></audio>
          {/if}
          <div class="faint cap mono">
            {[
              it.caption,
              it.duration != null ? `${it.duration.toFixed(2)} s` : null,
              it.sample_rate ? `${it.sample_rate / 1000} kHz` : null,
              it.channels ? (it.channels === 1 ? 'mono' : `${it.channels} ch`) : null,
            ]
              .filter(Boolean)
              .join(' · ')}
            ·
            <a href={api.mediaUrl(r.key, it.index!)} download="{r.name}-{it.key.replaceAll('/', '_')}-{it.step}"
              >download</a
            >
          </div>
        {:else if /plotly|vega|bokeh/.test(it.mime)}
          <FigureFrame url={api.mediaUrl(r.key, it.index!)} mime={it.mime} title="{r.name} {it.key}" />
        {:else}
          <div class="none">
            <a href={api.mediaUrl(r.key, it.index!)} download>{it.mime}</a>
          </div>
        {/if}
      </figure>
    {/each}
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
  .bar {
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .keys {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .tab {
    border: 1px solid var(--border);
    background: var(--panel-2);
    border-radius: 8px;
    padding: 5px 12px;
    font-size: 13px;
    color: var(--muted);
  }
  .tab[aria-pressed='true'] {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
    font-weight: 600;
  }
  .tab .faint {
    font-weight: 400;
    font-size: 11.5px;
    margin-left: 4px;
  }
  .slider {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .slider input {
    flex: 1;
    accent-color: var(--accent);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
  }
  .grid.wide {
    grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  }
  .grid.audio {
    grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
  }
  audio {
    width: 100%;
  }
  .cap a {
    color: var(--accent);
  }
  .players {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
  }
  .players .hint {
    font-size: 12px;
  }
  .cell {
    margin: 0;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  figcaption {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 12.5px;
  }
  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  img {
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
  .cap {
    font-size: 12px;
  }
</style>
