<script lang="ts">
  // Lines that tell a run apart from others with the same name: name and id suffix on top; its
  // status and start below; then its tags, and a context line (such as its hypothesis) if given.
  import { cap, fmtDate } from '../lib/format';
  import TagPills from './TagPills.svelte';
  import { idSuffix, type PickRun } from '../lib/runlabel';

  // a run that is gone has the status "not found"
  let { run, context = '' }: { run: PickRun; context?: string } = $props();
</script>

<span class="rl">
  <span class="top"
    ><span class="mono name">{run.name}</span><span class="mono sfx" title="Run id {run.id}">{idSuffix(run.id)}</span
    ></span
  >
  <span class="sub"
    ><span class="st {run.status}"><i></i>{cap(run.status)}</span>{#if run.started || run.created}<span class="sep"
        >·</span
      >{fmtDate(run.started ?? run.created)}{/if}</span
  >
  {#if context}<span class="ctx">← {context}</span>{/if}
  {#if run.tags?.length}<span class="tags"><TagPills tags={run.tags} max={4} /></span>{/if}
</span>

<style>
  .rl {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 1px;
    text-align: left;
  }
  .top {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }
  .name {
    font-size: 12.5px;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sfx {
    flex: none;
    margin-left: auto;
    font-size: 10.5px;
    color: var(--faint);
  }
  .sub {
    font-size: 11px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ctx {
    font-size: 11px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sep {
    margin: 0 5px;
  }
  .tags {
    display: flex;
    margin-top: 2px;
  }
  .st i {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 4px;
    vertical-align: 1px;
    background: var(--faint);
  }
  .st.finished i {
    background: var(--s4, var(--ok));
  }
  .st.running {
    color: var(--accent);
  }
  .st.running i {
    background: var(--accent);
  }
  .st.crashed,
  .st.killed {
    color: var(--err);
  }
  .st.crashed i,
  .st.killed i {
    background: var(--err);
  }
  .st.lost i {
    background: var(--warn);
  }
</style>
