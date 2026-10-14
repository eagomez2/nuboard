<script lang="ts">
  import { onMount } from 'svelte';
  import { app } from '../lib/state.svelte';

  /**
   * The waveform + spectrogram player (ported from audioviewer), in a
   * same-origin iframe so its script, styles and keyboard shortcuts stay
   * self-contained. Players with the same `group` follow each other's zoom,
   * scroll, cursor and selection, and starting one pauses the others.
   */
  let {
    url,
    title,
    sampleRate,
    channels,
    duration,
    group,
    header,
  }: {
    url: string;
    title: string;
    sampleRate?: number;
    channels?: number;
    duration?: number;
    group: string;
    header: { label?: string; name?: string; tags?: string[] };
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
      scale: 'linear',
      fftSize: 1024,
      colormap: 'theme',
      waveHeight: 72,
      spectrogramHeight: 140,
      normalize: false,
      notes: false,
      annotations: [],
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
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });

  // a new clip (step slider) or theme re-renders the player
  $effect(() => {
    void [url, app.theme, app.themeVersion];
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
