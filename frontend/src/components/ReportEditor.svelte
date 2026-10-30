<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { api } from '../lib/api';
  import { fmtBytes } from '../lib/format';
  import {
    activeFormats,
    insertBlock,
    insertRule,
    insertTable,
    toggle,
    type Edit,
    type Format,
    type Sel,
  } from '../lib/mdedit';
  import {
    AUDIO_ACCEPT,
    attachmentMarkdown,
    audioMarkdown,
    decodeText,
    imageMarkdown,
    inlineText,
    isAudio,
    isTable,
    LIMITS,
    noMediaIn,
    TEXT_ACCEPT,
  } from '../lib/reportfiles';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  // The report's Markdown text box with a formatting toolbar and an Insert menu. Every command
  // writes plain Markdown as one typing step, so the browser's undo and redo cover it.
  let {
    text = $bindable(),
    project,
    onsave,
  }: {
    text: string;
    project: string;
    onsave: () => void;
  } = $props();

  const readOnly = $derived(!!app.info?.read_only_reports);
  const noMedia = $derived(noMediaIn(app.runs, project));
  const limits = $derived({ ...LIMITS, ...app.info?.upload_limits });
  let area = $state<HTMLTextAreaElement>();
  let sel = $state<Sel>({ text: '', start: 0, end: 0 });
  const active = $derived(activeFormats(sel));

  function readSel() {
    if (area) sel = { text: area.value, start: area.selectionStart, end: area.selectionEnd };
  }
  onMount(() => {
    const onChange = () => document.activeElement === area && readSel();
    document.addEventListener('selectionchange', onChange);
    return () => document.removeEventListener('selectionchange', onChange);
  });

  /** Apply an edit as typing, so it joins the browser's undo history. */
  function apply(e: Edit) {
    if (!area) return;
    area.focus();
    area.setSelectionRange(e.from, e.to);
    const typed =
      e.insert === '' && e.from < e.to
        ? document.execCommand('delete')
        : e.insert !== '' && document.execCommand('insertText', false, e.insert);
    if (!typed) {
      area.setRangeText(e.insert, e.from, e.to, 'end');
      area.dispatchEvent(new Event('input', { bubbles: true }));
    }
    area.setSelectionRange(e.selStart, e.selEnd);
    readSel();
  }
  const current = (): Sel =>
    area ? { text: area.value, start: area.selectionStart, end: area.selectionEnd } : { text, start: 0, end: 0 };
  const run = (f: Format) => apply(toggle(current(), f));
  function history(cmd: 'undo' | 'redo') {
    area?.focus();
    document.execCommand(cmd);
    readSel();
  }

  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+';
  const BUTTONS: { f: Format; label: string; title: string; cls?: string; icon?: string }[][] = [
    [
      { f: 'bold', label: 'B', title: `Bold (${mod}B)`, cls: 'b' },
      { f: 'italic', label: 'I', title: `Italic (${mod}I)`, cls: 'i' },
      { f: 'underline', label: 'U', title: `Underline (${mod}U), written as <u>…</u>`, cls: 'u' },
      { f: 'strike', label: 'S', title: `Strikethrough (${mod}Shift+X)`, cls: 's' },
    ],
    [
      { f: 'h1', label: 'H1', title: 'Heading 1' },
      { f: 'h2', label: 'H2', title: 'Heading 2' },
      { f: 'h3', label: 'H3', title: 'Heading 3' },
      { f: 'paragraph', label: '¶', title: 'Paragraph: no heading, list or quote' },
    ],
    [
      { f: 'bullet', label: '•', title: 'Bulleted list', icon: 'list-bullet' },
      { f: 'numbered', label: '1.', title: 'Numbered list', icon: 'list-numbered' },
      { f: 'check', label: '☐', title: 'Checklist', icon: 'list-check' },
      { f: 'quote', label: '❝', title: 'Quote', icon: 'quote' },
    ],
    [
      { f: 'code', label: '`c`', title: 'Inline code', cls: 'mono' },
      { f: 'codeblock', label: '{ }', title: 'Code block', icon: 'codeblock' },
      { f: 'link', label: 'Link', title: `Link (${mod}K)`, icon: 'link' },
    ],
  ];

  function onKey(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
    const k = e.key.toLowerCase();
    const f: Format | null =
      k === 'b' && !e.shiftKey
        ? 'bold'
        : k === 'i' && !e.shiftKey
          ? 'italic'
          : k === 'u' && !e.shiftKey
            ? 'underline'
            : k === 'x' && e.shiftKey
              ? 'strike'
              : k === 'k' && !e.shiftKey
                ? 'link'
                : null;
    if (f) {
      e.preventDefault();
      run(f);
    } else if (k === 's') {
      e.preventDefault();
      onsave();
    }
  }

  // ---- the Insert menu and the table picker ----
  let menu = $state<'insert' | 'table' | null>(null);
  let tableHover = $state<[number, number]>([0, 0]);
  function pickTable(rows: number, cols: number) {
    menu = null;
    apply(insertTable(current(), rows, cols));
  }

  // ---- uploads: the image, audio and text-file panels, drag and drop, paste ----
  type Kind = 'image' | 'audio' | 'text';
  let panel = $state<Kind | null>(null);
  let dialogEl = $state<HTMLDialogElement>();
  let file = $state<File | null>(null);
  let preview = $state('');
  let alt = $state('');
  let caption = $state('');
  let mode = $state<'inline' | 'attach'>('inline');
  let asTable = $state(true);
  let problem = $state('');
  let busy = $state(false);
  let notice = $state(''); // an error from a direct drop or paste

  $effect(() => {
    if (panel && dialogEl && !dialogEl.open) dialogEl.showModal();
  });
  function openPanel(kind: Kind, f: File | null = null) {
    menu = null;
    panel = kind;
    problem = '';
    alt = caption = '';
    mode = 'inline';
    asTable = true;
    setFile(f);
  }
  function closePanel() {
    dialogEl?.close();
    panel = null;
    setFile(null);
  }
  function setFile(f: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    file = f;
    preview = f && panel === 'image' ? URL.createObjectURL(f) : '';
    problem = f ? checkSize(f, panel ?? 'image') : '';
    if (f && panel === 'image' && !alt) alt = f.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
    if (f && panel === 'audio' && !caption) caption = f.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
  }
  function checkSize(f: File, kind: Kind) {
    const limit = limits[kind];
    return f.size > limit ? `${f.name} is ${fmtBytes(f.size)}; ${kind} files can be at most ${fmtBytes(limit)}.` : '';
  }
  const isImage = (f: File) => f.type.startsWith('image/');

  async function upload(f: File, kind: Kind) {
    return api.uploadReportFile(project, f, f.name || (kind === 'image' ? 'pasted.png' : 'file.txt'), kind);
  }
  async function confirmPanel() {
    if (!file || problem) return;
    busy = true;
    try {
      if (panel === 'image') {
        const up = await upload(file, 'image');
        insertAndClose(imageMarkdown(up.path, alt, caption));
      } else if (panel === 'audio') {
        const up = await upload(file, 'audio');
        insertAndClose(audioMarkdown(up.path, caption));
      } else if (mode === 'attach') {
        const up = await upload(file, 'text');
        insertAndClose(attachmentMarkdown(up.name, up.path));
      } else {
        const decoded = decodeText(new Uint8Array(await file.arrayBuffer()), file.name, limits.text);
        if ('error' in decoded) problem = decoded.error;
        else insertAndClose(inlineText(decoded.text, file.name, asTable));
      }
    } catch (e) {
      problem = (e as Error).message;
    } finally {
      busy = false;
    }
  }
  function insertAndClose(md: string) {
    closePanel();
    apply(insertBlock(current(), md));
  }

  /** Images and audio dropped or pasted into the text box go in straight away; a text file opens its panel. */
  async function takeFiles(files: File[]) {
    notice = '';
    for (const f of files) {
      const kind = isImage(f) ? 'image' : isAudio(f) ? 'audio' : null;
      if (!kind) {
        openPanel('text', f);
        return;
      }
      const tooBig = checkSize(f, kind);
      if (tooBig) {
        notice = tooBig;
        continue;
      }
      try {
        const up = await upload(f, kind);
        const stem = f.name.replace(/\.[^.]+$/, '');
        const md =
          kind === 'audio'
            ? audioMarkdown(up.path, stem.replace(/[-_]+/g, ' '))
            : imageMarkdown(up.path, f.name && f.name !== 'image.png' ? stem : 'Pasted image', '');
        apply(insertBlock(current(), md));
      } catch (e) {
        notice = (e as Error).message;
      }
    }
  }
  let dragging = $state(false);
  const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes('Files');
</script>

<div class="editor-box">
  {#if readOnly}
    <p class="ro faint small">Reports are read-only on this server.</p>
  {:else}
    <div class="tools" role="toolbar" aria-label="Formatting">
      <button
        class="tool"
        title="Undo ({mod}Z)"
        aria-label="Undo"
        onmousedown={(e) => e.preventDefault()}
        onclick={() => history('undo')}><Icon name="undo" size={16} /></button
      >
      <button
        class="tool"
        title="Redo ({mod}Shift+Z)"
        aria-label="Redo"
        onmousedown={(e) => e.preventDefault()}
        onclick={() => history('redo')}><Icon name="redo" size={16} /></button
      >
      {#each BUTTONS as group, g (g)}
        <span class="sep"></span>
        {#each group as b (b.f)}
          <button
            class="tool {b.cls ?? ''}"
            title={b.title}
            aria-label={b.title.replace(/ \(.*$/, '').replace(/:.*$/, '')}
            aria-pressed={active.has(b.f)}
            onmousedown={(e) => e.preventDefault()}
            onclick={() => run(b.f)}
            >{#if b.icon}<Icon name={b.icon} size={16} />{:else}{b.label}{/if}</button
          >
        {/each}
      {/each}
      <span class="sep"></span>
      <button
        class="tool"
        title="Horizontal rule"
        aria-label="Horizontal rule"
        onmousedown={(e) => e.preventDefault()}
        onclick={() => apply(insertRule(current()))}><Icon name="rule" size={16} /></button
      >
      <div class="pop-anchor">
        <button
          class="tool"
          title="Table"
          aria-label="Table"
          aria-expanded={menu === 'table'}
          onmousedown={(e) => e.preventDefault()}
          onclick={() => (menu = menu === 'table' ? null : 'table')}><Icon name="table" size={16} /></button
        >
        {#if menu === 'table'}
          <div class="card pop grid-pop" role="dialog" aria-label="Table size">
            <div class="cells" style="grid-template-columns: repeat(8, 16px)">
              {#each [0, 1, 2, 3, 4, 5] as r (r)}
                {#each [0, 1, 2, 3, 4, 5, 6, 7] as c (c)}
                  <button
                    class="cell"
                    class:on={r < tableHover[0] && c < tableHover[1]}
                    aria-label="{r + 1} rows by {c + 1} columns"
                    onmouseenter={() => (tableHover = [r + 1, c + 1])}
                    onfocus={() => (tableHover = [r + 1, c + 1])}
                    onclick={() => pickTable(r + 1, c + 1)}
                  ></button>
                {/each}
              {/each}
            </div>
            <span class="faint small"
              >{tableHover[0] ? `${tableHover[0]} × ${tableHover[1]} (rows × columns)` : 'Pick a size'}</span
            >
          </div>
        {/if}
      </div>
      <span class="grow"></span>
      <div class="pop-anchor">
        <button
          class="btn sm insert"
          aria-expanded={menu === 'insert'}
          aria-haspopup="menu"
          onclick={() => (menu = menu === 'insert' ? null : 'insert')}><Icon name="plus" size={14} /> Insert</button
        >
        {#if menu === 'insert'}
          <div class="card pop menu" role="menu" aria-label="Insert">
            <button role="menuitem" onclick={() => openPanel('image')}>
              <Icon name="media" size={15} /><span><b>Image</b><small>Upload, drop or paste a picture</small></span>
            </button>
            <button role="menuitem" onclick={() => openPanel('audio')}>
              <Icon name="audio" size={15} /><span
                ><b>Audio</b><small>Upload or drop a recording; plays with the waveform player</small></span
              >
            </button>
            <button role="menuitem" onclick={() => openPanel('text')}>
              <Icon name="file" size={15} /><span
                ><b>Text file</b><small>Paste its content in, or attach it for download</small></span
              >
            </button>
            <button role="menuitem" onclick={() => ((menu = 'table'), (tableHover = [2, 3]))}>
              <Icon name="grid" size={15} /><span><b>Table</b><small>Pick rows and columns</small></span>
            </button>
            <button role="menuitem" onclick={() => router.go('charts', { project })}>
              <Icon name="charts" size={15} /><span
                ><b>Chart</b><small>Opens Charts: add one with its bookmark button</small></span
              >
            </button>
            <button role="menuitem" disabled={noMedia} onclick={() => router.go('media', { project })}>
              <Icon name="media" size={15} /><span
                ><b>Media item</b><small
                  >{noMedia
                    ? `No media logged in ${project} yet`
                    : 'Opens Media: add items with their bookmark button'}</small
                ></span
              >
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
  {#if notice}<p class="notice small" role="alert">{notice}</p>{/if}
  <textarea
    bind:this={area}
    class="editor mono"
    class:dragging
    aria-label="Report text"
    spellcheck="true"
    readonly={readOnly}
    bind:value={text}
    onblur={onsave}
    onkeydown={onKey}
    oninput={readSel}
    onclick={readSel}
    onkeyup={readSel}
    onfocus={readSel}
    ondragover={(e) => {
      if (readOnly || !hasFiles(e)) return;
      e.preventDefault();
      dragging = true;
    }}
    ondragleave={() => (dragging = false)}
    ondrop={(e) => {
      dragging = false;
      if (readOnly || !e.dataTransfer?.files.length) return;
      e.preventDefault();
      takeFiles([...e.dataTransfer.files]);
    }}
    onpaste={(e) => {
      const files = [...(e.clipboardData?.files ?? [])].filter(isImage);
      if (readOnly || !files.length) return;
      e.preventDefault();
      takeFiles(files);
    }}></textarea>
</div>

<svelte:window
  onclick={(e) => {
    if (menu && !(e.target as HTMLElement).closest('.pop-anchor')) menu = null;
  }}
  onkeydown={(e) => e.key === 'Escape' && menu && (menu = null)}
/>

{#if panel}
  <dialog
    bind:this={dialogEl}
    class="card upload"
    aria-labelledby="upload-title"
    oncancel={(e) => {
      e.preventDefault();
      if (!busy) closePanel();
    }}
    onpaste={(e) => {
      const f = [...(e.clipboardData?.files ?? [])][0];
      if (f) {
        e.preventDefault();
        setFile(f);
      }
    }}
  >
    <form
      onsubmit={(e) => {
        e.preventDefault();
        confirmPanel();
      }}
    >
      <h2 id="upload-title">
        {panel === 'image' ? 'Insert an image' : panel === 'audio' ? 'Insert audio' : 'Insert a text file'}
      </h2>
      <label
        class="drop"
        class:has={!!file}
        ondragover={(e) => e.preventDefault()}
        ondrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer?.files[0];
          if (f) setFile(f);
        }}
      >
        <input
          type="file"
          class="sr"
          aria-label={panel === 'image'
            ? 'Choose an image'
            : panel === 'audio'
              ? 'Choose an audio file'
              : 'Choose a text file'}
          accept={panel === 'image'
            ? 'image/png,image/jpeg,image/gif,image/webp,image/svg+xml'
            : panel === 'audio'
              ? AUDIO_ACCEPT
              : TEXT_ACCEPT}
          onchange={(e) => setFile(e.currentTarget.files?.[0] ?? null)}
        />
        {#if preview}
          <img src={preview} alt="" />
        {/if}
        {#if file}
          <span class="mono small">{file.name} · {fmtBytes(file.size)}</span>
        {:else}
          <span
            >Drop a file here, {panel === 'image' ? 'paste a screenshot, ' : ''}or <u>choose one</u>.<br /><span
              class="faint small"
              >{panel === 'image'
                ? `PNG, JPEG, GIF or WebP, up to ${fmtBytes(limits.image)}.`
                : panel === 'audio'
                  ? `WAV, FLAC, MP3, Ogg, M4A or WebM, up to ${fmtBytes(limits.audio)}.`
                  : `UTF-8 text such as .txt, .md, .log, .csv, .json, .yaml or code, up to ${fmtBytes(limits.text)}.`}</span
            ></span
          >
        {/if}
      </label>
      {#if panel === 'image'}
        <div class="field">
          <label class="label" for="up-alt">Alt text</label>
          <input id="up-alt" class="input" bind:value={alt} placeholder="What the image shows, for screen readers" />
        </div>
        <div class="field">
          <label class="label" for="up-caption">Caption</label>
          <input
            id="up-caption"
            class="input"
            bind:value={caption}
            placeholder="Shown under the image; say where it comes from if useful"
          />
        </div>
      {:else if panel === 'audio'}
        <div class="field">
          <label class="label" for="up-caption">Caption</label>
          <input id="up-caption" class="input" bind:value={caption} placeholder="Shown under the player" />
        </div>
      {:else}
        <div class="field">
          <span class="label">How it goes in</span>
          <div class="seg" role="group" aria-label="How it goes in">
            <button type="button" aria-pressed={mode === 'inline'} onclick={() => (mode = 'inline')}>Inline</button>
            <button type="button" aria-pressed={mode === 'attach'} onclick={() => (mode = 'attach')}>Attached</button>
          </div>
          <span class="hint"
            >{mode === 'inline'
              ? 'Its content is pasted into the report: Markdown as it is, anything else as a code block.'
              : 'Stored in reports/files/ and shown as a collapsible block with a download link.'}</span
          >
        </div>
        {#if mode === 'inline' && file && isTable(file.name)}
          <label class="row small"><input type="checkbox" bind:checked={asTable} /> As a table</label>
        {/if}
      {/if}
      {#if problem}<p class="problem small" role="alert">{problem}</p>{/if}
      <div class="actions">
        <button type="button" class="btn" disabled={busy} onclick={closePanel}>Cancel</button>
        <button type="submit" class="btn btn-primary" disabled={!file || !!problem || busy}
          >{busy ? 'Uploading…' : 'Insert'}</button
        >
      </div>
    </form>
  </dialog>
{/if}

<style>
  .editor-box {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
  }
  .tool {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 28px;
    height: 28px;
    padding: 0 6px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: none;
    color: var(--muted);
    font-size: 13px;
  }
  .tool:hover {
    background: var(--panel);
    color: var(--text);
  }
  .tool[aria-pressed='true'] {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tool.b {
    font-weight: 800;
  }
  .tool.i {
    font-style: italic;
    font-family: Georgia, serif;
  }
  .tool.u {
    text-decoration: underline;
  }
  .tool.s {
    text-decoration: line-through;
  }
  .tool.mono {
    font-family: var(--mono);
    font-size: 12px;
  }
  .sep {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 4px;
  }
  .grow {
    flex: 1;
  }
  .sm {
    height: 28px;
  }
  .pop-anchor {
    position: relative;
  }
  .pop {
    position: absolute;
    top: calc(100% + 6px);
    z-index: 20;
    padding: 6px;
    box-shadow: 0 8px 24px rgba(16, 24, 40, 0.18);
  }
  .menu {
    right: 0;
    width: 300px;
    display: flex;
    flex-direction: column;
  }
  .menu button {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    text-align: left;
    border: 0;
    background: none;
    border-radius: 8px;
    padding: 7px 8px;
    color: var(--text);
  }
  .menu button:not(:disabled):hover,
  .menu button:focus-visible {
    background: var(--panel-2);
  }
  .menu button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .menu span {
    display: flex;
    flex-direction: column;
  }
  .menu small {
    color: var(--faint);
    font-size: 12px;
  }
  .grid-pop {
    left: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: max-content;
  }
  .cells {
    display: grid;
    gap: 3px;
  }
  .cell {
    width: 16px;
    height: 16px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--panel);
  }
  .cell.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .editor {
    width: 100%;
    min-height: 64vh;
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
  .editor.dragging {
    border-color: var(--accent);
    border-style: dashed;
    background: var(--accent-soft);
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12.5px;
  }
  .ro {
    margin: 0;
  }
  .notice,
  .problem {
    margin: 0;
    color: var(--err);
    background: var(--err-bg);
    border-radius: 8px;
    padding: 6px 10px;
  }
  .upload {
    width: min(480px, calc(100vw - 32px));
    margin: auto;
    padding: 0;
    color: var(--text);
    box-shadow: 0 24px 48px -12px rgba(16, 24, 40, 0.35);
  }
  .upload::backdrop {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
    backdrop-filter: blur(2px);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px;
  }
  h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 650;
  }
  .drop {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 120px;
    padding: 14px;
    border: 1.5px dashed var(--border);
    border-radius: 10px;
    text-align: center;
    cursor: pointer;
    color: var(--muted);
  }
  .drop:hover,
  .drop:focus-within {
    border-color: var(--accent);
  }
  .drop img {
    max-width: 100%;
    max-height: 200px;
    border-radius: 6px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .seg {
    align-self: flex-start;
  }
  .hint {
    font-size: 12px;
    color: var(--faint);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
</style>
