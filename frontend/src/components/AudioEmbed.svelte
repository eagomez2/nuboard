<script lang="ts">
  import AudioFrame from './AudioFrame.svelte';

  // An audio file uploaded into a report, `[caption](files/x.wav)`: the waveform player, captioned.
  let { src, caption = '' }: { src: string; caption?: string } = $props();

  const name = $derived(src.split('/').pop() ?? '');
</script>

<figure class="embed">
  <AudioFrame
    url={src}
    title={caption || name}
    group={src}
    options={{ colormap: 'theme', scale: 'linear', fftSize: 1024, spectrogram: true, axis: true }}
    header={{ label: caption || name, name: '', tags: [] }}
  />
  <figcaption>
    {#if caption}<span class="cap">{caption}</span>{/if}
    <span class="faint mono">{name} · <a href={src} download>Download</a></span>
  </figcaption>
</figure>

<style>
  .embed {
    margin: 0.8em 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 760px;
  }
  figcaption {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
  }
  .cap {
    color: var(--text);
  }
  .faint {
    color: var(--faint);
    font-size: 12px;
  }
</style>
