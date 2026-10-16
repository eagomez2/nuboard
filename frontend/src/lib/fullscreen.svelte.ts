// Full screen for one element (a chart, the timeline). The browser's Fullscreen API is used where
// allowed; the `.full` class (a fixed overlay) keeps it working where it is not, e.g. in an iframe.

export class FullScreen {
  on = $state(false);
  el: HTMLElement | undefined = $state();

  async toggle() {
    if (this.on) {
      this.on = false;
      if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
      return;
    }
    this.on = true;
    await this.el?.requestFullscreen?.().catch(() => {});
  }

  /** Follow the browser leaving full screen (Esc). Returns the cleanup for `onMount`. */
  listen(): () => void {
    const sync = () => {
      if (!document.fullscreenElement && this.on) this.on = false;
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && this.on) this.toggle();
    };
    document.addEventListener('fullscreenchange', sync);
    window.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      window.removeEventListener('keydown', key);
    };
  }
}
