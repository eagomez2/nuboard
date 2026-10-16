<script lang="ts">
  import { COPYRIGHT, DISPLAY_NAME, DOCS_URL, LICENSE } from '../lib/brand';
  import { app } from '../lib/state.svelte';

  // The About window: name, version, copyright, license and documentation.
  let { open = $bindable(false) }: { open?: boolean } = $props();
  let el = $state<HTMLDialogElement>();

  $effect(() => {
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  });
</script>

<dialog
  bind:this={el}
  class="card about"
  aria-labelledby="nb-about-title"
  onclose={() => (open = false)}
  onclick={(e) => e.target === el && (open = false)}
>
  <img src="./logo.svg" alt="" width="56" height="56" />
  <h2 id="nb-about-title">{DISPLAY_NAME}</h2>
  <p class="mono version">version {app.info?.version ?? '…'}</p>
  <p class="tagline">Experiment tracking that lives in a folder.</p>
  <p class="fine">{COPYRIGHT}</p>
  <p class="fine">Released under the {LICENSE}.</p>
  <a class="fine" href={DOCS_URL} target="_blank" rel="noopener noreferrer">Documentation</a>
  <button class="btn sm" onclick={() => (open = false)}>Close</button>
</dialog>

<style>
  .about {
    width: min(340px, calc(100vw - 32px));
    margin: auto;
    padding: 24px 22px 18px;
    color: var(--text);
    text-align: center;
    box-shadow:
      0 1px 2px rgba(16, 24, 40, 0.08),
      0 24px 48px -12px rgba(16, 24, 40, 0.35);
  }
  .about[open] {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .about::backdrop {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
    backdrop-filter: blur(2px);
  }
  img {
    border-radius: 12px;
    margin-bottom: 6px;
  }
  h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  p {
    margin: 0;
  }
  .version {
    color: var(--muted);
    font-size: 12.5px;
  }
  .tagline {
    margin: 8px 0;
    color: var(--muted);
    font-size: 13.5px;
  }
  .fine {
    font-size: 12.5px;
    color: var(--faint);
  }
  a.fine {
    color: var(--accent);
    margin-top: 6px;
  }
  .btn {
    margin-top: 14px;
  }
</style>
