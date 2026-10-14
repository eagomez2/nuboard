// Themed replacements for prompt() and confirm(): one dialog at a time,
// rendered by components/Dialog.svelte and answered through a promise.

export interface DialogField {
  label: string;
  value?: string;
  placeholder?: string;
  hint?: string;
  suggestions?: string[];
}

export interface DialogRequest {
  title: string;
  message?: string;
  fields: DialogField[];
  confirm: string;
  danger?: boolean;
  resolve: (values: string[] | null) => void;
}

class DialogState {
  current = $state<DialogRequest | null>(null);

  close(values: string[] | null) {
    const req = this.current;
    this.current = null;
    req?.resolve(values);
  }
}

export const dialog = new DialogState();

function open(req: Omit<DialogRequest, 'resolve'>): Promise<string[] | null> {
  dialog.close(null); // a new dialog cancels any open one
  return new Promise((resolve) => {
    dialog.current = { ...req, resolve };
  });
}

/** Ask for one or more values; null when cancelled. */
export function ask(
  title: string,
  fields: DialogField[],
  opts: { message?: string; confirm?: string } = {},
): Promise<string[] | null> {
  return open({ title, fields, message: opts.message, confirm: opts.confirm ?? 'OK' });
}

/** Ask a yes/no question. */
export async function confirmAction(
  title: string,
  message: string,
  opts: { confirm?: string; danger?: boolean } = {},
): Promise<boolean> {
  const res = await open({ title, message, fields: [], confirm: opts.confirm ?? 'OK', danger: opts.danger });
  return res !== null;
}
