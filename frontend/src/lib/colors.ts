const VARS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
/** Marker shapes paired with colors so series stay distinguishable without color. */
export const SHAPES = ['circle', 'square', 'triangle', 'diamond', 'circle', 'square', 'triangle', 'diamond'] as const;

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function seriesColor(i: number): string {
  return cssVar(VARS[i % VARS.length]) || '#0072b2';
}

export function seriesVar(i: number): string {
  return `var(${VARS[i % VARS.length]})`;
}

export function withAlpha(color: string, alpha: number): string {
  if (color.startsWith('#') && color.length === 7) {
    const a = Math.round(alpha * 255)
      .toString(16)
      .padStart(2, '0');
    return color + a;
  }
  return `color-mix(in srgb, ${color} ${Math.round(alpha * 100)}%, transparent)`;
}

/** The style that tints a `.tagpill` with a series color picked from the tag's text, so a tag keeps its color. */
export function tagStyle(tag: string): string {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) | 0;
  return `--tc: var(${VARS[Math.abs(h) % VARS.length]})`;
}
