<script lang="ts">
  import { onMount } from 'svelte';
  import type { AudioNote } from '../lib/api';
  import type { AudioOptions } from '../lib/media';
  import { app } from '../lib/state.svelte';

  /**
   * The waveform + spectrogram player (ported from audioviewer), in a
   * same-origin iframe so its script, styles and keyboard shortcuts stay
   * self-contained. Players with the same `group` follow each other's zoom,
   * scroll, cursor and selection, and starting one pauses the others.
   * With `onnotes`, a selection can carry a note; the player sends each
   * added, edited or deleted note and the new list goes to `onnotes`.
   */
  let {
    url,
    title,
    sampleRate,
    channels,
    duration,
    group,
    header,
    options,
    notes = [],
    onnotes,
  }: {
    url: string;
    title: string;
    sampleRate?: number;
    channels?: number;
    duration?: number;
    group: string;
    header: { label?: string; name?: string; tags?: string[] };
    /** Spectrogram colormap, frequency scale and window, and the amplitude axis (see MediaPage's options). */
    options: AudioOptions;
    notes?: AudioNote[];
    onnotes?: (notes: AudioNote[]) => void;
  } = $props();

  let frame = $state<HTMLIFrameElement | null>(null);
  let height = $state(300);
  let ready = false;

  function theme() {
    const css = getComputedStyle(document.documentElement);
    const v = (name: string) => css.getPropertyValue(name).trim();
    return {
      base: app.theme,
      textColor: v('--text'),
      backgroundColor: v('--panel'),
      secondaryBackgroundColor: v('--panel-2'),
      primaryColor: v('--accent'),
      font: v('--sans'),
      fontMono: v('--mono'),
    };
  }

  function send() {
    if (!ready || !frame?.contentWindow) return;
    const args = {
      url,
      sampleRate: sampleRate ?? 0,
      channels: channels ?? 1,
      duration: duration ?? 0,
      group,
      link: true,
      scale: options.scale,
      fftSize: options.fftSize,
      colormap: options.colormap,
      waveHeight: 72,
      spectrogramHeight: options.spectrogram ? 140 : 0,
      axis: options.axis,
      normalize: false,
      notes: !!onnotes,
      annotations: $state.snapshot(notes),
      header,
    };
    frame.contentWindow.postMessage({ type: 'nb-audio:render', args, theme: theme() }, location.origin);
  }

  onMount(() => {
    const onMessage = (e: MessageEvent) => {
      if (!frame || e.source !== frame.contentWindow || e.origin !== location.origin) return;
      if (e.data?.type === 'nb-audio:ready') {
        ready = true;
        send();
      } else if (e.data?.type === 'nb-audio:height') {
        height = Math.max(Number(e.data.height) || 0, 60);
      } else if (e.data?.type === 'nb-audio:note' && onnotes) {
        const note = e.data.value as AudioNote;
        onnotes([...notes.filter((n) => n.id !== note.id), note].sort((a, b) => a.start - b.start));
      } else if (e.data?.type === 'nb-audio:note-delete' && onnotes) {
        onnotes(notes.filter((n) => n.id !== e.data.id));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });

  // a new clip (step slider), theme or option re-renders the player
  $effect(() => {
    void [
      url,
      app.theme,
      app.themeVersion,
      options.colormap,
      options.scale,
      options.fftSize,
      options.spectrogram,
      options.axis,
    ];
    void notes;
    send();
  });
</script>

<iframe bind:this={frame} {title} src="./audio.html" style="height:{height}px"></iframe>

<style>
  iframe {
    width: 100%;
    border: 0;
    display: block;
    background: transparent;
  }
</style>
