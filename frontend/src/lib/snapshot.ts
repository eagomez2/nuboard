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

/** Load an inline SVG as an image, with its computed styles copied on, at its on-screen size. */
async function svgImage(svg: SVGSVGElement): Promise<{ img: HTMLImageElement; w: number; h: number }> {
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
    return { img, w: box.width, h: box.height };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Render an inline SVG to a PNG data URL.
 *
 * Styles come from CSS (often variables), which a standalone SVG image cannot see, so the
 * computed styles are copied onto a clone first.
 */
export async function svgToPng(svg: SVGSVGElement, title = ''): Promise<string> {
  const { img, w, h } = await svgImage(svg);
  return frame(svg, w, h, title, (ctx, top) => ctx.drawImage(img, 0, top, w, h));
}

/**
 * Render a chart and its HTML legend to a PNG data URL.
 *
 * `root` holds the chart's `.plot > svg` and a `.legend` of `<span>`s, each with an `<i>` swatch; the
 * legend is drawn under the chart, wrapped to its width, so the image says which line is which.
 */
export async function chartToPng(root: Element, title = ''): Promise<string> {
  const svg = root.querySelector<SVGSVGElement>('.plot > svg');
  if (!svg) throw new Error('no chart to save');
  const { img, w, h } = await svgImage(svg);
  const font = `11.5px ${cssVar(root, '--mono', 'monospace')}`;
  const measure = document.createElement('canvas').getContext('2d')!;
  measure.font = font;
  const items = [...root.querySelectorAll('.legend > span')].map((el) => {
    const swatch = el.querySelector('i');
    const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
    return {
      text,
      color: swatch ? getComputedStyle(swatch).backgroundColor : '#888',
      width: 14 + measure.measureText(text).width,
    };
  });
  // lay the items out in rows, as the page does
  const LINE = 18;
  let x = 12;
  let row = 0;
  const placed = items.map((it) => {
    if (x > 12 && x + it.width > w - 12) {
      x = 12;
      row++;
    }
    const at = { ...it, x, row };
    x += it.width + 14;
    return at;
  });
  const legendH = items.length ? (row + 1) * LINE + 8 : 0;
  return frame(svg, w, h + legendH, title, (ctx, top) => {
    ctx.drawImage(img, 0, top, w, h);
    ctx.font = font;
    ctx.textBaseline = 'middle';
    for (const it of placed) {
      const y = top + h + 4 + it.row * LINE + LINE / 2;
      ctx.fillStyle = it.color;
      ctx.fillRect(it.x, y - 1.5, 10, 3);
      ctx.fillStyle = cssVar(root, '--text', '#111');
      ctx.fillText(it.text, it.x + 14, y);
    }
  });
}
