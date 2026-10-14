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
