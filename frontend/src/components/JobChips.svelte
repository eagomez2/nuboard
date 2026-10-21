<script lang="ts">
  import type { Job } from '../lib/api';

  // Helper jobs logging into a run (such as an evaluator started with `job="eval"`), as chips.
  let { jobs = [] }: { jobs?: Job[] } = $props();

  const tip = (j: Job) => `Job ${j.job}: ${j.status}${j.error ? `\n${j.error.trim().split('\n').at(-1)}` : ''}`;
</script>

{#each jobs as j (j.job)}
  <span class="job {j.status}" title={tip(j)}
    >{j.job}{#if j.status === 'running'}<span class="ring"></span>{:else if j.status !== 'finished'}<span class="x"
        >✕</span
      >{/if}</span
  >
{/each}

<style>
  .job {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    line-height: 16px;
    padding: 0 7px;
    border-radius: 999px;
    border: 1px solid var(--border);
    color: var(--muted);
    white-space: nowrap;
  }
  .job.running {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  }
  .job.crashed,
  .job.killed,
  .job.lost {
    color: var(--err);
    border-color: color-mix(in srgb, var(--err) 40%, transparent);
  }
  .ring {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1.5px solid var(--accent);
    animation: pulse 1.6s ease-in-out infinite;
  }
  .x {
    font-weight: 700;
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
