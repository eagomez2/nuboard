// Pure helpers for the charts picked with Select items, kept free of Svelte so they can be tested.

/** File names for the PNGs of `metrics` in a .zip: slashes become `_`, repeats get `-2`, `-3`… */
export function chartFileNames(metrics: string[]): string[] {
  const seen = new Set<string>();
  return metrics.map((m) => {
    const base = m.replace(/[\\/:*?"<>|\s]+/g, '_').replace(/^_+|_+$/g, '') || 'chart';
    let name = `${base}.png`;
    for (let i = 2; seen.has(name.toLowerCase()); i++) name = `${base}-${i}.png`;
    seen.add(name.toLowerCase());
    return name;
  });
}

/** The bytes of a PNG data URL. */
export function pngBytes(dataUrl: string): Uint8Array {
  const bin = atob(dataUrl.slice(dataUrl.indexOf(',') + 1));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
