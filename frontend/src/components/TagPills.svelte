<script lang="ts">
  import { tagStyle } from '../lib/colors';

  // Tags as colored pills, at most `max` of them with a "+N" for the rest.
  let { tags, max = 99 }: { tags: string[]; max?: number } = $props();
</script>

<span class="pills" title={tags.join(', ')}>
  {#each tags.slice(0, max) as t (t)}<span class="tagpill" style={tagStyle(t)}>{t}</span>{/each}
  {#if tags.length > max}<span class="more">+{tags.length - max}</span>{/if}
</span>

<style>
  .pills {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
    overflow: hidden;
  }
  .more {
    font-size: 11px;
    color: var(--faint);
  }
</style>
