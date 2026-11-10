<script lang="ts">
  import DirectionButton from './DirectionButton.svelte';
  import ScalarPicker from './ScalarPicker.svelte';
  import type { Stat } from '../lib/stat';

  /**
   * The one control for "which scalar, summarized how": a scalar picker, the ↑ / ↓ of which way
   * is better (when `projects` is given), and Min / Max / Last. Every screen that shows one number
   * per run uses it, so the same words mean the same thing everywhere. Each screen keeps its own
   * URL keys and remembered choice; this only draws the control.
   */
  let {
    metrics,
    metric,
    stat,
    onmetric,
    onstat,
    projects,
    allowLast = true,
    none,
    disabled = false,
    size = 'md',
  }: {
    metrics: string[];
    metric: string;
    stat: Stat;
    onmetric: (m: string) => void;
    onstat: (s: Stat) => void;
    /** Projects whose direction the arrow shows; no arrow without them. */
    projects?: string[];
    allowLast?: boolean;
    /** Label of an empty first choice (no scalar), such as "None". */
    none?: string;
    disabled?: boolean;
    size?: 'sm' | 'md';
  } = $props();

  const HINTS: Record<Stat, string> = {
    min: "Each run's lowest value at any step",
    max: "Each run's highest value at any step",
    last: "Each run's value at its last logged step",
  };
  const choices = $derived<Stat[]>(allowLast ? ['min', 'max', 'last'] : ['min', 'max']);
</script>

<span class="scalarstat" class:small={size === 'sm'}>
  <ScalarPicker {metrics} value={metric} onpick={onmetric} {none} {disabled} {size} />
  {#if projects && metric}<DirectionButton {projects} name={metric} />{/if}
  {#if metric}
    <span class="seg" role="group" aria-label="Statistic">
      {#each choices as c (c)}
        <button aria-pressed={stat === c} title={HINTS[c]} {disabled} onclick={() => onstat(c)}
          >{c === 'min' ? 'Min' : c === 'max' ? 'Max' : 'Last'}</button
        >
      {/each}
    </span>
  {/if}
</span>

<style>
  .scalarstat {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .small .seg button {
    padding: 2px 8px;
    font-size: 12.5px;
  }
</style>
