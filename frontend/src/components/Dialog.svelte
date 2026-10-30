<script lang="ts">
  import ComboBox from './ComboBox.svelte';
  import { tagStyle } from '../lib/colors';
  import { dialog } from '../lib/dialog.svelte';

  let el = $state<HTMLDialogElement>();
  let values = $state<string[]>([]);
  const req = $derived(dialog.current);

  $effect(() => {
    if (!el) return;
    if (req) {
      values = req.fields.map((f) => f.value ?? '');
      if (!el.open) el.showModal();
      queueMicrotask(() => {
        const first = el?.querySelector<HTMLInputElement>('input.input');
        if (first) first.select();
        else el?.querySelector<HTMLButtonElement>('button.confirm')?.focus();
      });
    } else if (el.open) {
      el.close();
    }
  });

  const picked = (v: string) =>
    v
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  function togglePick(i: number, option: string, order: string[]) {
    const now = picked(values[i]);
    const next = now.includes(option) ? now.filter((o) => o !== option) : [...now, option];
    values[i] = next.sort((a, b) => order.indexOf(a) - order.indexOf(b)).join(', ');
  }

  function submit(e: SubmitEvent) {
    e.preventDefault();
    // a combo box left empty takes its preselected option
    dialog.close(values.map((v, i) => (!v.trim() && req?.fields[i]?.combo ? (req.fields[i].preselect ?? v) : v)));
  }
</script>

<dialog
  bind:this={el}
  class="card nb-dialog"
  aria-labelledby="nb-dialog-title"
  oncancel={(e) => {
    e.preventDefault();
    dialog.close(null);
  }}
  onclick={(e) => {
    if (e.target === el) dialog.close(null); // click on the backdrop
  }}
>
  {#if req}
    <form onsubmit={submit}>
      <h2 id="nb-dialog-title">{req.title}</h2>
      {#if req.message}<p class="msg">{req.message}</p>{/if}
      {#each req.fields as f, i (i)}
        {#if f.options && f.multiple}
          <div class="field" role="group" aria-labelledby="nb-dialog-label-{i}">
            <span class="label" id="nb-dialog-label-{i}">{f.label}</span>
            <div class="picks">
              {#each f.options as o (o.value)}
                <button
                  type="button"
                  class="tagpill"
                  style={tagStyle(o.value)}
                  aria-pressed={picked(values[i] ?? '').includes(o.value)}
                  onclick={() =>
                    togglePick(
                      i,
                      o.value,
                      f.options!.map((x) => x.value),
                    )}>{o.label}</button
                >
              {/each}
            </div>
            {#if f.hint}<span class="hint">{f.hint}</span>{/if}
          </div>
        {:else if f.options && f.options.length > 4}
          <div class="field">
            <label class="label" for="nb-dialog-in-{i}">{f.label}</label>
            <select
              id="nb-dialog-in-{i}"
              class="input"
              bind:value={values[i]}
              aria-describedby={f.hint ? `nb-dialog-hint-${i}` : undefined}
            >
              {#each f.options as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            </select>
            {#if f.hint}<span class="hint" id="nb-dialog-hint-{i}">{f.hint}</span>{/if}
          </div>
        {:else if f.options}
          <div class="field" role="group" aria-labelledby="nb-dialog-label-{i}">
            <span class="label" id="nb-dialog-label-{i}">{f.label}</span>
            <div class="seg">
              {#each f.options as o (o.value)}
                <button type="button" aria-pressed={values[i] === o.value} onclick={() => (values[i] = o.value)}
                  >{o.label}</button
                >
              {/each}
            </div>
            {#if f.hint}<span class="hint">{f.hint}</span>{/if}
          </div>
        {:else if f.toggle}
          <label class="field row">
            <button
              type="button"
              class="switch"
              role="switch"
              aria-checked={values[i] === '1'}
              aria-label={f.label}
              onclick={() => (values[i] = values[i] === '1' ? '0' : '1')}
            ></button>
            <span>{f.label}</span>
            {#if f.hint}<span class="hint">{f.hint}</span>{/if}
          </label>
        {:else if f.combo}
          <div class="field">
            <label class="label" for="nb-dialog-in-{i}">{f.label}</label>
            <ComboBox
              id="nb-dialog-in-{i}"
              bind:value={values[i]}
              options={f.combo}
              preselect={f.preselect}
              placeholder={f.placeholder}
              newLabel={f.newLabel}
              describedby={f.hint ? `nb-dialog-hint-${i}` : undefined}
            />
            {#if f.hint}<span class="hint" id="nb-dialog-hint-{i}">{f.hint}</span>{/if}
          </div>
        {:else}
          <div class="field">
            <label class="label" for="nb-dialog-in-{i}">{f.label}</label>
            <input
              id="nb-dialog-in-{i}"
              class="input"
              type={f.inputType ?? 'text'}
              bind:value={values[i]}
              placeholder={f.placeholder}
              list={f.suggestions?.length ? `nb-dialog-list-${i}` : undefined}
              aria-describedby={f.hint ? `nb-dialog-hint-${i}` : undefined}
              autocomplete="off"
              spellcheck="false"
            />
            {#if f.suggestions?.length}
              <datalist id="nb-dialog-list-{i}">
                {#each f.suggestions as s (s)}<option value={s}></option>{/each}
              </datalist>
            {/if}
            {#if f.hint}<span class="hint" id="nb-dialog-hint-{i}">{f.hint}</span>{/if}
          </div>
        {/if}
      {/each}
      <div class="actions">
        {#if !req.notice}<button type="button" class="btn" onclick={() => dialog.close(null)}>Cancel</button>{/if}
        <button type="submit" class="btn btn-primary confirm" class:danger={req.danger}>{req.confirm}</button>
      </div>
    </form>
  {/if}
</dialog>

<style>
  .nb-dialog {
    width: min(420px, calc(100vw - 32px));
    margin: auto; /* the CSS reset zeroes the native centering */
    padding: 0;
    color: var(--text);
    box-shadow:
      0 1px 2px rgba(16, 24, 40, 0.08),
      0 24px 48px -12px rgba(16, 24, 40, 0.35);
  }
  .nb-dialog::backdrop {
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
    letter-spacing: -0.01em;
  }
  .msg {
    margin: -6px 0 0;
    color: var(--muted);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  input::-webkit-calendar-picker-indicator {
    display: none !important; /* suggestions still open while typing */
  }
  .field.row {
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  .seg {
    align-self: flex-start;
  }
  .picks {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .hint {
    font-size: 12px;
    color: var(--faint);
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 4px;
  }
  .btn-primary.danger {
    background: var(--err);
    border-color: var(--err);
    color: #fff;
  }
</style>
