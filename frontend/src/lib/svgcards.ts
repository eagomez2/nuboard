/**
 * Hover cards on an SVG snapshot saved into a report (the Timeline): every element whose
 * `<title>` has several lines (name, id, status, ...) shows them as a card like the page's,
 * instead of the browser's slow plain tooltip. `export-hover.js` does the same in exported files.
 */

/** The lines of a multi-line title (older snapshots hold a literal `\n`), or null. */
export function cardLines(title: string): string[] | null {
  const lines = title.split(/\n|\\n/).filter((l) => l.trim());
  return lines.length > 1 ? lines : null;
}

/**
 * Turn the multi-line titles inside `box` into hover cards. `onopen` gets the `data-run` of a
 * clicked element. Returns a function that removes the listeners.
 */
export function svgCards(box: HTMLElement, onopen?: (run: string) => void): () => void {
  for (const t of box.querySelectorAll('title')) {
    const lines = cardLines(t.textContent ?? '');
    if (!lines || !t.parentElement) continue;
    t.parentElement.dataset.card = JSON.stringify(lines);
    if (onopen && t.parentElement.dataset.run) t.parentElement.style.cursor = 'pointer';
    t.remove();
  }
  box.style.position = 'relative';
  const tip = document.createElement('div');
  tip.className = 'nb-card';
  tip.hidden = true;
  tip.setAttribute('role', 'status');
  box.append(tip);
  const target = (e: Event) => (e.target as Element | null)?.closest?.<HTMLElement | SVGElement>('[data-card]');
  const move = (e: PointerEvent) => {
    const el = target(e);
    if (!el) return void (tip.hidden = true);
    const lines: string[] = JSON.parse(el.dataset.card ?? '[]');
    tip.replaceChildren(
      ...lines.map((text, i) => {
        const row = document.createElement('div');
        row.textContent = text;
        row.className = i === 0 ? 'head' : i === 1 ? 'faint' : text.startsWith('⚠') ? 'warn' : '';
        return row;
      }),
    );
    tip.hidden = false;
    const r = box.getBoundingClientRect();
    const x = e.clientX - r.left + box.scrollLeft;
    const y = e.clientY - r.top;
    const below = y < r.height * 0.6; // near the bottom, the card opens above the cursor
    tip.style.top = `${below ? y + 14 : y - 14}px`;
    tip.style.transform = below ? '' : 'translateY(-100%)';
    tip.style.left = x > r.width / 2 ? '' : `${x + 12}px`;
    tip.style.right = x > r.width / 2 ? `${r.width - x + 12}px` : '';
  };
  const leave = () => (tip.hidden = true);
  const click = (e: MouseEvent) => {
    const run = target(e)?.dataset.run;
    if (run && onopen) onopen(run);
  };
  box.addEventListener('pointermove', move);
  box.addEventListener('pointerleave', leave);
  box.addEventListener('click', click);
  return () => {
    box.removeEventListener('pointermove', move);
    box.removeEventListener('pointerleave', leave);
    box.removeEventListener('click', click);
    tip.remove();
  };
}
