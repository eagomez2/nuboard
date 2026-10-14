<script lang="ts">
  let { status }: { status: string } = $props();
</script>

<span class="status {status}">
  {#if status === 'running'}<span class="ring"></span>
  {:else if status === 'crashed' || status === 'killed'}<span class="x">✕</span>
  {:else if status === 'lost'}<span class="x">?</span>
  {:else}<span class="dot"></span>{/if}
  {status}
</span>

<style>
  .status {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 13px;
    color: var(--muted);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--faint);
  }
  .ring {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 2px solid var(--accent);
    animation: pulse 1.6s ease-in-out infinite;
  }
  .running {
    color: var(--accent);
  }
  .crashed,
  .killed {
    color: var(--err);
  }
  .lost {
    color: var(--warn);
  }
  .x {
    font-size: 11px;
    font-weight: 700;
    width: 9px;
    text-align: center;
  }
  @keyframes pulse {
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .ring {
      animation: none;
    }
  }
</style>
