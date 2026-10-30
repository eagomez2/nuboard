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

/** A copy of an inline SVG with its computed styles written on, so it draws the same on its own. */
function styledClone(svg: SVGSVGElement): SVGSVGElement {
  const box = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const src = [svg, ...svg.querySelectorAll('*')];
  const dst = [clone, ...clone.querySelectorAll('*')];
  src.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const style = STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';');
    dst[i].setAttribute('style', style);
  });
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(box.width));
  clone.setAttribute('height', String(box.height));
  return clone;
}

/**
 * Render an inline SVG to a standalone SVG data URL, with the panel background and a title.
 *
 * Elements with a `data-tip` get it as their `<title>`, which shows on hover wherever the SVG is
 * inlined (as in an exported report). Event handlers, classes and other attributes the page used
 * are dropped, so the file holds only the drawing.
 */
export async function svgToSvg(svg: SVGSVGElement, title = ''): Promise<string> {
  const clone = styledClone(svg);
  clone.querySelectorAll('title').forEach((t) => t.remove());
  for (const el of [clone, ...clone.querySelectorAll('*')]) {
    const tip = el.getAttribute('data-tip');
    for (const a of [...el.attributes])
      if (
        !/^(style|xmlns|width|height|viewBox|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|d|points|transform|text-anchor|fill|stroke|data-run)$/.test(
          a.name,
        )
      )
        el.removeAttribute(a.name);
    if (tip) {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      t.textContent = tip;
      el.prepend(t);
    }
  }
  const w = Number(clone.getAttribute('width'));
  const h = Number(clone.getAttribute('height'));
  const top = title ? 34 : 0;
  const NS = 'http://www.w3.org/2000/svg';
  const out = document.createElementNS(NS, 'svg');
  out.setAttribute('xmlns', NS);
  out.setAttribute('width', String(w));
  out.setAttribute('height', String(h + top));
  out.setAttribute('viewBox', `0 0 ${w} ${h + top}`);
  const bg = document.createElementNS(NS, 'rect');
  bg.setAttribute('width', '100%');
  bg.setAttribute('height', '100%');
  bg.setAttribute('fill', cssVar(svg, '--panel', '#fff'));
  out.append(bg);
  if (title) {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', '12');
    t.setAttribute('y', '22');
    t.setAttribute(
      'style',
      `fill:${cssVar(svg, '--text', '#111')};font:600 14px ${cssVar(svg, '--mono', 'monospace')}`,
    );
    t.textContent = title;
    out.append(t);
  }
  const body = document.createElementNS(NS, 'g');
  body.setAttribute('transform', `translate(0,${top})`);
  body.append(...clone.childNodes);
  out.append(body);
  const text = new XMLSerializer().serializeToString(out);
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return `data:image/svg+xml;base64,${btoa(bin)}`;
}

/** Load an inline SVG as an image, with its computed styles copied on, at its on-screen size. */
async function svgImage(svg: SVGSVGElement): Promise<{ img: HTMLImageElement; w: number; h: number }> {
  const box = svg.getBoundingClientRect();
  const clone = styledClone(svg);
  clone.querySelectorAll('title').forEach((t) => t.remove());
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
