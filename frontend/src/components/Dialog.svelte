<script lang="ts">
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
        const first = el?.querySelector<HTMLInputElement>('input');
        if (first) first.select();
        else el?.querySelector<HTMLButtonElement>('button.confirm')?.focus();
      });
    } else if (el.open) {
      el.close();
    }
  });

  function submit(e: SubmitEvent) {
    e.preventDefault();
    dialog.close([...values]);
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
        <div class="field">
          <label class="label" for="nb-dialog-in-{i}">{f.label}</label>
          <input
            id="nb-dialog-in-{i}"
            class="input"
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
      {/each}
      <div class="actions">
        <button type="button" class="btn" onclick={() => dialog.close(null)}>Cancel</button>
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
