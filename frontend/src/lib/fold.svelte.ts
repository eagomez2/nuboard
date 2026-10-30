import { prefs } from './router.svelte';

/**
 * A side list that folds into a thin bar (Reports, the Runs workspace), remembered per browser
 * under `key`. `[` toggles it when no text box has the focus.
 */
export class Fold {
  folded = $state(false);
  constructor(private key: string) {
    this.folded = prefs.get(key, false);
  }
  toggle = () => {
    this.folded = !this.folded;
    prefs.set(this.key, this.folded);
  };
  onkeydown = (e: KeyboardEvent) => {
    const t = e.target;
    const typing = t instanceof HTMLElement && (t.isContentEditable || !!t.closest('input, textarea, select'));
    if (e.key === '[' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      this.toggle();
    }
  };
}
