<script lang="ts">
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import Terminal from './Terminal.svelte';
  import { isTerminalText, stripAnsi } from '../lib/ansi';
  import { api, type RunDetail, type RunFile, type RunTree, type TensorEntry, type TensorInfo } from '../lib/api';
  import { sideBySide } from '../lib/diff';
  import { fmtBytes, fmtDate, fmtNum } from '../lib/format';
  import { isPattern, patternRegex, pinMatches } from '../lib/pattern';
  import { pins } from '../lib/pins.svelte';
  import { router } from '../lib/router.svelte';

  // Every file of the shown runs' folders: a tree to browse, with a preview of the
  // picked file below. Text files are diffed between two runs, checkpoints are listed
  // tensor by tensor (read from their headers), anything else can be downloaded.
  // With `pin`, only the file(s) that pin names are shown, without the tree.
  let {
    details,
    trees,
    pairIdx,
    onlyChanges,
    colors,
    pin = null,
  }: {
    details: RunDetail[];
    trees: (RunTree | null)[];
    pairIdx: number[];
    onlyChanges: boolean;
    colors: string[];
    pin?: string | null;
  } = $props();

  const multi = $derived(details.length >= 2);
  const projects = $derived([...new Set(details.map((d) => d.run.project))]);
  const pinned = $derived(pins.of(projects));
  let showInternal = $state(false);
  let find = $state('');
  // Folders opened or closed by hand; `files/` and the picked file's folders start open
  let toggled = $state(new Set<string>());

  // path -> the file in each run (null where a run lacks it)
  const byPath = $derived.by(() => {
    const map = new Map<string, (RunFile | null)[]>();
    trees.forEach((t, i) => {
      for (const f of t?.files ?? []) {
        if (!map.has(f.path))
          map.set(
            f.path,
            details.map(() => null),
          );
        map.get(f.path)![i] = f;
      }
    });
    return map;
  });
  const shownPaths = $derived(
    [...byPath.keys()]
      .filter((p) => showInternal || !byPath.get(p)!.some((f) => f?.internal))
      .filter((p) => !find || (findRe ? findRe.test(p) : p.toLowerCase().includes(find.toLowerCase())))
      .sort((a, b) => {
        // folders before files at each level, then by name
        const pa = a.split('/');
        const pb = b.split('/');
        for (let i = 0; i < Math.min(pa.length, pb.length); i++) {
          if (pa[i] === pb[i]) continue;
          const da = i < pa.length - 1;
          const db = i < pb.length - 1;
          if (da !== db) return da ? -1 : 1;
          return pa[i].localeCompare(pb[i]);
        }
        return pa.length - pb.length;
      }),
  );
  // A filter with `*` or `?` is a pattern over whole paths, and can be pinned
  const findRe = $derived(isPattern(find.trim()) ? patternRegex(find.trim().replace(/^\/+/, '')) : null);
  const internalCount = $derived([...byPath.values()].filter((fs) => fs.some((f) => f?.internal)).length);

  type Row =
    | { kind: 'dir'; path: string; name: string; depth: number; count: number; size: number }
    | {
        kind: 'file';
        path: string;
        name: string;
        depth: number;
        files: (RunFile | null)[];
      };
  // The tree as rows: a folder row, then its contents unless it is closed
  const rows = $derived.by(() => {
    const out: Row[] = [];
    const dirs = new Map<string, Row & { kind: 'dir' }>();
    for (const p of shownPaths) {
      const parts = p.split('/');
      const files = byPath.get(p)!;
      const size = Math.max(...files.map((f) => f?.size ?? 0));
      let hidden = false;
      for (let i = 0; i < parts.length - 1; i++) {
        const dir = parts.slice(0, i + 1).join('/');
        let row = dirs.get(dir);
        if (!row) {
          row = { kind: 'dir', path: dir, name: parts[i], depth: i, count: 0, size: 0 };
          dirs.set(dir, row);
          if (!hidden) out.push(row);
        }
        row.count++;
        row.size += size;
        if (!isOpen(dir) && !find) hidden = true;
      }
      if (!hidden) out.push({ kind: 'file', path: p, name: parts[parts.length - 1], depth: parts.length - 1, files });
    }
    return out;
  });
  function isOpen(dir: string): boolean {
    return (dir === 'files' || dir.startsWith('files/')) !== toggled.has(dir);
  }
  // A file picked from a link opens the folders it is in
  $effect(() => {
    const parts = picked.split('/').slice(0, -1);
    untrack(() => {
      const shut = parts.map((_, i) => parts.slice(0, i + 1).join('/')).filter((d) => !isOpen(d));
      if (!shut.length) return;
      const next = new Set(toggled);
      for (const d of shut) if (!next.delete(d)) next.add(d);
      toggled = next;
    });
  });
  // The tree is as tall as its rows, up to about 12, until resized by hand
  let treeH = $state<number | null>(null);
  const autoH = $derived(Math.min(290, Math.max(90, rows.length * 23 + 12)));
  function toggleDir(path: string) {
    const next = new Set(toggled);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    toggled = next;
  }
  const middle = (name: string) => (name.length > 28 ? [name.slice(0, -14), name.slice(-14)] : [name, '']);

  // ---- the picked file ----
  const picked = $derived(pin ? '' : router.get('file'));
  // A pin names one file per run: its path, or a pattern's newest match unless another is chosen
  const matches = $derived(pin ? details.map((_, i) => pinMatches(pin, trees[i]?.files ?? [])) : []);
  let choice = $state<Record<number, string>>({});
  $effect(() => {
    void pin;
    choice = {};
  });
  const pickedFiles: (RunFile | null)[] = $derived(
    pin ? matches.map((m, i) => m.find((f) => f.path === choice[i]) ?? m[0] ?? null) : (byPath.get(picked) ?? []),
  );
  const pickedKind = $derived(pickedFiles.find(Boolean)?.kind ?? null);
  const pickedPath = $derived(pickedFiles.find(Boolean)?.path ?? '');
  // The runs whose copy is shown: the diffed pair, or the one run
  const shownIdx = $derived(multi ? (pairIdx.every((i) => i < details.length) ? pairIdx : [0, 1]) : [0]);
  let texts = $state<({ text: string; truncated: boolean } | null)[]>([]);
  let infos = $state<(TensorInfo | null)[]>([]);
  let loading = $state(false);
  let request = 0;

  $effect(() => {
    const kind = pickedKind;
    const ds = shownIdx.map((i) => details[i]);
    const paths = shownIdx.map((i) => pickedFiles[i]?.path ?? null);
    const req = ++request;
    texts = [];
    infos = [];
    if (!kind || !paths.some(Boolean) || !ds.every(Boolean)) return;
    if (kind === 'text') {
      loading = true;
      Promise.all(ds.map((d, i) => (paths[i] ? api.text(d.run.key, paths[i]) : null))).then((t) => {
        if (req !== request) return;
        texts = t;
        loading = false;
      });
    } else if (kind === 'tensors') {
      loading = true;
      Promise.all(
        ds.map((d, i) =>
          paths[i]
            ? api.inspect(d.run.key, paths[i]).catch((e): TensorInfo => ({
                format: '',
                entries: [],
                tensors: 0,
                params: 0,
                bytes: 0,
                truncated: false,
                error: String(e),
              }))
            : null,
        ),
      ).then((x) => {
        if (req !== request) return;
        infos = x;
        loading = false;
      });
    }
  });

  const ext = $derived(pickedPath.split('.').pop()?.toLowerCase() ?? '');

  /** JSON pretty-printed, everything else as is. */
  function pretty(text: string): string {
    if (ext !== 'json') return text;
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  /** Rows of a CSV or TSV (quoted fields allowed), at most `max`. */
  function parseTable(text: string, max = 1000): string[][] {
    const sep = ext === 'tsv' ? '\t' : ',';
    const out: string[][] = [];
    let row: string[] = [];
    let cell = '';
    let quoted = false;
    for (let i = 0; i < text.length && out.length < max; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') {
          cell += '"';
          i++;
        } else if (c === '"') quoted = false;
        else cell += c;
      } else if (c === '"') quoted = true;
      else if (c === sep) {
        row.push(cell);
        cell = '';
      } else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell);
        out.push(row);
        row = [];
        cell = '';
      } else cell += c;
    }
    if ((cell || row.length) && out.length < max) out.push([...row, cell]);
    return out;
  }

  // Terminal output (color codes, progress bars) is drawn as a terminal shows it, and diffed by its visible text
  const showsTerminal = $derived(!multi && !!texts[0] && isTerminalText(texts[0].text));
  let raw = $state(false);
  const visible = (t: string) => (isTerminalText(t) ? stripAnsi(t) : pretty(t));
  const diffRows = $derived(
    multi && texts.length === 2 ? sideBySide(visible(texts[0]?.text ?? ''), visible(texts[1]?.text ?? '')) : [],
  );
  const shownDiff = $derived(
    onlyChanges
      ? diffRows.filter(
          (r, i) => r.kind !== 'same' || diffRows.slice(Math.max(0, i - 2), i + 3).some((x) => x.kind !== 'same'),
        )
      : diffRows,
  );

  // ---- tensors ----
  const keyOf = (e: TensorEntry) => e.path.join('/');
  const describe = (e: TensorEntry | undefined) =>
    !e
      ? '—'
      : e.kind === 'tensor'
        ? `${e.dtype} [${e.shape.join(', ')}]`
        : e.value === null
          ? e.type
          : `${e.value}${e.type === 'str' || e.type === 'int' || e.type === 'float' ? '' : ` (${e.type})`}`;
  let tensorFind = $state('');
  let tensorOpen = $state(new Set<string>());
  let tensorLimit = $state(500);
  $effect(() => {
    void pickedPath;
    tensorLimit = 500;
  });

  type TNode = {
    id: string;
    name: string;
    depth: number;
    leaf: TensorEntry | null;
    kids: boolean;
    params: number;
    bytes: number;
    n: number;
  };
  // One checkpoint as a tree: state_dict keys such as `encoder.layers.0.weight` split on dots
  const tensorRows = $derived.by(() => {
    const info = !multi ? infos[0] : null;
    if (!info) return [];
    const q = tensorFind.toLowerCase();
    const nodes = new Map<string, TNode>();
    const order: TNode[] = [];
    for (const e of info.entries) {
      const parts = e.path.flatMap((p) => p.split('.')).filter((p) => p !== '');
      if (!parts.length) parts.push('(root)');
      if (q && !parts.join('.').toLowerCase().includes(q)) continue;
      const params = e.kind === 'tensor' ? e.shape.reduce((a, b) => a * b, 1) : 0;
      const bytes = e.kind === 'tensor' ? (e.bytes ?? 0) : 0;
      for (let i = 0; i < parts.length; i++) {
        const id = parts.slice(0, i + 1).join('.');
        let node = nodes.get(id);
        if (!node) {
          node = { id, name: parts[i], depth: i, leaf: null, kids: false, params: 0, bytes: 0, n: 0 };
          nodes.set(id, node);
          order.push(node);
          if (i > 0) nodes.get(parts.slice(0, i).join('.'))!.kids = true;
        }
        node.params += params;
        node.bytes += bytes;
        if (e.kind === 'tensor') node.n++;
        if (i === parts.length - 1) node.leaf = e;
      }
    }
    // A node is shown when every ancestor is open (all are open while searching)
    const out: TNode[] = [];
    for (const n of order) {
      const parts = n.id.split('.');
      let visible = true;
      for (let i = 1; i < parts.length && !q; i++)
        if (!tensorOpen.has(parts.slice(0, i).join('.'))) {
          visible = false;
          break;
        }
      if (visible) out.push(n);
    }
    return out;
  });
  function toggleTensor(id: string) {
    const next = new Set(tensorOpen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    tensorOpen = next;
  }

  // Two checkpoints side by side, key by key
  const tensorDiff = $derived.by(() => {
    if (!multi || infos.length !== 2) return [];
    const [a, b] = infos.map((info) => new Map((info?.entries ?? []).map((e) => [keyOf(e), e])));
    const keys = [...new Set([...a.keys(), ...b.keys()])];
    return keys
      .map((k) => {
        const l = a.get(k);
        const r = b.get(k);
        const status = !l ? 'add' : !r ? 'del' : describe(l) === describe(r) ? 'same' : 'mod';
        return { k, l, r, status };
      })
      .filter((row) => !onlyChanges || row.status !== 'same')
      .filter((row) => !tensorFind || row.k.toLowerCase().includes(tensorFind.toLowerCase()));
  });
  const tensorChanges = $derived(tensorDiff.filter((r) => r.status !== 'same').length);

  const fmtCount = (n: number) =>
    n >= 1e9
      ? `${fmtNum(n / 1e9, 3)}B`
      : n >= 1e6
        ? `${fmtNum(n / 1e6, 3)}M`
        : n >= 1e3
          ? `${fmtNum(n / 1e3, 3)}K`
          : String(n);

  /** A path without the folders every match shares. */
  function shortName(path: string, all: RunFile[]): string {
    const dirs = all.map((f) => f.path.split('/').slice(0, -1));
    let n = 0;
    while (dirs.every((d) => n < d.length && d[n] === dirs[0][n])) n++;
    return path.split('/').slice(n).join('/');
  }

  async function unpin() {
    if (!pin) return;
    await pins.set(projects, pin, false);
    router.set({ tab: 'filetree' });
  }

  const totals = $derived(
    trees.map((t) => (t ? `${t.count} file${t.count === 1 ? '' : 's'} · ${fmtBytes(t.bytes)}` : '…')),
  );
</script>

<div class="files">
  {#if !pin}
    <div class="tree">
      <div class="treehead">
        {#each details as d, i (d.run.key)}
          <span class="total" title={d.run.path}
            >{#if multi}<i style="background:{colors[i % colors.length]}"></i>{/if}{totals[i] ?? '…'}</span
          >
        {/each}
        <input
          class="input sm mono find"
          placeholder="Filter files, or a pattern such as checkpoints/*/best_*.pth"
          aria-label="Filter files"
          bind:value={find}
        />
        {#if findRe && shownPaths.length}
          <button
            class="btn btn-ghost sm"
            title="Show the files matching {find.trim()} as a tab in every run of this project"
            onclick={() => pins.set(projects, find.trim(), true)}
            disabled={pinned.includes(find.trim().replace(/^\/+/, ''))}
            ><Icon name="pin" size={14} />
            {pinned.includes(find.trim().replace(/^\/+/, '')) ? 'Pinned' : 'Pin pattern'}</button
          >
        {/if}
        {#if internalCount}
          <label class="tg small"
            ><button
              class="switch"
              role="switch"
              aria-checked={showInternal}
              aria-label="Show NuBoard data"
              onclick={() => (showInternal = !showInternal)}
            ></button>NuBoard data ({internalCount})</label
          >
        {/if}
      </div>
      <div
        class="treebody mono"
        role="tree"
        aria-label="Run files"
        tabindex="-1"
        style="height:{treeH ?? autoH}px"
        onpointerup={(e) => {
          const h = (e.currentTarget as HTMLElement).offsetHeight;
          if (h !== (treeH ?? autoH)) treeH = h;
        }}
      >
        {#each rows as r (r.kind + r.path)}
          {#if r.kind === 'dir'}
            <button
              class="node dir"
              role="treeitem"
              aria-selected="false"
              aria-expanded={isOpen(r.path) || !!find}
              style="padding-left:{8 + r.depth * 14}px"
              title={r.path + '/'}
              onclick={() => toggleDir(r.path)}
            >
              <span class="chev" class:shut={!isOpen(r.path) && !find}><Icon name="chevron" size={13} /></span>
              <span class="nm">{r.name}/</span>
              <span class="meta">{r.count} · {fmtBytes(r.size)}</span>
            </button>
          {:else}
            {@const f = r.files.find(Boolean)!}
            {@const differs = multi && new Set(r.files.map((x) => (x ? x.size : -1))).size > 1}
            {@const [head, tail] = middle(r.name)}
            {@const isPinned = pinned.includes(r.path)}
            <div
              class="node"
              role="treeitem"
              tabindex="0"
              aria-selected={picked === r.path}
              style="padding-left:{22 + r.depth * 14}px"
              title={r.path}
              onclick={() => router.set({ file: r.path })}
              onkeydown={(e) => e.key === 'Enter' && router.set({ file: r.path })}
            >
              <span class="nm"
                ><span class="h">{head}</span>{#if tail}<span class="t">{tail}</span>{/if}</span
              >
              {#if multi}
                <span class="present">
                  {#each r.files as x, i (i)}<i
                      class:off={!x}
                      style="background:{colors[i % colors.length]}"
                      title={x ? `${details[i].run.name}: ${fmtBytes(x.size)}` : `not in ${details[i].run.name}`}
                    ></i>{/each}
                </span>
                {#if differs}<span class="chg" title="Sizes differ between runs">≠</span>{/if}
              {/if}
              <span class="meta">{fmtBytes(f.size)}</span>
              <button
                class="pinbtn"
                class:on={isPinned}
                aria-label={isPinned ? `Unpin ${r.path}` : `Pin ${r.path}`}
                title={isPinned ? 'Unpin: remove its tab' : 'Pin: show it as a tab in every run of this project'}
                onclick={(e) => {
                  e.stopPropagation();
                  pins.set(projects, r.path, !isPinned);
                }}><Icon name="pin" size={13} /></button
              >
            </div>
          {/if}
        {:else}
          <p class="faint pad">{trees.length ? (find ? `No file matches “${find}”.` : 'No files.') : 'Loading…'}</p>
        {/each}
      </div>
    </div>
  {/if}

  <section class="view">
    {#if !pickedFiles.some(Boolean)}
      <p class="faint pad">
        {#if pin}
          No file matches <span class="mono">{pin}</span> in {multi ? 'these runs' : 'this run'}.
          <button class="btn btn-ghost sm" onclick={unpin}>Unpin</button>
        {:else}
          Pick a file above to see it here. Text files show their content (diffed between runs), checkpoints list their
          tensors, and every file can be downloaded.
        {/if}
      </p>
    {:else}
      <div class="vhead">
        {#if pin}
          <span class="path pinpath mono" title={pin}><Icon name="pin" size={13} /> {pin}</span>
          <button class="btn btn-ghost sm" onclick={unpin}>Unpin</button>
        {:else}
          <span class="path mono" title={picked}>{picked}</span>
        {/if}
        {#if showsTerminal}
          <label class="tg small" title="The text as stored, with its color codes"
            ><button class="switch" role="switch" aria-checked={raw} aria-label="Raw" onclick={() => (raw = !raw)}
            ></button>Raw</label
          >
        {/if}
      </div>
      <div class="vhead">
        {#each shownIdx as i (i)}
          {@const f = pickedFiles[i]}
          <span class="fmeta">
            {#if multi}<i style="background:{colors[i % colors.length]}"></i>{/if}
            {#if pin && (matches[i]?.length ?? 0) > 1}
              <select
                class="input sm mono"
                aria-label="File of {details[i].run.name}"
                value={f?.path}
                onchange={(e) => (choice = { ...choice, [i]: (e.currentTarget as HTMLSelectElement).value })}
              >
                {#each matches[i] as m (m.path)}<option value={m.path} title={m.path}
                    >{shortName(m.path, matches[i])}</option
                  >{/each}
              </select>
            {:else if pin && f}
              <span class="pf mono" title={f.path}>{f.path}</span>
            {/if}
            {#if f}
              <span class="nowrap">{fmtBytes(f.size)} · {fmtDate(f.mtime)}</span>
              <a
                class="btn btn-ghost sm"
                href={api.rawUrl(details[i].run.key, f.path, true)}
                download
                title="Download {details[i].run.name}'s copy"><Icon name="download" size={14} /> Download</a
              >
            {:else}<span class="faint">Not in {details[i].run.name}</span>{/if}
          </span>
        {/each}
      </div>

      {#if loading}
        <p class="faint pad">Loading…</p>
      {:else if pickedKind === 'text'}
        {#if multi}
          <div class="diff mono">
            {#each [0, 1] as s (s)}
              <div class="dh"><b>{details[shownIdx[s]].run.name}</b><span>{texts[s] ? '' : 'missing'}</span></div>
            {/each}
            {#each shownDiff as r, i (i)}
              <div class="line {r.kind === 'same' ? '' : r.kind === 'add' ? 'none' : 'del'}">
                <span class="ln">{r.ln ?? ''}</span><span class="tx"
                  >{r.kind !== 'same' && r.left !== null ? '- ' : '  '}{r.left ?? ''}</span
                >
              </div>
              <div class="line {r.kind === 'same' ? '' : r.kind === 'del' ? 'none' : 'add'}">
                <span class="ln">{r.rn ?? ''}</span><span class="tx"
                  >{r.kind !== 'same' && r.right !== null ? '+ ' : '  '}{r.right ?? ''}</span
                >
              </div>
            {/each}
          </div>
        {:else if texts[0] && (ext === 'csv' || ext === 'tsv')}
          {@const table = parseTable(texts[0].text)}
          <div class="csv">
            <table class="mono">
              <thead
                ><tr
                  >{#each table[0] ?? [] as h, i (i)}<th>{h}</th>{/each}</tr
                ></thead
              >
              <tbody>
                {#each table.slice(1) as row, i (i)}<tr
                    >{#each row as c, j (j)}<td>{c}</td>{/each}</tr
                  >{/each}
              </tbody>
            </table>
          </div>
          {#if table.length >= 1000}<p class="faint small">The first 1,000 rows.</p>{/if}
        {:else}
          {#if showsTerminal}
            <Terminal text={texts[0]!.text} {raw} />
          {:else}
            <pre class="file mono">{texts[0] ? pretty(texts[0].text) : '(could not be read)'}</pre>
          {/if}
        {/if}
        {#if texts.some((t) => t?.truncated)}<p class="faint small">
            Only the first 2 MB is shown; download the file for all of it.
          </p>{/if}
      {:else if pickedKind === 'image'}
        <div class="imgs">
          {#each shownIdx as i (i)}
            {#if pickedFiles[i]}<img
                src={api.rawUrl(details[i].run.key, pickedFiles[i].path)}
                alt="{pickedFiles[i].path} of {details[i].run.name}"
              />{/if}
          {/each}
        </div>
      {:else if pickedKind === 'tensors'}
        <div class="tbar">
          {#each infos as info, s (s)}
            {#if info && (info.entries.length || multi)}
              <span class="sum">
                {#if multi}<i style="background:{colors[shownIdx[s] % colors.length]}"></i>{/if}
                <b>{fmtCount(info.tensors)}</b> tensors · <b>{fmtCount(info.params)}</b> values · {fmtBytes(info.bytes)}
                <span class="faint">({info.format})</span>
              </span>
            {/if}
          {/each}
          <input
            class="input sm mono tfind"
            placeholder="Filter keys"
            aria-label="Filter keys"
            bind:value={tensorFind}
          />
          {#if multi}<span class="faint small">{tensorChanges} key{tensorChanges === 1 ? '' : 's'} differ</span>{/if}
        </div>
        {#each infos as info, s (s)}
          {#if info?.error}<p class="warn small">
              {multi ? `${details[shownIdx[s]].run.name}: ` : ''}{info.entries.length
                ? 'Only part of this file could be read'
                : 'This file could not be read'}: {info.error}
            </p>{/if}
          {#if info?.truncated}<p class="faint small">
              Only the first {info.entries.length.toLocaleString()} entries are listed; the totals count all of them.
            </p>{/if}
        {/each}
        {#if multi}
          <div class="tdiff mono">
            <div class="trow head">
              <span>Key</span><span>{details[shownIdx[0]].run.name}</span><span>{details[shownIdx[1]].run.name}</span>
            </div>
            {#each tensorDiff.slice(0, tensorLimit) as row (row.k)}
              <div class="trow {row.status}">
                <span class="k" title={row.k}>{row.k}</span><span title={describe(row.l)}>{describe(row.l)}</span><span
                  title={describe(row.r)}>{describe(row.r)}</span
                >
              </div>
            {:else}
              <p class="faint pad">{onlyChanges ? 'No differences.' : 'Nothing to show.'}</p>
            {/each}
          </div>
          {#if tensorDiff.length > tensorLimit}<button class="btn btn-ghost sm" onclick={() => (tensorLimit += 2000)}
              >Show more ({tensorDiff.length - tensorLimit} left)</button
            >{/if}
        {:else if infos[0]?.entries.length}
          <div class="ttree mono" role="tree" aria-label="Tensors">
            <div class="tnode head"><span>Key</span><span>Shape</span><span>Dtype</span><span>Size</span></div>
            {#each tensorRows.slice(0, tensorLimit) as n (n.id)}
              {@const open = tensorOpen.has(n.id) || !!tensorFind}
              {@const leaf = n.kids ? null : n.leaf}
              <button
                class="tnode"
                role="treeitem"
                aria-selected="false"
                aria-expanded={leaf ? undefined : open}
                onclick={() => !leaf && toggleTensor(n.id)}
              >
                <span class="k" style="padding-left:{n.depth * 14}px" title={n.id}
                  >{#if !leaf}<span class="chev" class:shut={!open}><Icon name="chevron" size={12} /></span
                    >{/if}{n.name}</span
                >
                {#if leaf?.kind === 'tensor'}
                  <span>[{leaf.shape.join(', ')}]</span><span>{leaf.dtype}</span><span
                    >{leaf.bytes === null ? '—' : fmtBytes(leaf.bytes)}</span
                  >
                {:else if leaf}
                  <span class="val" title={leaf.value ?? leaf.type}>{leaf.value ?? ''}</span><span class="faint"
                    >{leaf.type}</span
                  ><span></span>
                {:else}
                  <span class="faint group"
                    >{n.n ? `${fmtCount(n.n)} tensor${n.n === 1 ? '' : 's'} · ${fmtCount(n.params)} values` : ''}{n.leaf
                      ?.kind === 'value'
                      ? `${n.n ? ' · ' : ''}${n.leaf.type}`
                      : ''}</span
                  ><span>{n.bytes ? fmtBytes(n.bytes) : ''}</span>
                {/if}
              </button>
            {/each}
          </div>
          {#if tensorRows.length > tensorLimit}<button class="btn btn-ghost sm" onclick={() => (tensorLimit += 2000)}
              >Show more ({tensorRows.length - tensorLimit} left)</button
            >{/if}
        {/if}
      {:else}
        <p class="faint pad">No preview for this kind of file. Download it to open it.</p>
      {/if}
    {/if}
  </section>
</div>

<style>
  .files {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .tree,
  .view {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .treehead {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 14px;
  }
  .find {
    flex: 1 1 260px;
    max-width: 520px;
  }
  .total,
  .fmeta,
  .sum {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    color: var(--muted);
  }
  .total i,
  .fmeta i,
  .sum i,
  .present i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex: none;
  }
  .tg {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    color: var(--muted);
  }
  .small {
    font-size: 12.5px;
  }
  .faint {
    color: var(--faint);
  }
  .pad {
    padding: 10px 12px;
    margin: 0;
  }
  .warn {
    margin: 0;
    color: var(--warn);
  }
  /* about 12 rows; the corner handle makes it taller */
  .treebody {
    border: 1px solid var(--border);
    border-radius: 10px;
    height: 290px;
    min-height: 90px;
    resize: vertical;
    overflow: auto;
    font-size: 12.5px;
    padding: 4px 0;
  }
  .node {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: 0;
    background: none;
    text-align: left;
    padding: 3px 10px;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .node:hover {
    background: var(--panel-2);
  }
  .node[aria-selected='true'] {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .node.dir {
    color: var(--muted);
  }
  .nm {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* a long name loses its middle, so the end (step, epoch, suffix) stays readable */
  .node .nm {
    display: flex;
  }
  .nm .h {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .nm .t {
    flex: none;
  }
  .pinbtn {
    flex: none;
    display: inline-grid;
    border: 0;
    background: none;
    padding: 1px 2px;
    color: var(--faint);
    opacity: 0;
    cursor: pointer;
  }
  .node:hover .pinbtn,
  .node:focus-within .pinbtn,
  .pinbtn.on {
    opacity: 1;
  }
  .pinbtn.on {
    color: var(--accent);
  }
  .meta {
    margin-left: auto;
    color: var(--faint);
    flex: none;
    font-size: 11.5px;
  }
  .present {
    display: inline-flex;
    gap: 2px;
    flex: none;
  }
  .present i.off {
    opacity: 0.18;
  }
  .chg {
    color: var(--warn);
    flex: none;
  }
  .chev {
    display: inline-grid;
    color: var(--faint);
    transition: transform 0.15s;
    flex: none;
  }
  .chev.shut {
    transform: rotate(-90deg);
  }
  .vhead {
    display: flex;
    align-items: center;
    gap: 6px 14px;
    flex-wrap: wrap;
  }
  .path {
    font-weight: 600;
    font-size: 13px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fmeta a {
    height: 26px;
  }
  .fmeta select,
  .pf {
    max-width: min(70ch, 60vw);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pinpath {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .nowrap {
    white-space: nowrap;
  }
  .file {
    font-size: 12.5px;
    max-height: 520px;
    overflow: auto;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    margin: 0;
    white-space: pre;
  }
  .csv {
    max-height: 520px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
  }
  .csv table {
    border-collapse: collapse;
    font-size: 12.5px;
  }
  .csv th,
  .csv td {
    padding: 4px 10px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    text-align: left;
  }
  .csv th {
    position: sticky;
    top: 0;
    background: var(--panel-2);
  }
  .imgs {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .imgs img {
    max-width: min(100%, 480px);
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel-2);
  }
  .diff {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    column-gap: 4px;
    font-size: 12.5px;
    max-height: 560px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel-2);
  }
  .dh {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: var(--panel-2);
  }
  .dh span {
    color: var(--faint);
    font-size: 11.5px;
  }
  .line {
    display: grid;
    grid-template-columns: 44px 1fr;
    min-height: 20px;
  }
  .ln {
    color: var(--faint);
    text-align: right;
    padding-right: 10px;
    user-select: none;
  }
  .tx {
    white-space: pre;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-left: 6px;
  }
  .line.del {
    background: var(--diff-del);
  }
  .line.add {
    background: var(--diff-add);
  }
  .line.none {
    background: repeating-linear-gradient(-45deg, transparent 0 4px, var(--border) 4px 5px);
    opacity: 0.5;
  }
  .tbar {
    display: flex;
    align-items: center;
    gap: 8px 16px;
    flex-wrap: wrap;
  }
  .tfind {
    width: 220px;
  }
  .ttree,
  .tdiff {
    border: 1px solid var(--border);
    border-radius: 10px;
    max-height: 560px;
    overflow: auto;
    font-size: 12.5px;
  }
  .tnode,
  .trow {
    display: grid;
    grid-template-columns: minmax(200px, 2fr) minmax(110px, 1fr) 100px 90px;
    gap: 12px;
    align-items: center;
    width: 100%;
    border: 0;
    border-bottom: 1px solid var(--border);
    background: none;
    text-align: left;
    padding: 4px 12px;
    color: var(--text);
    font: inherit;
  }
  .trow {
    grid-template-columns: minmax(220px, 2fr) minmax(0, 1fr) minmax(0, 1fr);
  }
  .tnode:last-child,
  .trow:last-child {
    border-bottom: 0;
  }
  .tnode.head,
  .trow.head {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--panel-2);
    font-weight: 600;
    color: var(--muted);
  }
  .tnode:not(.head):hover {
    background: var(--panel-2);
  }
  .tnode > span,
  .trow > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tnode .group {
    grid-column: span 2;
  }
  .tnode .k {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .trow.mod {
    background: var(--diff-del);
  }
  .trow.add {
    background: var(--diff-add);
  }
  .trow.del {
    background: var(--diff-del);
  }
  .trow .k {
    color: var(--muted);
  }
</style>
