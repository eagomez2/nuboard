<script lang="ts">
  import { onMount } from 'svelte';
  import { app } from '../lib/state.svelte';

  /** A logged Plotly / Vega-Lite / Bokeh figure, rendered in a sandboxed iframe. */
  let { url, mime, title }: { url: string; mime: string; title: string } = $props();

  let frame = $state<HTMLIFrameElement | null>(null);
  let height = $state(440);
  let data: string | null = null;
  let ready = false;

  function send() {
    if (ready && data !== null && frame?.contentWindow) {
      frame.contentWindow.postMessage({ type: 'render', mime, data, theme: app.theme }, '*');
    }
  }

  onMount(() => {
    const onMessage = (e: MessageEvent) => {
      if (!frame || e.source !== frame.contentWindow) return;
      if (e.data?.type === 'ready') {
        ready = true;
        send();
      } else if (e.data?.type === 'height') {
        height = Math.min(Math.max(Number(e.data.height) || 0, 160), 1400);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });

  $effect(() => {
    const target = url;
    data = null;
    fetch(target)
      .then((r) => r.text())
      .then((text) => {
        if (target === url) {
          data = text;
          send();
        }
      });
  });

  // re-render with the new colors when the theme changes
  $effect(() => {
    void app.theme;
    send();
  });
</script>

<!-- No allow-same-origin: the figure cannot reach the viewer's page or its API. -->
<iframe bind:this={frame} {title} sandbox="allow-scripts allow-downloads" src="./figure.html" style="height:{height}px"
></iframe>
<a class="dl" href={url} download>Download spec ({mime.replace('application/', '')})</a>

<style>
  iframe {
    width: 100%;
    border: 0;
    display: block;
    background: transparent;
  }
  .dl {
    display: inline-block;
    margin-top: 4px;
    font-size: 12px;
    color: var(--faint);
  }
</style>
