// PNG snapshots of what is on screen, for reports.

const STYLE_PROPS = [
  'fill',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-opacity',
  'stroke-dasharray',
  'opacity',
  'font-family',
  'font-size',
  'font-weight',
  'text-anchor',
  'dominant-baseline',
  'visibility',
  'display',
];

function cssVar(el: Element, name: string, fallback: string): string {
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback;
}

/** Draw `body` on a canvas with the panel background and an optional title above it. */
function frame(
  ref: Element,
  w: number,
  h: number,
  title: string,
  draw: (ctx: CanvasRenderingContext2D, top: number) => void,
): string {
  const scale = 2;
  const top = title ? 34 : 0;
  const out = document.createElement('canvas');
  out.width = Math.round(w * scale);
  out.height = Math.round((h + top) * scale);
  const ctx = out.getContext('2d')!;
  ctx.scale(scale, scale);
  ctx.fillStyle = cssVar(ref, '--panel', '#fff');
  ctx.fillRect(0, 0, w, h + top);
  if (title) {
    ctx.fillStyle = cssVar(ref, '--text', '#111');
    ctx.font = `600 14px ${cssVar(ref, '--mono', 'monospace')}`;
    ctx.fillText(title, 12, 22);
  }
  draw(ctx, top);
  return out.toDataURL('image/png');
}

/**
 * Render an inline SVG to a PNG data URL.
 *
 * Styles come from CSS (often variables), which a standalone SVG image cannot see, so the
 * computed styles are copied onto a clone first.
 */
export async function svgToPng(svg: SVGSVGElement, title = ''): Promise<string> {
  const box = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const src = [svg, ...svg.querySelectorAll('*')];
  const dst = [clone, ...clone.querySelectorAll('*')];
  src.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const style = STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';');
    dst[i].setAttribute('style', style);
  });
  clone.querySelectorAll('title').forEach((t) => t.remove());
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(box.width));
  clone.setAttribute('height', String(box.height));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    await new Promise<void>((ok, fail) => {
      img.onload = () => ok();
      img.onerror = () => fail(new Error('could not render the SVG'));
      img.src = url;
    });
    return frame(svg, box.width, box.height, title, (ctx, top) => ctx.drawImage(img, 0, top, box.width, box.height));
  } finally {
    URL.revokeObjectURL(url);
  }
}
