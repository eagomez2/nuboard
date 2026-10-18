// Text widths for sizing table columns to their content, without laying out every row.

let ctx: CanvasRenderingContext2D | null = null;
const cache = new Map<string, number>();
const families: Record<string, string> = {};

/** Bumped once the web fonts have loaded, so widths measured with a fallback font are redone. */
export const fonts = $state({ ready: 0 });

if (typeof document !== 'undefined' && document.fonts)
  document.fonts.ready.then(() => {
    cache.clear();
    fonts.ready++;
  });

/** The family of a CSS variable such as `--mono`, or the body font when it is not set. */
function family(mono: boolean): string {
  const k = mono ? 'mono' : 'body';
  families[k] ??=
    (mono
      ? getComputedStyle(document.documentElement).getPropertyValue('--mono')
      : getComputedStyle(document.body).fontFamily
    ).trim() || 'sans-serif';
  return families[k];
}

/**
 * Width in pixels of `text` drawn with `size` (px) and `weight`, in the mono or body font.
 *
 * Results are cached, so measuring thousands of rows stays cheap.
 */
export function textWidth(text: string, size: number, mono = false, weight = 400): number {
  if (!text) return 0;
  const key = `${mono ? 'm' : 's'}${weight}/${size}/${text}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  ctx ??= document.createElement('canvas').getContext('2d');
  if (!ctx) return text.length * size * 0.62;
  ctx.font = `${weight} ${size}px ${family(mono)}`;
  const w = Math.ceil(ctx.measureText(text).width);
  cache.set(key, w);
  return w;
}
