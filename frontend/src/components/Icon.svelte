<script lang="ts">
  const PATHS: Record<string, string> = {
    runs: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
    charts: 'M3 3v18h18M7 15l4-5 4 3 5-7',
    media: 'M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M15.5 9.5h.01',
    folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
    search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
    sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
    moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
    star: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z',
    x: 'M6 6l12 12M18 6L6 18',
    check: 'M5 12l5 5L20 7',
    file: 'M14 3H6v18h12V7zM14 3v4h4',
    collection: 'M4 6h16M4 12h10M4 18h7M17 15v6M14 18h6',
    archive: 'M3 4h18v4H3zM5 8v12h14V8M10 12h4',
    compare: 'M9 3v18M15 3v18M3 8h6M15 16h6',
    reset: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
    chevron: 'M6 9l6 6 6-6',
    alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
    timeline: 'M3 6h8M7 12h10M5 18h14M3 3v18',
    sweep: 'M4 4v16M10 4v16M16 4v16M22 4v16M4 15l6-7 6 9 6-12',
    artifact: 'M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10',
    columns: 'M3 4h18v16H3zM9 4v16M15 4v16',
    plus: 'M12 5v14M5 12h14',
  };
  let { name, size = 18, filled = false }: { name: string; size?: number; filled?: boolean } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill={filled ? 'currentColor' : 'none'}
  stroke="currentColor"
  stroke-width="1.7"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"><path d={PATHS[name] ?? ''} /></svg
>
