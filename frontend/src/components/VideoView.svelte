<script lang="ts">
  import { decodeApng, type Apng } from '../lib/apng';

  // A logged video: files play in the browser's own player; arrays, stored as an
  // animated PNG, play here frame by frame, with a slider to step through them.
  let { url, mime, label, caption }: { url: string; mime: string; label: string; caption?: string | null } = $props();

  let anim = $state<Apng | null>(null);
  let failed = $state(false);
  let frame = $state(0);
  let playing = $state(true);
  let canvas = $state<HTMLCanvasElement>();

  $effect(() => {
    if (mime !== 'image/apng') return;
    let cancelled = false;
    anim = null;
    failed = false;
    frame = 0;
    fetch(url)
      .then((r) => r.arrayBuffer())
      .then(decodeApng)
      .then((a) => {
        if (cancelled) return;
        anim = a;
        failed = !a;
      })
      .catch(() => (failed = true));
    return () => {
      cancelled = true;
    };
  });

  // draw the current frame
  $effect(() => {
    const f = anim?.frames[frame];
    const ctx = canvas?.getContext('2d');
    if (!f || !ctx || !anim) return;
    ctx.clearRect(0, 0, anim.width, anim.height);
    ctx.drawImage(f.image, 0, 0);
  });

  // advance while playing, each frame for its own delay
  $effect(() => {
    if (!anim || !playing) return;
    const n = anim.frames.length;
    const timer = setTimeout(() => (frame = (frame + 1) % n), Math.max(10, anim.frames[frame].delay * 1000));
    return () => clearTimeout(timer);
  });

  const fps = $derived(anim?.frames[0]?.delay ? Math.round(10 / anim.frames[0].delay) / 10 : null);
</script>

{#if mime.startsWith('video/')}
  <video src={url} controls loop muted playsinline aria-label={label}></video>
{:else if mime === 'image/apng' && !failed}
  <div class="vid">
    {#if anim}
      <canvas bind:this={canvas} width={anim.width} height={anim.height} aria-label={label}></canvas>
      <div class="bar">
        <button class="btn btn-ghost sm" aria-label={playing ? 'Pause' : 'Play'} onclick={() => (playing = !playing)}
          >{playing ? '❚❚' : '▶'}</button
        >
        <input
          type="range"
          min="0"
          max={anim.frames.length - 1}
          bind:value={frame}
          oninput={() => (playing = false)}
          aria-label="Frame"
        />
        <span class="mono faint">{frame + 1}/{anim.frames.length}{fps ? ` · ${fps} fps` : ''}</span>
      </div>
    {:else}
      <div class="faint">Loading video…</div>
    {/if}
  </div>
{:else}
  <img src={url} alt={label} />
{/if}
{#if caption}<div class="faint cap">{caption}</div>{/if}

<style>
  video,
  canvas,
  img {
    display: block;
    width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 8px;
    background: var(--panel-2, transparent);
  }
  canvas {
    image-rendering: pixelated;
    height: auto;
  }
  .vid {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }
  .bar input {
    flex: 1;
    min-width: 0;
  }
  .sm {
    height: 24px;
    padding: 0 6px;
    font-size: 11px;
  }
  .faint {
    color: var(--faint);
  }
  .cap {
    font-size: 12.5px;
    margin-top: 4px;
  }
</style>
