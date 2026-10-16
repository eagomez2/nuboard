<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import Markdown from '../components/Markdown.svelte';
  import { api, type ReportInfo } from '../lib/api';
  import { DISPLAY_NAME } from '../lib/brand';
  import { ask, confirmAction } from '../lib/dialog.svelte';
  import {
    defaultFooter,
    downloadReportHtml,
    reportHasAudio,
    type AudioPlayer,
    type ExportTheme,
  } from '../lib/exporthtml';
  import { fmtAgo } from '../lib/format';
  import { prefs, router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  let list = $state<ReportInfo[]>([]);
  const project = $derived(router.get('project'));
  const current = $derived(
    list.find((r) => r.project === router.get('rproject') && r.name === router.get('report')) ??
      (router.get('report') ? null : (list[0] ?? null)),
  );
  const view = $derived(router.get('rview', 'split') as 'write' | 'split' | 'preview');

  async function load() {
    const res = await api.reports(project || null);
    list = res.reports;
  }
  $effect(() => {
    void project;
    load();
  });

  // The open report's text, saved a moment after typing stops
  let text = $state('');
  let savedText = $state('');
  let loadedFor = $state('');
  let textProject = $state(''); // the project `text` belongs to, so embeds never mix reports
  let saving = $state(false);
  $effect(() => {
    const r = current;
    const id = r ? `${r.project}/${r.name}` : '';
    if (id === loadedFor) return;
    loadedFor = id;
    text = savedText = '';
    if (r)
      api.report(r.project, r.name).then((res) => {
        if (loadedFor !== id) return;
        text = savedText = res.text;
        textProject = r.project;
      });
  });
  async function save() {
    const r = current;
    if (!r || text === savedText) return;
    saving = true;
    const body = text;
    await api.saveReport({ project: r.project, name: r.name, text: body });
    savedText = body;
    saving = false;
  }
  $effect(() => {
    if (text === savedText) return;
    const t = setTimeout(save, 700);
    return () => clearTimeout(t);
  });

  const projects = $derived(app.info?.projects.map((p) => p.name) ?? []);
  async function create() {
    const res = await ask(
      'New report',
      [
        { label: 'Name', value: 'findings', hint: 'Saved as <project>/reports/<name>.md' },
        { label: 'Project', value: project || projects[0] || '', suggestions: projects },
      ],
      { confirm: 'Create' },
    );
    if (!res || !res[0].trim() || !res[1].trim()) return;
    const [name, proj] = [res[0].trim(), res[1].trim()];
    const saved = await api.saveReport({
      project: proj,
      name,
      text: `# ${name}\n\nWrite in Markdown. Add images, audio, figures and text from the **Media** page with the bookmark button on any item.\n`,
    });
    if (saved.error) return;
    await load();
    router.set({ rproject: proj, report: saved.saved ?? name });
  }
  async function rename() {
    const r = current;
    if (!r) return;
    await save();
    const res = await ask('Rename report', [{ label: 'Name', value: r.name }], { confirm: 'Rename' });
    if (!res || !res[0].trim() || res[0].trim() === r.name) return;
    const out = await api.saveReport({ project: r.project, name: r.name, rename: res[0].trim() });
    if (out.error) return;
    await load();
    router.set({ rproject: r.project, report: out.saved ?? res[0].trim() });
  }
  async function remove() {
    const r = current;
    if (!r) return;
    const ok = await confirmAction(`Delete the report "${r.title}"?`, `${r.project}/reports/${r.name}.md is removed.`, {
      confirm: 'Delete',
      danger: true,
    });
    if (!ok) return;
    await api.saveReport({ project: r.project, name: r.name, delete: true });
    loadedFor = '';
    router.set({ report: null, rproject: null });
    await load();
  }
  let exporting = $state(false);
  async function exportHtml() {
    const r = current;
    if (!r) return;
    // the player choice is only asked when the report has audio
    const audio = await reportHasAudio(r.project, text).catch(() => false);
    const res = await ask(
      'Export as HTML',
      [
        {
          label: 'Theme',
          value: prefs.get('exportTheme', 'switch'),
          options: [
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
            { value: 'switch', label: 'Switchable' },
          ],
          hint: 'Switchable follows the reader’s system theme and has a button to change it.',
        },
        { label: 'Footer', value: defaultFooter(r.project, app.info?.version) },
        { label: `${DISPLAY_NAME} logo as the tab icon`, value: prefs.get('exportLogo', '1'), toggle: true },
        ...(audio
          ? [
              {
                label: 'Audio player',
                value: prefs.get('exportPlayer', 'wave'),
                options: [
                  { value: 'wave', label: 'Waveform' },
                  { value: 'simple', label: 'Simple' },
                ],
                hint: 'Waveform has the spectrogram, zoom and notes, as in the viewer; Simple is the browser’s own player, with a smaller file.',
              },
            ]
          : []),
      ],
      { confirm: 'Export', message: 'One self-contained file that opens offline.' },
    );
    if (!res) return;
    const theme = (['light', 'dark', 'switch'].includes(res[0]) ? res[0] : 'switch') as ExportTheme;
    prefs.set('exportTheme', theme);
    prefs.set('exportLogo', res[2]);
    const audioPlayer: AudioPlayer = res[3] === 'simple' ? 'simple' : 'wave';
    if (audio) prefs.set('exportPlayer', audioPlayer);
    exporting = true;
    try {
      await save();
      await downloadReportHtml(r.project, r.name, r.title, text, {
        theme,
        footer: res[1],
        logo: res[2] === '1',
        audioPlayer,
      });
    } finally {
      exporting = false;
    }
  }
  const byProject = $derived(
    [...new Set(list.map((r) => r.project))].map((p) => ({ p, reports: list.filter((r) => r.project === p) })),
  );
</script>

<div class="layout">
  <aside class="card side">
    <div class="head">
      <span class="label">Reports</span>
      <button class="btn sm" onclick={create}><Icon name="plus" size={15} /> New</button>
    </div>
    {#if !list.length}
      <p class="faint small">
        No reports yet. Press <b>New</b>, or add an item from the Media page with its bookmark button.
      </p>
    {/if}
    {#each byProject as g (g.p)}
      <div class="proj faint small mono" title={g.p}>{g.p}</div>
      {#each g.reports as r (r.project + r.name)}
        <button
          class="item"
          class:on={current?.project === r.project && current?.name === r.name}
          onclick={() => router.set({ rproject: r.project, report: r.name })}
          title="{r.project}/reports/{r.name}.md"
        >
          <Icon name="report" size={15} />
          <span class="t">{r.title}</span>
          <span class="faint small when">{fmtAgo(r.updated)}</span>
        </button>
      {/each}
    {/each}
    <p class="hint faint small">
      Reports are Markdown files in <code>&lt;project&gt;/reports/</code>. A line
      <code>![caption](media:run/key@step)</code> shows a logged item; the Media page writes it for you.
    </p>
  </aside>

  <section class="card main">
    {#if !current}
      <div class="empty faint">Pick a report, or press <b>New</b>.</div>
    {:else}
      <div class="toolbar">
        <h2 title={current.title}>{current.title}</h2>
        <span class="faint small mono path" title="{current.project}/reports/{current.name}.md"
          >{current.project}/reports/{current.name}.md</span
        >
        <span class="faint small state">{saving ? 'saving…' : text === savedText ? 'saved' : 'editing'}</span>
        <div class="seg" role="group" aria-label="View">
          <button aria-pressed={view === 'write'} onclick={() => router.set({ rview: 'write' })}>write</button>
          <button aria-pressed={view === 'split'} onclick={() => router.set({ rview: null })}>split</button>
          <button aria-pressed={view === 'preview'} onclick={() => router.set({ rview: 'preview' })}>preview</button>
        </div>
        <a
          class="btn sm"
          href={api.reportExportUrl(current.project, current.name)}
          download
          aria-label="Export as .zip"
          title="Markdown plus the embedded files, in a zip"><Icon name="download" size={15} /> .zip</a
        >
        <button
          class="btn sm"
          disabled={exporting}
          aria-label="Export as HTML"
          title="One HTML file with every item inlined"
          onclick={exportHtml}><Icon name="download" size={15} /> {exporting ? 'Exporting…' : '.html'}</button
        >
        <button class="btn sm" onclick={() => window.print()} title="Print or save as PDF">Print</button>
        <button class="btn sm btn-ghost" onclick={rename} aria-label="Rename" title="Rename"
          ><Icon name="edit" size={15} /></button
        >
        <button class="btn sm btn-ghost" onclick={remove} aria-label="Delete report" title="Delete"
          ><Icon name="trash" size={15} /></button
        >
      </div>
      <div class="panes" class:split={view === 'split'}>
        {#if view !== 'preview'}
          <textarea
            class="editor mono"
            aria-label="Report text"
            spellcheck="true"
            bind:value={text}
            onblur={save}
            onkeydown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                save();
              }
            }}></textarea>
        {/if}
        {#if view !== 'write'}
          <div class="preview printable">
            <Markdown {text} project={textProject} files />
          </div>
        {/if}
      </div>
    {/if}
  </section>
</div>

<style>
  .layout {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .side {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    position: sticky;
    top: 16px;
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .sm {
    height: 30px;
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12px;
  }
  .proj {
    margin: 8px 2px 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 8px;
    border: 0;
    background: none;
    border-radius: 8px;
    padding: 7px 8px;
    text-align: left;
    min-width: 0;
    color: var(--text);
  }
  .item:hover {
    background: var(--panel-2);
  }
  .item.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .item .t {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .when {
    flex: none;
  }
  .hint {
    margin: 12px 2px 0;
    line-height: 1.5;
  }
  .hint code {
    font-family: var(--mono);
    font-size: 11.5px;
  }
  .main {
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
    min-height: 70vh;
  }
  .empty {
    padding: 60px;
    text-align: center;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 40%;
    flex: none;
  }
  .path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    flex: 1 1 0;
  }
  .state {
    flex: none;
  }
  .panes {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
    flex: 1;
  }
  .panes.split {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  .editor {
    width: 100%;
    min-height: 68vh;
    resize: vertical;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.55;
    outline: none;
    box-sizing: border-box;
  }
  .editor:focus {
    border-color: var(--accent);
  }
  .preview {
    min-width: 0;
    padding: 0 6px;
  }
  @media print {
    .side,
    .toolbar,
    .editor {
      display: none !important;
    }
    .layout,
    .panes.split {
      display: block;
    }
    .main {
      border: 0;
      box-shadow: none;
    }
  }
</style>
