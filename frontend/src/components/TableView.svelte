<script lang="ts">
  import { flip } from 'svelte/animate';
  import MediaView from './MediaView.svelte';
  import { api, type MediaItem } from '../lib/api';
  import { lowerIsBetter } from '../lib/format';
  import { TABLE_MIME } from '../lib/media';
  import { isCellRef, loadTable, rowFilter, runMedia, type Cell, type TableData } from '../lib/tables';

  /**
   * A table logged with `add_table`, at the step of `item`. Each cell is
   * compared with the same row (matched by the table's id column) at the
   * previous step or the first one: tinted green when it got better and orange
   * when it got worse, with the change next to the value. Rows glide to their
   * new place when the step changes.
   */
  let { runKey, runName, item }: { runKey: string; runName: string; item: MediaItem } = $props();

  const LIMIT = 100; // rows drawn before "Show all"
  const TREND_STEPS = 12; // at most this many steps are loaded for the trend column

  let media = $state<MediaItem[]>([]);
  $effect(() => {
    void runMedia(runKey).then((list) => (media = list));
  });
  const history = $derived(
    media.filter((m) => m.key === item.key && m.mime === TABLE_MIME).sort((a, b) => a.step - b.step),
  );
  const cells = $derived(new Map(media.filter((m) => m.kind === 'cell').map((m) => [`${m.key}@${m.step}`, m])));

  let compare = $state<'prev' | 'first' | 'none'>('prev');
  let mode = $state<'both' | 'color' | 'delta'>('both');
  let find = $state('');
  let sort = $state<{ col: number; asc: boolean } | null>(null);
  let selected = $state<string | null>(null);
  let all = $state(false);

  const url = (it: MediaItem) => api.mediaUrl(runKey, it.index!);
  const against = $derived.by((): MediaItem | null => {
    if (compare === 'none') return null;
    const before = history.filter((h) => h.step < item.step);
    return (compare === 'first' ? before[0] : before[before.length - 1]) ?? null;
  });
  const trendItems = $derived.by(() => {
    if (history.length <= TREND_STEPS) return history;
    const every = (history.length - 1) / (TREND_STEPS - 1);
    return Array.from({ length: TREND_STEPS }, (_, i) => history[Math.round(i * every)]);
  });

  let table = $state<TableData | null>(null);
  let base = $state<TableData | null>(null);
  let trend = $state<{ step: number; data: TableData }[]>([]);
  $effect(() => {
    const u = url(item);
    void loadTable(u).then((d) => {
      if (u === url(item)) table = d;
    });
  });
  $effect(() => {
    const it = against;
    base = null;
    if (it) void loadTable(url(it)).then((d) => it === against && (base = d));
  });
  $effect(() => {
    const list = trendItems;
    void Promise.all(list.map((it) => loadTable(url(it)).then((d) => (d ? { step: it.step, data: d } : null)))).then(
      (out) => list === trendItems && (trend = out.filter((x) => x !== null)),
    );
  });

  const columns = $derived(table?.columns ?? []);
  const idCol = $derived(
    Math.max(
      0,
      columns.findIndex((c) => c.name === table?.id),
    ),
  );
  const idOf = (row: Cell[]) => String(row[idCol] ?? '');
  const baseRows = $derived(new Map((base?.rows ?? []).map((r) => [idOf(r), r])));

  // The column the stripes, summary and trend follow: the sorted one if it holds numbers
  const primary = $derived.by(() => {
    if (sort && columns[sort.col]?.type === 'number') return sort.col;
    const numbers = columns.flatMap((c, i) => (c.type === 'number' ? [i] : []));
    // an input column (the same at every step) says nothing about training: prefer one that moved
    const moved = numbers.find((i) =>
      (table?.rows ?? []).some((r) => {
        const old = baseRows.get(idOf(r))?.[i];
        return typeof old === 'number' && old !== r[i];
      }),
    );
    return moved ?? numbers[0] ?? -1;
  });
  const ranges = $derived(
    columns.map((c, i) => {
      if (c.type !== 'number') return 1;
      const vals = (table?.rows ?? []).map((r) => r[i]).filter((v): v is number => typeof v === 'number');
      return vals.length ? Math.max(...vals) - Math.min(...vals) || 1 : 1;
    }),
  );
  const better = (col: number, delta: number) => (lowerIsBetter(columns[col].name) ? delta < 0 : delta > 0);

  const filtering = $derived.by((): { rows: Cell[][]; error: string } => {
    if (!table) return { rows: [], error: '' };
    try {
      const keep = rowFilter(find, columns);
      return { rows: table.rows.filter((r) => keep(r, idOf(r))), error: '' };
    } catch (e) {
      return { rows: table.rows, error: e instanceof Error ? e.message : String(e) };
    }
  });
  const filtered = $derived(filtering.rows);
  const filterError = $derived(filtering.error);
  function order(rows: Cell[][]): Cell[][] {
    if (!sort) return rows;
    const { col, asc } = sort;
    return [...rows].sort((a, b) => {
      const x = a[col];
      const y = b[col];
      if (x === null || isCellRef(x)) return 1;
      if (y === null || isCellRef(y)) return -1;
      const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
      return asc ? c : -c;
    });
  }
  const sorted = $derived(order(filtered));
  const shown = $derived(all ? sorted : sorted.slice(0, LIMIT));
  // Places each row moved in the current sort since the compared step
  const before = $derived.by(() => {
    if (!base || !sort) return new Map<string, number>();
    const ids = new Set(filtered.map(idOf));
    return new Map(order(base.rows.filter((r) => ids.has(idOf(r)))).map((r, i) => [idOf(r), i]));
  });

  const summary = $derived.by(() => {
    if (primary < 0 || !table) return null;
    const vals = filtered.map((r) => r[primary]).filter((v): v is number => typeof v === 'number');
    const mean = vals.reduce((a, b) => a + b, 0) / (vals.length || 1);
    if (!base) return { mean, delta: null, up: 0, down: 0 };
    let up = 0;
    let down = 0;
    let sum = 0;
    let n = 0;
    for (const r of filtered) {
      const old = baseRows.get(idOf(r))?.[primary];
      const now = r[primary];
      if (typeof old !== 'number' || typeof now !== 'number') continue;
      sum += old;
      n++;
      if (Math.abs(now - old) > 0.08 * ranges[primary]) {
        if (better(primary, now - old)) up++;
        else down++;
      }
    }
    return { mean, delta: n ? mean - sum / n : null, up, down };
  });

  function stripe(row: Cell[]): string {
    if (primary < 0) return '';
    const old = baseRows.get(idOf(row))?.[primary];
    const now = row[primary];
    if (typeof old !== 'number' || typeof now !== 'number') return '';
    if (Math.abs(now - old) <= 0.08 * ranges[primary]) return '';
    return better(primary, now - old) ? 'better' : 'worse';
  }

  // Decimals per column: as few as the logged values need, at most 3
  const decimals = $derived(
    columns.map((c, i) => {
      if (c.type !== 'number') return 0;
      const vals = (table?.rows ?? []).map((r) => r[i]).filter((v): v is number => typeof v === 'number');
      for (let d = 0; d <= 3; d++)
        if (vals.every((v) => Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) < 1e-6)) return d;
      const top = Math.max(0, ...vals.map(Math.abs));
      return top >= 100 ? 1 : top >= 10 ? 2 : 3;
    }),
  );
  const digits = (col: number) => decimals[col] ?? 3;
  const fmt = (v: number, col: number) => v.toFixed(digits(col));

  function change(row: Cell[], col: number): { text: string; tint: string; cls: string } | null {
    if (!base) return null;
    const old = baseRows.get(idOf(row))?.[col];
    const now = row[col];
    if (typeof old !== 'number' || typeof now !== 'number') return null;
    const delta = now - old;
    const size = Math.abs(delta) / ranges[col];
    const flat = size < 0.01;
    const good = better(col, delta);
    const color = good ? 'var(--s4)' : 'var(--s5)';
    const tint =
      flat || mode === 'delta'
        ? ''
        : `background-color: color-mix(in srgb, ${color} ${Math.round(Math.min(40, 6 + size * 90))}%, transparent)`;
    const text =
      mode === 'color' || delta === 0 ? '' : `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(digits(col))}`;
    return { text, tint, cls: flat ? 'flat' : good ? 'up' : 'down' };
  }

  // Trend of the primary column over the loaded steps
  const trendIndex = $derived(
    trend.map(({ step, data }) => {
      const col = data.columns.findIndex((c) => c.name === columns[primary]?.name);
      const id = Math.max(
        0,
        data.columns.findIndex((c) => c.name === data.id),
      );
      return { step, values: new Map(data.rows.map((r) => [String(r[id] ?? ''), col >= 0 ? r[col] : null])) };
    }),
  );
  const trendRange = $derived.by(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const t of trendIndex)
      for (const v of t.values.values())
        if (typeof v === 'number') {
          lo = Math.min(lo, v);
          hi = Math.max(hi, v);
        }
    return { lo, span: hi - lo || 1 };
  });
  function spark(id: string): { d: string; dot: [number, number] | null } {
    const W = 72;
    const H = 18;
    const n = trendIndex.length;
    let d = '';
    let dot: [number, number] | null = null;
    trendIndex.forEach((t, i) => {
      const v = t.values.get(id);
      if (typeof v !== 'number') return;
      const x = 3 + (i * (W - 6)) / Math.max(1, n - 1);
      const y = H - 3 - ((v - trendRange.lo) / trendRange.span) * (H - 6);
      d += `${d ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
      if (t.step === item.step) dot = [x, y];
    });
    return { d, dot };
  }

  function sortBy(col: number) {
    sort = sort?.col === col ? { col, asc: !sort.asc } : { col, asc: true };
  }
  const cellItem = (ref: { $cell: string }) => cells.get(`${ref.$cell}@${item.step}`) ?? null;
  const selectedRow = $derived(selected === null ? null : (table?.rows.find((r) => idOf(r) === selected) ?? null));
</script>

<div class="tv">
  <div class="bar">
    <div class="seg" role="group" aria-label="Compare with">
      <button aria-pressed={compare === 'prev'} onclick={() => (compare = 'prev')}>previous step</button>
      <button aria-pressed={compare === 'first'} onclick={() => (compare = 'first')}>first step</button>
      <button aria-pressed={compare === 'none'} onclick={() => (compare = 'none')}>nothing</button>
    </div>
    <div class="seg" role="group" aria-label="Show change as">
      <button aria-pressed={mode === 'both'} onclick={() => (mode = 'both')}>color + Δ</button>
      <button aria-pressed={mode === 'color'} onclick={() => (mode = 'color')}>color</button>
      <button aria-pressed={mode === 'delta'} onclick={() => (mode = 'delta')}>Δ</button>
    </div>
    <input
      class="input sm mono find"
      class:bad={filterError}
      placeholder="Filter rows: snr_in < 0 and noise = babble"
      aria-label="Filter rows"
      title={filterError || 'Comparisons joined with and; other text matches the row id'}
      bind:value={find}
    />
  </div>

  {#if !table}
    <div class="faint none">Loading…</div>
  {:else}
    <div class="summary">
      <span><b>{filtered.length.toLocaleString()}</b> of {table.rows.length.toLocaleString()} rows</span>
      {#if summary}
        <span
          >mean {columns[primary].name} <b>{summary.mean.toFixed(Math.max(2, digits(primary)))}</b>
          {#if summary.delta !== null}
            <span class="pill {better(primary, summary.delta) ? 'up' : 'down'}"
              >{summary.delta >= 0 ? '+' : '−'}{Math.abs(summary.delta).toFixed(digits(primary))}</span
            >
          {/if}</span
        >
        {#if base && against}
          <span><b>{summary.up}</b> improved</span>
          <span><b class="bad">{summary.down}</b> got worse</span>
          <span class="faint">since step {against.step.toLocaleString()}</span>
        {/if}
      {/if}
      {#if filterError}<span class="bad">{filterError}</span>{/if}
    </div>

    <div class="scroll" role="region" aria-label="{runName} {item.key} at step {item.step}">
      <table>
        <thead>
          <tr>
            <th class="num">#</th>
            {#each columns as c, i (c.name)}
              <th
                class:num={c.type === 'number'}
                aria-sort={sort?.col === i ? (sort.asc ? 'ascending' : 'descending') : 'none'}
              >
                <button onclick={() => sortBy(i)}
                  >{c.name}{#if c.type === 'number'}<span class="dir">{lowerIsBetter(c.name) ? ' ↓' : ' ↑'}</span
                    >{/if}{#if sort?.col === i}<span class="arrow">{sort.asc ? ' ▲' : ' ▼'}</span>{/if}</button
                >
              </th>
            {/each}
            {#if trendIndex.length > 1 && primary >= 0}<th>trend <span class="dir">{columns[primary].name}</span></th
              >{/if}
          </tr>
        </thead>
        <tbody>
          {#each shown as row, ri (idOf(row))}
            {@const id = idOf(row)}
            {@const moved = before.has(id) ? before.get(id)! - ri : 0}
            <tr
              class={stripe(row)}
              class:sel={selected === id}
              animate:flip={{ duration: shown.length > 200 ? 0 : 420 }}
              onclick={() => (selected = selected === id ? null : id)}
            >
              <td class="num rank mono"
                >{ri + 1}{#if moved}<span class="mv">{moved > 0 ? ` ↑${moved}` : ` ↓${-moved}`}</span>{/if}</td
              >
              {#each columns as c, ci (c.name)}
                {@const v = row[ci]}
                {#if isCellRef(v)}
                  {@const it = cellItem(v)}
                  <td>
                    {#if it && it.mime.startsWith('image/')}
                      <img class="thumb" src={url(it)} alt="{c.name} of {id}" />
                    {:else if it}
                      <span class="clip">▶ clip</span>
                    {:else}<span class="faint">–</span>{/if}
                  </td>
                {:else if typeof v === 'number'}
                  {@const ch = change(row, ci)}
                  <td class="num heat" style={ch?.tint ?? ''}
                    >{fmt(v, ci)}{#if ch && ch.text}<span class="d {ch.cls}">{ch.text}</span>{/if}</td
                  >
                {:else if typeof v === 'boolean'}
                  <td>{v ? '✓' : '–'}</td>
                {:else}
                  <td class:mono={ci === idCol}>{v ?? ''}</td>
                {/if}
              {/each}
              {#if trendIndex.length > 1 && primary >= 0}
                {@const s = spark(id)}
                <td>
                  <svg width="72" height="18" viewBox="0 0 72 18" aria-hidden="true">
                    <path d={s.d} fill="none" stroke="var(--faint)" stroke-width="1.4" />
                    {#if s.dot}<circle cx={s.dot[0]} cy={s.dot[1]} r="2.6" fill="var(--accent)" />{/if}
                  </svg>
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
      {#if !filtered.length}<p class="faint none">No row matches this filter.</p>{/if}
    </div>
    {#if sorted.length > shown.length}
      <button class="btn btn-ghost sm more" onclick={() => (all = true)}
        >Show all {sorted.length.toLocaleString()} rows</button
      >
    {/if}

    {#if selectedRow}
      <div class="detail">
        <div class="dhead">
          <b class="mono">{selected}</b>
          <button class="btn btn-ghost sm" onclick={() => (selected = null)}>Close</button>
        </div>
        {#if trendIndex.length > 1}
          <div class="scroll small-table">
            <table>
              <thead
                ><tr
                  ><th>step</th>{#each columns as c (c.name)}{#if c.type === 'number'}<th class="num">{c.name}</th
                      >{/if}{/each}</tr
                ></thead
              >
              <tbody>
                {#each trend as t (t.step)}
                  {@const r = t.data.rows.find(
                    (x) =>
                      String(
                        x[
                          Math.max(
                            0,
                            t.data.columns.findIndex((c) => c.name === t.data.id),
                          )
                        ] ?? '',
                      ) === selected,
                  )}
                  <tr class:now={t.step === item.step}>
                    <td class="mono">{t.step.toLocaleString()}</td>
                    {#each columns as c, ci (c.name)}
                      {#if c.type === 'number'}
                        {@const k = t.data.columns.findIndex((x) => x.name === c.name)}
                        {@const v = r && k >= 0 ? r[k] : null}
                        <td class="num">{typeof v === 'number' ? fmt(v, ci) : '–'}</td>
                      {/if}
                    {/each}
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
        {#each columns as c, ci (c.name)}
          {@const v = selectedRow[ci]}
          {#if isCellRef(v) && cellItem(v)}
            <div class="cell">
              <span class="faint small">{c.name} at step {item.step.toLocaleString()}</span>
              <MediaView {runKey} {runName} item={cellItem(v)!} player="wave" />
            </div>
          {/if}
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .tv {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .seg button {
    height: 26px;
    font-size: 12px;
  }
  .find {
    flex: 1;
    min-width: 200px;
    max-width: 340px;
  }
  .find.bad {
    border-color: var(--s5);
  }
  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 18px;
    font-size: 12.5px;
    color: var(--muted);
  }
  .summary b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .bad,
  .summary b.bad {
    color: var(--s5);
  }
  .pill {
    font-family: var(--mono);
    font-size: 11.5px;
    border-radius: 6px;
    padding: 0 5px;
  }
  .pill.up {
    color: var(--s4);
    background: color-mix(in srgb, var(--s4) 14%, transparent);
  }
  .pill.down {
    color: var(--s5);
    background: color-mix(in srgb, var(--s5) 14%, transparent);
  }
  .scroll {
    overflow: auto;
    max-height: 480px;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    font-size: 12.5px;
    font-variant-numeric: tabular-nums;
  }
  th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--panel);
    text-align: left;
    border-bottom: 1px solid var(--border);
    padding: 0;
    white-space: nowrap;
    font-weight: 600;
    color: var(--muted);
  }
  th button {
    all: unset;
    cursor: pointer;
    display: block;
    padding: 6px 8px;
    width: 100%;
    box-sizing: border-box;
  }
  th button:focus-visible {
    outline: 2px solid var(--accent);
  }
  th.num,
  td.num,
  th.num button {
    text-align: right;
  }
  .dir {
    font-weight: 400;
    color: var(--faint);
  }
  .arrow {
    color: var(--accent);
  }
  td {
    padding: 4px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tbody tr {
    cursor: pointer;
  }
  tbody tr:hover td {
    background-color: var(--panel-2);
  }
  tbody tr.sel td {
    background-color: var(--accent-soft);
  }
  tbody tr.better td:first-child {
    box-shadow: inset 3px 0 0 var(--s4);
  }
  tbody tr.worse td:first-child {
    box-shadow: inset 3px 0 0 var(--s5);
  }
  .heat {
    transition: background-color 0.3s;
  }
  .rank {
    color: var(--faint);
    font-size: 11.5px;
  }
  .mv {
    color: var(--muted);
  }
  .d {
    display: inline-block;
    min-width: 46px;
    margin-left: 6px;
    text-align: left;
    font-family: var(--mono);
    font-size: 11px;
  }
  .d.up {
    color: var(--s4);
  }
  .d.down {
    color: var(--s5);
  }
  .d.flat {
    color: var(--faint);
  }
  .clip {
    color: var(--accent);
    font-size: 12px;
  }
  .thumb {
    height: 32px;
    border-radius: 4px;
    display: block;
  }
  .none {
    padding: 16px;
    text-align: center;
    font-size: 12.5px;
    margin: 0;
  }
  .more {
    align-self: flex-start;
  }
  .detail {
    display: flex;
    flex-direction: column;
    gap: 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
  }
  .dhead {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .small-table {
    max-height: 220px;
  }
  tr.now td {
    background: var(--accent-soft);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .faint {
    color: var(--faint);
  }
  .small {
    font-size: 12px;
  }
</style>
