<script lang="ts">
  import Icon from './Icon.svelte';
  import { keyFilter } from '../lib/keyfilter';

  /**
   * Pick one scalar out of many: a button that opens a searchable list (type to narrow, ↑ ↓ and
   * Enter to pick, Esc to close). Every screen that picks a scalar uses it, so hundreds of scalars
   * stay easy to find. Without `label` the button shows the picked scalar, like a menu; with it,
   * the button shows that text (such as "All 24"). With `pressed` too, the button is one choice of
   * a `.seg` group, on while `pressed` is true (as Charts' X axis "Scalar…").
   */
  let {
    metrics,
    value,
    onpick,
    label,
    none,
    disabled = false,
    size = 'md',
    ariaLabel = 'Scalar',
    title,
    pressed,
  }: {
    metrics: string[];
    value: string;
    onpick: (m: string) => void;
    /** Text of the button instead of the picked scalar. */
    label?: string;
    /** Label of an empty first choice (no scalar), such as "None". */
    none?: string;
    disabled?: boolean;
    size?: 'sm' | 'md';
    ariaLabel?: string;
    title?: string;
    /** Draw the button as a `.seg` choice that is on while this is true. */
    pressed?: boolean;
  } = $props();

  const LIMIT = 300;
  let open = $state(false);
  let find = $state('');
  let index = $state(0);
  let el = $state<HTMLElement>();
  let input = $state<HTMLInputElement>();

  // on open: focus the search box and bring the picked scalar into view
  $effect(() => {
    if (!open) return;
    input?.focus();
    requestAnimationFrame(() => el?.querySelector('.opt.on')?.scrollIntoView({ block: 'center' }));
  });

  // the empty choice (when offered) stays first while nothing is typed
  const list = $derived.by((): string[] => {
    const f = keyFilter(find);
    const all = value && !metrics.includes(value) ? [value, ...metrics] : metrics;
    const hits = (f.empty ? all : all.filter((m) => f.test(m))).slice(0, LIMIT);
    return none !== undefined && f.empty ? ['', ...hits] : hits;
  });

  function toggle() {
    open = !open;
    find = '';
    index = Math.max(0, list.indexOf(value));
  }
  function pick(m: string) {
    open = false;
    find = '';
    if (m !== value) onpick(m);
  }
  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = list.length;
      if (n) index = (index + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
      el?.querySelector(`[data-i="${index}"]`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && index < list.length) {
      e.preventDefault();
      pick(list[index]);
    } else if (e.key === 'Escape') {
      e.stopPropagation();
      open = false;
    }
  }
  $effect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!el?.contains(e.target as Node)) open = false;
    };
    window.addEventListener('pointerdown', close, true);
    return () => window.removeEventListener('pointerdown', close, true);
  });
</script>

<span class="picker" class:small={size === 'sm'} bind:this={el}>
  {#if label && pressed !== undefined}
    <button
      class="segpick"
      aria-pressed={pressed}
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label="{ariaLabel}: {value || 'none'}"
      title={title ?? value}
      {disabled}
      onclick={toggle}><span class="val" class:mono={pressed}>{label}</span><Icon name="chevron" size={12} /></button
    >
  {:else if label}
    <button class="btn btn-ghost sm" aria-expanded={open} aria-haspopup="dialog" {title} {disabled} onclick={toggle}
      ><Icon name="search" size={14} /> {label}</button
    >
  {:else}
    <button
      class="input mono trigger"
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label="{ariaLabel}: {value || none || 'none'}"
      title={title ?? value}
      {disabled}
      onclick={toggle}
      ><span class="val" class:faint={!value}>{value || none || '—'}</span><Icon name="chevron" size={13} /></button
    >
  {/if}
  {#if open}
    <div class="card pop" role="dialog" aria-label="Pick a scalar">
      <input
        class="input sm mono"
        placeholder="Filter {metrics.length} scalars (/regex/, !exclude)"
        aria-label="Search scalars"
        bind:this={input}
        bind:value={find}
        oninput={() => (index = 0)}
        {onkeydown}
      />
      <div class="list" role="listbox" aria-label="Scalars">
        {#each list as m, i (m)}
          <button
            class="opt mono"
            class:none={m === ''}
            role="option"
            data-i={i}
            aria-selected={i === index}
            class:on={m === value}
            title={m || none}
            onmouseenter={() => (index = i)}
            onclick={() => pick(m)}>{m || none}</button
          >
        {:else}
          <p class="faint small">No scalar matches “{find}”.</p>
        {/each}
      </div>
      {#if list.length >= LIMIT}<p class="faint small">Showing the first {LIMIT}; type to narrow.</p>{/if}
    </div>
  {/if}
</span>

<style>
  .picker {
    position: relative;
    display: inline-flex;
    min-width: 0;
  }
  .trigger {
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 240px;
    max-width: 100%;
    font-size: 12.5px;
    text-align: left;
    cursor: pointer;
  }
  .segpick {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    max-width: 220px;
  }
  .small .trigger {
    width: 200px;
    height: 30px;
  }
  .val {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .pop {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 30;
    width: 360px;
    max-width: calc(100vw - 32px);
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: var(--lift);
  }
  .list {
    max-height: 320px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .opt {
    border: 0;
    background: none;
    text-align: left;
    padding: 5px 8px;
    border-radius: 6px;
    font-size: 12.5px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: none;
  }
  .opt.none {
    font-family: var(--sans);
    color: var(--muted);
  }
  .opt[aria-selected='true'] {
    background: var(--panel-2);
  }
  .opt.on {
    color: var(--accent);
    font-weight: 600;
  }
  .faint {
    color: var(--faint);
  }
  .small p,
  .pop p {
    margin: 4px 8px;
    font-size: 12px;
  }
</style>
