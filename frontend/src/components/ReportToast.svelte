<script lang="ts">
  import { lastAdded } from '../lib/reports.svelte';
  import { router } from '../lib/router.svelte';
</script>

{#if lastAdded.value}
  {@const a = lastAdded.value}
  <div class="card toast" role="status">
    Added to <b>{a.name}</b>.
    <button
      class="btn btn-ghost sm"
      onclick={() => {
        const { project, name } = a;
        lastAdded.value = null;
        router.go('reports', { rproject: project, report: name });
      }}>Open report</button
    >
  </div>
{/if}

<style>
  .toast {
    position: fixed;
    right: 20px;
    bottom: 20px;
    z-index: 60;
    padding: 8px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    border-color: color-mix(in srgb, var(--accent) 45%, transparent);
    box-shadow: 0 8px 24px rgb(0 0 0 / 0.15);
  }
  .sm {
    height: 28px;
  }
</style>
