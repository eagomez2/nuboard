<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy, untrack } from 'svelte';
  import { app } from '../lib/state.svelte';
  import { waveformKit } from '../lib/waveform';
  import { mountWaveform, type WaveformNote } from '../lib/waveplot';
  import '../lib/waveplot.css';

  /**
   * A waveform figure: the audio with its signals over it (see lib/waveplot.ts, which an HTML export
   * of a report uses too, so the exported figure looks and works the same).
   */
  let {
    url,
    title,
    names,
    range = [-1, 1],
    offset,
    samples,
    caption = null,
    height = 240,
    regions = null,
    notes = [],
    onnotes,
  }: {
    url: string;
    title: string;
    names: string[];
    /** The values at the bottom and top of the plot. */
    range?: [number, number];
    /** Bytes of the WAV at the start of the item, then `samples` float32 values per signal. */
    offset: number;
    samples: number;
    caption?: string | null;
    height?: number;
    /** Labelled regions logged with the figure, by track. */
    regions?: Record<string, [number, number, string][]> | null;
    /** Notes added in the viewer; `onnotes` gets the new list after each change. */
    notes?: WaveformNote[];
    onnotes?: (notes: WaveformNote[]) => void;
  } = $props();

  const kit = waveformKit();
  let box: HTMLDivElement;
  let error = $state('');
  let mounted: ReturnType<typeof mountWaveform> | null = null;
  let audioUrl = '';

  function unmount() {
    mounted?.destroy();
    mounted = null;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = '';
  }

  // load the item: a new one (the step slider) starts at the whole clip
  $effect(() => {
    const target = url;
    const opts = {
      offset,
      names: $state.snapshot(names),
      range: $state.snapshot(range),
      samples,
      caption,
      height,
      regions: $state.snapshot(regions),
      onnotes,
    };
    error = '';
    fetch(target)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then((buffer) => {
        if (target !== url) return;
        unmount();
        audioUrl = URL.createObjectURL(new Blob([buffer.slice(0, opts.offset)], { type: 'audio/wav' }));
        // the notes as they are now; later changes go to setNotes below
        const current = untrack(() => $state.snapshot(notes));
        mounted = mountWaveform(box, kit, uPlot, { buffer, audioSrc: audioUrl, notes: current, ...opts });
      })
      .catch((e) => (error = `Could not load the waveform: ${e instanceof Error ? e.message : e}`));
  });

  $effect(() => {
    const next = $state.snapshot(notes);
    untrack(() => mounted?.setNotes(next));
  });

  // the app's own colors changed (the light/dark switch is followed by the plot itself)
  $effect(() => {
    void app.themeVersion;
    mounted?.restyle();
  });

  onDestroy(unmount);
</script>

{#if error}<div class="nbwf-err">{error}</div>{/if}
<div bind:this={box} role="group" aria-label={title}></div>
