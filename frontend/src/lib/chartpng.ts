// Charts as PNG images: the focus chart's snapshot, and the small charts picked with Select items,
// drawn off screen at a fixed size so a chart on another page or in a folded section looks the same.

import { mount, tick, unmount, type ComponentProps } from 'svelte';
import LineChart from '../components/LineChart.svelte';
import type { ChartData } from './api';

export interface LegendItem {
  label: string;
  color: string;
}

/**
 * A chart's canvas with a title above it and a legend under it, as a PNG data URL.
 * Colors come from the CSS variables of `root`, so the image follows the page's theme.
 */
export function framePng(src: HTMLCanvasElement, root: Element, title: string, legend: LegendItem[]): string {
  const css = getComputedStyle(root);
  const dpr = src.width / Math.max(1, src.clientWidth);
  const perRow = Math.max(1, Math.floor(src.clientWidth / 220));
  const legendH = Math.ceil(legend.length / perRow) * 20 + 8;
  const out = document.createElement('canvas');
  out.width = src.width;
  out.height = src.height + (36 + legendH) * dpr;
  const ctx = out.getContext('2d')!;
  ctx.fillStyle = css.getPropertyValue('--panel').trim() || '#fff';
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.scale(dpr, dpr);
  ctx.fillStyle = css.getPropertyValue('--text').trim() || '#111';
  ctx.font = `600 14px ${css.getPropertyValue('--mono') || 'monospace'}`;
  ctx.fillText(title, 12, 22);
  ctx.drawImage(src, 0, 36, src.clientWidth, src.clientHeight);
  ctx.font = '12px system-ui, sans-serif';
  legend.forEach((x, i) => {
    const cx = 12 + (i % perRow) * 220;
    const cy = 36 + src.clientHeight + 16 + Math.floor(i / perRow) * 20;
    ctx.fillStyle = x.color;
    ctx.beginPath();
    ctx.arc(cx + 4, cy - 4, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = css.getPropertyValue('--muted').trim() || '#555';
    ctx.fillText(x.label.length > 30 ? x.label.slice(0, 29) + '…' : x.label, cx + 14, cy);
  });
  return out.toDataURL('image/png');
}

const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));

/** The props of a LineChart that a PNG of it takes from the page. */
export type ChartLook = Omit<ComponentProps<typeof LineChart>, 'data' | 'height' | 'compact'>;

/**
 * Draw `data` with LineChart in a hidden box `width` × `height` CSS pixels, and return it framed
 * with its title and legend (see `framePng`). The chart is mounted only for the drawing.
 */
export async function chartPng(
  data: ChartData,
  look: ChartLook,
  title: string,
  { width = 900, height = 340 } = {},
): Promise<string | null> {
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = `position:fixed;left:-20000px;top:0;width:${width}px;pointer-events:none;`;
  document.body.append(host);
  const chart = mount(LineChart, { target: host, props: { ...look, data, height, syncKey: 'png' } });
  try {
    await tick();
    // LineChart draws on the next frame, and again once its ResizeObserver has the box's width
    for (let i = 0; i < 60; i++) {
      await frame();
      const c = host.querySelector('canvas');
      if (c && Math.abs(c.clientWidth - width) <= 1 && i >= 2) break;
    }
    await frame();
    const src = host.querySelector('canvas');
    if (!src) return null;
    const hidden = look.hidden ?? new Set<string>();
    const legend = data.series
      .map((s, i) => ({ label: s.label, color: look.colorOf(s.label, i) }))
      .filter((x) => !hidden.has(x.label));
    return framePng(src, document.documentElement, title, legend);
  } finally {
    unmount(chart);
    host.remove();
  }
}
