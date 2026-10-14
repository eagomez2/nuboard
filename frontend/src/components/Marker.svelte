<script lang="ts">
  import { SHAPES } from '../lib/colors';
  let { index, color, size = 11 }: { index: number; color: string; size?: number } = $props();
  const shape = $derived(SHAPES[index % SHAPES.length]);
</script>

<svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" style="flex:none">
  {#if shape === 'circle'}
    <circle cx="6" cy="6" r="4" fill="none" stroke={color} stroke-width="2" />
  {:else if shape === 'square'}
    <rect x="2" y="2" width="8" height="8" fill="none" stroke={color} stroke-width="2" />
  {:else if shape === 'triangle'}
    <path d="M6 1.8 10.5 10H1.5z" fill="none" stroke={color} stroke-width="1.8" stroke-linejoin="round" />
  {:else}
    <path d="M6 1.5 10.5 6 6 10.5 1.5 6z" fill="none" stroke={color} stroke-width="1.8" stroke-linejoin="round" />
  {/if}
</svg>
