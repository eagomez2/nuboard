<script lang="ts">
  // The small icon of a hypothesis verdict (check, cross, circle, star, question mark, pause).
  import type { VerdictIcon } from '../lib/hypotheses';

  let { icon, size = 12 }: { icon: VerdictIcon | string; size?: number } = $props();
  const PATHS: Record<string, string> = {
    check: 'M2.5 6.5l2.5 2.5 4.5-6',
    x: 'M3 3l6 6M9 3l-6 6',
    circle: 'M6 2a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
    star: 'M6 1.5l1.4 2.9 3.1.4-2.3 2.2.6 3.1L6 8.6 3.2 10.1l.6-3.1L1.5 4.8l3.1-.4z',
    question: 'M4.2 4.4a1.9 1.9 0 1 1 2.7 1.7c-.6.3-.9.7-.9 1.3M6 9.6h.01',
    pause: 'M4.3 3v6M7.7 3v6',
  };
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 12 12"
  fill="none"
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"><path d={PATHS[icon] ?? PATHS.circle} /></svg
>
