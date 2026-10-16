<script lang="ts">
  import { onMount } from 'svelte';
  import Dialog from './components/Dialog.svelte';
  import ReportToast from './components/ReportToast.svelte';
  import Icon from './components/Icon.svelte';
  import QueryBar from './components/QueryBar.svelte';
  import RunsPage from './pages/RunsPage.svelte';
  import ChartsPage from './pages/ChartsPage.svelte';
  import MediaPage from './pages/MediaPage.svelte';
  import TimelinePage from './pages/TimelinePage.svelte';
  import SweepsPage from './pages/SweepsPage.svelte';
  import ArtifactsPage from './pages/ArtifactsPage.svelte';
  import ReportsPage from './pages/ReportsPage.svelte';
  import { DISPLAY_NAME as NAME } from './lib/brand';
  import { onLive } from './lib/live';
  import { router, type Page } from './lib/router.svelte';
  import { app } from './lib/state.svelte';

  const nav: { page: Page; icon: string; label: string }[] = [
    { page: 'runs', icon: 'runs', label: 'Runs' },
    { page: 'charts', icon: 'charts', label: 'Charts' },
    { page: 'media', icon: 'media', label: 'Media' },
    { page: 'sweeps', icon: 'sweep', label: 'Sweeps' },
    { page: 'timeline', icon: 'timeline', label: 'Timeline' },
    { page: 'artifacts', icon: 'artifact', label: 'Artifacts' },
    { page: 'reports', icon: 'report', label: 'Reports' },
  ];
  const titles: Record<Page, string> = {
    runs: 'All runs',
    charts: 'Charts',
    media: 'Media',
    sweeps: 'Sweeps',
    timeline: 'Timeline',
    artifacts: 'Artifacts',
    reports: 'Reports',
  };

  onMount(() => {
    app.loadInfo();
    app.loadCollections();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = onLive('runs', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        app.loadRuns();
        app.loadInfo();
      }, 300);
    });
    return off;
  });

  // Reload the run list whenever the query or project in the URL changes.
  $effect(() => {
    router.get('q');
    router.get('project');
    app.loadRuns();
  });

  const project = $derived(router.get('project'));
  const title = $derived(
    project ? (router.page === 'runs' ? project : `${project} · ${titles[router.page]}`) : titles[router.page],
  );
  const subtitle = $derived.by(() => {
    const r = app.runs;
    if (!r) return NAME;
    const running = r.runs.filter((x) => x.status === 'running').length;
    const projects = app.info?.projects.length ?? 0;
    const parts = [NAME];
    if (!project) parts.push(`${projects} project${projects === 1 ? '' : 's'}`);
    parts.push(`${r.runs.length} of ${r.total} runs`);
    if (r.query.group_by) parts.push(`grouped by ${r.query.group_by}`);
    if (running) parts.push(`${running} running · live`);
    return parts.join(' · ');
  });
</script>

<div class="shell">
  <nav class="rail" aria-label="Pages">
    <a class="logo" href="#/runs" title={NAME}><img src="./logo.svg" alt={NAME} width="34" height="34" /></a>
    {#each nav as item (item.page)}
      <button
        aria-current={router.page === item.page ? 'page' : undefined}
        title={item.label}
        aria-label={item.label}
        onclick={() => router.go(item.page)}
      >
        <Icon name={item.icon} size={20} />
      </button>
    {/each}
  </nav>

  <main class="page">
    <header>
      <button class="btn folder" title={app.info?.root} onclick={() => router.go('runs', { project: null })}>
        <Icon name="folder" size={17} />
        <span class="mono">{app.info?.root_display ?? '…'}</span>
      </button>
      <div class="title">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <QueryBar />
      <button
        class="btn theme"
        aria-label="Toggle light/dark theme"
        title="Toggle theme"
        onclick={() => app.toggleTheme()}
      >
        <Icon name={app.theme === 'dark' ? 'sun' : 'moon'} size={18} />
      </button>
    </header>

    {#if app.error && !app.runs}
      <div class="card errbox">Could not reach the {NAME} server: {app.error}</div>
    {/if}

    {#if router.page === 'runs'}
      <RunsPage />
    {:else if router.page === 'charts'}
      <ChartsPage />
    {:else if router.page === 'sweeps'}
      <SweepsPage />
    {:else if router.page === 'timeline'}
      <TimelinePage />
    {:else if router.page === 'artifacts'}
      <ArtifactsPage />
    {:else if router.page === 'reports'}
      <ReportsPage />
    {:else}
      <MediaPage />
    {/if}
  </main>
</div>

<Dialog />
<ReportToast />

<style>
  .shell {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr);
    min-height: 100vh;
    background: linear-gradient(to right, var(--rail) 64px, transparent 64px);
  }
  .rail {
    background: var(--rail);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding-block: 14px;
    position: sticky;
    top: 0;
    height: 100vh;
  }
  .logo {
    margin-bottom: 14px;
    display: block;
  }
  .logo img {
    display: block;
    border-radius: 9px;
  }
  .rail button {
    width: 42px;
    height: 42px;
    border-radius: 11px;
    border: 0;
    background: none;
    color: var(--rail-fg);
    display: grid;
    place-items: center;
  }
  .rail button:hover {
    background: rgba(255, 255, 255, 0.07);
    color: #fff;
  }
  .rail button[aria-current='page'] {
    background: rgba(255, 255, 255, 0.13);
    color: #fff;
  }
  .page {
    padding: 18px 24px 40px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
  }
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .folder {
    height: 40px;
    border-radius: 12px;
    box-shadow: var(--lift);
    max-width: 260px;
  }
  .folder span {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .title h1 {
    font-size: 22px;
    font-weight: 650;
    letter-spacing: -0.02em;
    margin: 0;
  }
  .title p {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
  }
  .theme {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    justify-content: center;
    padding: 0;
    box-shadow: var(--lift);
  }
  .errbox {
    padding: 14px 16px;
    color: var(--err);
  }
  @media (max-width: 720px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
      background: none;
    }
    .rail {
      flex-direction: row;
      height: auto;
      position: static;
      padding: 8px 16px;
    }
    .logo {
      margin: 0 10px 0 0;
    }
    .page {
      padding: 14px 16px 32px;
    }
  }
</style>
