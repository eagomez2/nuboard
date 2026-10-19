<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import Status from '../components/Status.svelte';
  import { api, type ArtifactVersion } from '../lib/api';
  import { fmtAgo, fmtBytes, fmtDate, fmtValue } from '../lib/format';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  const NODE_W = 168;
  const NODE_H = 44;
  const COL = 214;
  const GAP = 16;
  const MAX_NODES = 60;

  let artifacts = $state<ArtifactVersion[]>([]);
  let loaded = $state(false);

  $effect(() => {
    void app.runs?.version;
    api
      .artifacts(router.get('project') || null)
      .then((r) => {
        artifacts = r.artifacts;
        loaded = true;
      })
      .catch(() => (loaded = true));
  });

  const id = (a: ArtifactVersion) => `${a.project}|${a.name}|${a.version}`;
  const selected = $derived(
    artifacts.find((a) => id(a) === router.get('art')) ??
      // by default the most connected version: it shows the most lineage
      [...artifacts].sort(
        (a, b) =>
          b.consumers.length + b.producers.length - (a.consumers.length + a.producers.length) ||
          (b.manifest.created ?? 0) - (a.manifest.created ?? 0),
      )[0] ??
      null,
  );
  const byName = $derived.by(() => {
    const out = new Map<string, ArtifactVersion[]>();
    for (const a of artifacts) {
      const k = `${a.project}|${a.name}`;
      out.set(k, [...(out.get(k) ?? []), a]);
    }
    for (const list of out.values()) list.sort((a, b) => b.version - a.version);
    return [...out.entries()];
  });

  const runName = (key: string) =>
    app.runByKey(key)?.name ?? key.replace(/^\d{8}-\d{4}_/, '').replace(/_[a-z0-9]{6}$/, '');

  // Lineage: runs and artifact versions linked by "produced" and "used" edges,
  // laid out in columns by distance from the selected version (upstream left).
  const graph = $derived.by(() => {
    type Node = { id: string; kind: 'run' | 'artifact'; layer: number; label: string; sub: string; ref: string };
    type Placed = Node & { x: number; y: number };
    if (!selected)
      return {
        nodes: [] as Placed[],
        edges: [] as [string, string][],
        pos: new Map<string, { x: number; y: number }>(),
        width: 0,
        height: 0,
      };
    const out = new Map<string, string[]>();
    const inn = new Map<string, string[]>();
    const link = (a: string, b: string) => {
      out.set(a, [...(out.get(a) ?? []), b]);
      inn.set(b, [...(inn.get(b) ?? []), a]);
    };
    const arts = new Map(artifacts.map((a) => [`a:${id(a)}`, a]));
    for (const a of artifacts) {
      for (const k of a.producers) link(`r:${k}`, `a:${id(a)}`);
      for (const k of a.consumers) link(`a:${id(a)}`, `r:${k}`);
    }
    const start = `a:${id(selected)}`;
    const layer = new Map<string, number>([[start, 0]]);
    const queue = [start];
    while (queue.length && layer.size < MAX_NODES) {
      const n = queue.shift()!;
      const l = layer.get(n)!;
      // follow downstream from nodes at or right of the selection, upstream from those at or left
      const next = [...(l >= 0 ? (out.get(n) ?? []).map((m) => [m, l + 1] as const) : [])];
      next.push(...(l <= 0 ? (inn.get(n) ?? []).map((m) => [m, l - 1] as const) : []));
      for (const [m, ml] of next) {
        if (!layer.has(m)) {
          layer.set(m, ml);
          queue.push(m);
        }
      }
    }
    const nodes: Node[] = [...layer.entries()].map(([n, l]) => {
      if (n.startsWith('a:')) {
        const a = arts.get(n)!;
        return {
          id: n,
          kind: 'artifact',
          layer: l,
          label: `${a.name}:v${a.version}`,
          sub: a.manifest.type ?? 'artifact',
          ref: id(a),
        };
      }
      const key = n.slice(2);
      const r = app.runByKey(key);
      return { id: n, kind: 'run', layer: l, label: runName(key), sub: r?.status ?? 'run', ref: key };
    });
    const layers = [...new Set(nodes.map((n) => n.layer))].sort((a, b) => a - b);
    const rows = new Map<number, number>();
    const pos = new Map<string, { x: number; y: number }>();
    nodes.sort((a, b) => a.layer - b.layer || a.label.localeCompare(b.label));
    for (const n of nodes) {
      const row = rows.get(n.layer) ?? 0;
      rows.set(n.layer, row + 1);
      pos.set(n.id, { x: 16 + layers.indexOf(n.layer) * COL, y: 16 + row * (NODE_H + GAP) });
    }
    const tallest = Math.max(...rows.values());
    // center each column vertically
    for (const n of nodes) {
      const p = pos.get(n.id)!;
      p.y += ((tallest - rows.get(n.layer)!) * (NODE_H + GAP)) / 2;
    }
    const edges: [string, string][] = [];
    for (const [a, targets] of out) for (const b of targets) if (layer.has(a) && layer.has(b)) edges.push([a, b]);
    return {
      nodes: nodes.map((n): Placed => ({ ...n, ...pos.get(n.id)! })),
      edges: edges.map(([a, b]) => [a, b] as [string, string]),
      pos,
      width: 32 + (layers.length - 1) * COL + NODE_W,
      height: 32 + tallest * (NODE_H + GAP) - GAP,
    };
  });

  function edgePath(a: string, b: string): string {
    const pa = graph.pos?.get(a);
    const pb = graph.pos?.get(b);
    if (!pa || !pb) return '';
    const x0 = pa.x + NODE_W;
    const y0 = pa.y + NODE_H / 2;
    const x1 = pb.x;
    const y1 = pb.y + NODE_H / 2;
    const mid = (x0 + x1) / 2;
    return `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${x1},${y1}`;
  }

  function openNode(n: { kind: string; ref: string }) {
    if (n.kind === 'artifact') router.set({ art: n.ref });
    else router.go('runs', { cmp: n.ref });
  }
</script>

{#if !loaded}
  <div class="card empty">Loading artifacts…</div>
{:else if !artifacts.length}
  <div class="card empty">
    <Icon name="artifact" size={28} />
    <p>No artifacts here yet. Log one from a run:</p>
    <pre class="mono">run.add_artifact("dataset", "data/", type="dataset")
run.use_artifact("dataset:latest")</pre>
    <p class="faint">Each version is a folder under <code>&lt;project&gt;/artifacts/&lt;name&gt;/v&lt;N&gt;/</code>.</p>
  </div>
{:else}
  <div class="layout">
    <aside class="card side">
      <div class="label">Artifacts</div>
      {#each byName as [k, versions] (k)}
        <div class="aname">
          <Icon name="artifact" size={15} />
          <span class="grow mono" title={versions[0].name}>{versions[0].name}</span>
          <span class="faint small trunc proj" title={versions[0].project}>{versions[0].project}</span>
        </div>
        {#each versions as a (id(a))}
          <button class="ver" class:on={selected && id(a) === id(selected)} onclick={() => router.set({ art: id(a) })}>
            <span class="mono">v{a.version}</span>
            <span class="faint small grow" title={a.manifest.type ?? ''}>{a.manifest.type ?? ''}</span>
            <span class="faint small keep">{fmtAgo(a.manifest.created)}</span>
          </button>
        {/each}
      {/each}
    </aside>

    {#if selected}
      <section class="main">
        <div class="card head">
          <div class="title">
            <h2 class="mono trunc" title="{selected.name}:v{selected.version}">{selected.name}:v{selected.version}</h2>
            {#if selected.manifest.type}<span class="chip keep">{selected.manifest.type}</span>{/if}
            {#if selected.manifest.reference}<span
                class="chip keep"
                title="The files stay where they are; NuBoard records their path and fingerprint">Reference</span
              >{/if}
            {#if selected.version === Math.max(...artifacts
                  .filter((a) => a.project === selected.project && a.name === selected.name)
                  .map((a) => a.version))}<span class="chip latest keep">Latest</span>{/if}
          </div>
          {#if selected.manifest.description}<p class="desc">{selected.manifest.description}</p>{/if}
          <div class="facts">
            <div class="fact-name">
              <span class="label">Project</span><span class="trunc" title={selected.project}>{selected.project}</span>
            </div>
            <div><span class="label">Created</span><span>{fmtDate(selected.manifest.created)}</span></div>
            {#if selected.manifest.created_by?.user || selected.manifest.created_by?.host}
              <div class="fact-name">
                <span class="label">By</span><span class="trunc" title={selected.manifest.created_by?.command ?? ''}
                  >{[selected.manifest.created_by?.user, selected.manifest.created_by?.host]
                    .filter(Boolean)
                    .join('@')}</span
                >
              </div>
            {/if}
            <div><span class="label">Size</span><span class="mono">{fmtBytes(selected.size)}</span></div>
            <div><span class="label">Files</span><span class="mono">{selected.manifest.files?.length ?? 0}</span></div>
            <div>
              <span class="label">Stored</span><span>{selected.manifest.reference ? 'Reference' : 'Copy'}</span>
            </div>
            <div><span class="label">Used by</span><span class="mono">{selected.consumers.length} runs</span></div>
          </div>
          <pre class="mono snippet">run.use_artifact("{selected.project}/{selected.name}:v{selected.version}")</pre>
        </div>

        <div class="card lineage">
          <div class="sh">
            <span class="label">Lineage</span><span class="faint">Upstream on the left, downstream on the right</span>
          </div>
          <div class="scroll">
            <svg width={graph.width} height={graph.height} role="img" aria-label="Lineage graph">
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" class="arrowhead" />
                </marker>
              </defs>
              {#each graph.edges as [a, b] (a + b)}
                <path class="edge" d={edgePath(a, b)} marker-end="url(#arrow)" />
              {/each}
              {#each graph.nodes as n (n.id)}
                <g
                  class="node {n.kind}"
                  class:sel={n.kind === 'artifact' && n.ref === id(selected)}
                  transform="translate({n.x},{n.y})"
                  role="button"
                  tabindex="0"
                  onclick={() => openNode(n)}
                  onkeydown={(e) => e.key === 'Enter' && openNode(n)}
                >
                  <rect width={NODE_W} height={NODE_H} rx={n.kind === 'artifact' ? 8 : 12} />
                  <title>{n.label}</title>
                  <text class="nl mono" x="12" y="19">{n.label.length > 20 ? n.label.slice(0, 18) + '…' : n.label}</text
                  >
                  <text class="ns" x="12" y="34">{n.kind === 'run' ? `run · ${n.sub}` : n.sub}</text>
                </g>
              {/each}
            </svg>
          </div>
        </div>

        <div class="cols">
          <div class="card box">
            <div class="label">Produced by</div>
            {#each selected.producers as k (k)}
              <button class="runlink" onclick={() => router.go('runs', { cmp: k })}>
                <Status status={app.runByKey(k)?.status ?? 'finished'} /><span class="mono trunc" title={runName(k)}
                  >{runName(k)}</span
                >
              </button>
            {:else}
              <p class="faint">Logged outside a run.</p>
            {/each}
            <div class="label gap">Used by</div>
            {#each selected.consumers as k (k)}
              <button class="runlink" onclick={() => router.go('runs', { cmp: k })}>
                <Status status={app.runByKey(k)?.status ?? 'finished'} /><span class="mono trunc" title={runName(k)}
                  >{runName(k)}</span
                >
              </button>
            {:else}
              <p class="faint">No run has used this version yet.</p>
            {/each}
          </div>
          <div class="card box">
            <div class="label">Metadata</div>
            {#each Object.entries(selected.manifest.metadata ?? {}) as [k, v] (k)}
              <div class="kv">
                <span class="mono faint trunc" title={k}>{k}</span><span class="mono kval">{fmtValue(v)}</span>
              </div>
            {:else}
              <p class="faint">None.</p>
            {/each}
          </div>
        </div>

        <div class="card box">
          <div class="label">Files</div>
          <table>
            <thead><tr><th>Path</th><th class="right">Size</th><th>SHA-256</th></tr></thead>
            <tbody>
              {#each selected.manifest.files ?? [] as f (f.path)}
                <tr>
                  <td class="mono path">{f.path}</td>
                  <td class="mono right keep">{fmtBytes(f.size)}</td>
                  <td class="mono faint" title={f.sha256 ?? 'Not hashed: checked by size'}
                    >{f.sha256 ? `${f.sha256.slice(0, 12)}…` : '—'}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="faint small">
            {#if selected.manifest.reference}
              References <code>{selected.manifest.reference}</code>; the files are not copied.
            {:else}
              On disk: <code>{selected.project}/artifacts/{selected.name}/v{selected.version}/files/</code>
            {/if}
          </p>
        </div>
      </section>
    {/if}
  </div>
{/if}

<style>
  .layout {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .side {
    min-width: 0;
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    position: sticky;
    top: 16px;
  }
  .side .label {
    padding: 0 8px 8px;
  }
  .aname {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 8px 4px;
    font-size: 13.5px;
    font-weight: 600;
  }
  .ver {
    display: flex;
    align-items: center;
    gap: 8px;
    border: 0;
    background: none;
    border-radius: 8px;
    padding: 6px 8px 6px 31px;
    font-size: 13px;
    color: var(--text);
    text-align: left;
    min-width: 0;
  }
  .ver:hover {
    background: var(--panel-2);
  }
  .ver.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .grow {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .small {
    font-size: 12px;
  }
  /* Long names shrink with an ellipsis (full text in the title attribute); values never do. */
  .trunc {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .keep {
    flex: none;
    white-space: nowrap;
  }
  .proj {
    max-width: 35%;
  }
  .kv .trunc {
    flex: none;
    max-width: 45%;
  }
  .fact-name {
    min-width: 0;
    max-width: 100%;
  }
  .kval {
    min-width: 0;
    text-align: right;
    overflow-wrap: anywhere;
  }
  .path {
    overflow-wrap: anywhere;
  }
  .faint {
    color: var(--faint);
  }
  .main {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
  }
  .head {
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .title {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  h2 {
    margin: 0;
    font-size: 19px;
  }
  .latest {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .desc {
    margin: 0;
    font-size: 14px;
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .facts {
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    font-size: 13.5px;
  }
  .facts > div {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .snippet {
    margin: 0;
    padding: 8px 12px;
    background: var(--panel-2);
    border-radius: 8px;
    font-size: 12.5px;
    overflow-x: auto;
  }
  .lineage {
    padding: 14px;
  }
  .sh {
    display: flex;
    gap: 12px;
    align-items: baseline;
    font-size: 12.5px;
    padding-bottom: 8px;
  }
  .scroll {
    overflow-x: auto;
  }
  svg {
    display: block;
  }
  .edge {
    fill: none;
    stroke: var(--faint);
    stroke-width: 1.5;
  }
  .arrowhead {
    fill: var(--faint);
  }
  .node {
    cursor: pointer;
  }
  .node rect {
    fill: var(--panel);
    stroke: var(--border);
    stroke-width: 1.5;
  }
  .node.artifact rect {
    fill: var(--panel-2);
  }
  .node.sel rect {
    stroke: var(--accent);
    stroke-width: 2.5;
    fill: var(--accent-soft);
  }
  .node:hover rect {
    stroke: var(--accent);
  }
  .nl {
    fill: var(--text);
    font-size: 12.5px;
    font-weight: 600;
  }
  .ns {
    fill: var(--muted);
    font-size: 11px;
  }
  .cols {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 16px;
  }
  .box {
    min-width: 0;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .box p {
    margin: 0;
    font-size: 13px;
  }
  .gap {
    margin-top: 10px;
  }
  .runlink {
    display: flex;
    align-items: center;
    gap: 10px;
    border: 0;
    background: none;
    padding: 4px 0;
    color: var(--text);
    font-size: 13px;
    text-align: left;
    min-width: 0;
    max-width: 100%;
  }
  .runlink:hover .mono {
    color: var(--accent);
    text-decoration: underline;
  }
  .kv {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    font-size: 13px;
    padding: 3px 0;
    border-bottom: 1px solid var(--border);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  th {
    text-align: left;
    color: var(--muted);
    font-size: 11.5px;
    font-weight: 600;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  .right {
    text-align: right;
  }
  code {
    font-family: var(--mono);
    overflow-wrap: anywhere;
  }
  .empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
  }
  .empty pre {
    text-align: left;
    background: var(--panel-2);
    padding: 10px 14px;
    border-radius: 8px;
  }
  @media (max-width: 1100px) {
    .layout,
    .cols {
      grid-template-columns: minmax(0, 1fr);
    }
    .side {
      position: static;
    }
  }
</style>
