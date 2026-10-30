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
    sidebar: 'M3 4h18v16H3zM9 4v16M5.5 8h1M5.5 11h1',
    alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
    timeline: 'M3 6h8M7 12h10M5 18h14M3 3v18',
    sweep: 'M4 4v16M10 4v16M16 4v16M22 4v16M4 15l6-7 6 9 6-12',
    artifact: 'M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10',
    columns: 'M3 4h18v16H3zM9 4v16M15 4v16',
    plus: 'M12 5v14M5 12h14',
    info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5h.01',
    report: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7M9 8h3',
    bookmark: 'M6 3h12v18l-6-4-6 4z',
    edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
    download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
    trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13',
    tag: 'M3 12V3h9l9 9-9 9zM7.5 7.5h.01',
    grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
    shrink: 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5',
    pin: 'M9 4h6M10 4v6l-3 4h10l-3-4V4M12 14v7',
    disk: 'M3 13h18v7H3zM3 13l3-9h12l3 9M7 16.5h.01M11 16.5h6',
    audio: 'M3 12h1M7 9v6M11 5v14M15 8v8M19 11v2M22 12h-.01',
    link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
    'list-bullet': 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
    'list-numbered': 'M10 6h10M10 12h10M10 18h10M4 4.5h1.5V9M4 9h3M4 14.5a1.5 1.5 0 0 1 3 0c0 1.5-3 2-3 4h3',
    'list-check': 'M3.5 4.5h5v5h-5zM3.5 14.5h5v5h-5zM12 7h8M12 17h8M4.8 16.8l1.4 1.4 2.3-2.7',
    quote: 'M10 7c-3 1-5 3-5 6v4h5v-5H6.5M19 7c-3 1-5 3-5 6v4h5v-5h-3.5',
    codeblock: 'M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14',
    rule: 'M3 12h18M7 6h10M7 18h10',
    table: 'M3 5h18v14H3zM3 10h18M3 15h18M9 5v14M15 5v14',
    undo: 'M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',
    redo: 'M15 14l5-5-5-5M20 9H9.5a5.5 5.5 0 0 0 0 11H13',
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
