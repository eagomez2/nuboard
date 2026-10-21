// Waveform figures (`add_figure(key, nb.WaveformFigure(...))`): the stored item is a 16-bit WAV followed by
// float32 signals, one value per sample. They are drawn with M4 decimation (Jugel et al., VLDB 2014):
// each pixel column keeps the first, smallest, largest and last value of its samples, which draws the
// same pixels as a line through every sample, at any zoom and for files of any length.

export interface WaveformData {
  sampleRate: number;
  /** Samples per channel, then signals, in order. */
  channels: Float32Array[];
  signals: Float32Array[];
}

/**
 * The parsing and decimation, in one closure that uses nothing from outside it, so an HTML export
 * can embed the same code as text (`waveformKit.toString()`).
 */
export function waveformKit() {
  /** Split a waveform item into its audio channels (as -1 to 1 floats) and its signals. */
  function parseWaveform(buffer: ArrayBuffer, offset: number, names: string[], samples: number): WaveformData {
    const view = new DataView(buffer, 0, offset);
    if (view.getUint32(0, false) !== 0x52494646 || view.getUint32(8, false) !== 0x57415645) {
      throw new Error('not a WAV file');
    }
    let pos = 12;
    let rate = 0;
    let count = 1;
    let bits = 16;
    let format = 1;
    while (pos + 8 <= offset) {
      const id = view.getUint32(pos, false);
      const size = view.getUint32(pos + 4, true);
      const body = pos + 8;
      if (id === 0x666d7420) {
        // "fmt "
        format = view.getUint16(body, true);
        count = view.getUint16(body + 2, true);
        rate = view.getUint32(body + 4, true);
        bits = view.getUint16(body + 14, true);
      } else if (id === 0x64617461) {
        // "data"
        const frames = Math.floor(Math.min(size, offset - body) / ((bits / 8) * count));
        const channels = Array.from({ length: count }, () => new Float32Array(frames));
        // typed arrays read the samples in bulk (little-endian, as every browser's platform is); they
        // need aligned bytes, so data at an odd offset is copied first
        const n = frames * count;
        const aligned = body % (bits / 8) === 0;
        const src = aligned ? buffer : buffer.slice(body, body + n * (bits / 8));
        const start = aligned ? body : 0;
        const pcm = format === 3 && bits === 32 ? new Float32Array(src, start, n) : new Int16Array(src, start, n);
        const scale = format === 3 && bits === 32 ? 1 : 1 / 32768;
        for (let c = 0; c < count; c++) {
          const out = channels[c];
          for (let i = 0, k = c; i < frames; i++, k += count) out[i] = pcm[k] * scale;
        }
        const signals = names.map((_, k) => {
          const from = offset + k * samples * 4;
          return from % 4 === 0
            ? new Float32Array(buffer, from, samples)
            : new Float32Array(buffer.slice(from, from + samples * 4));
        });
        return { sampleRate: rate, channels, signals };
      }
      pos = body + size + (size & 1);
    }
    throw new Error('the WAV file has no data');
  }

  /** Block sizes of the precomputed minimum and maximum. */
  const BLOCKS = [64, 4096, 262144];

  /** A series with the minimum and maximum of its blocks, so a range's extent costs little at any zoom. */
  class Pyramid {
    // NOTE: Declared only and assigned in the constructor: the build lowers class fields to a helper
    // outside the kit, which the export's copy would not have
    declare readonly levels: { size: number; lo: Float32Array; hi: Float32Array }[];
    declare readonly values: Float32Array;

    constructor(values: Float32Array) {
      this.levels = [];
      this.values = values;
      let prev: { size: number; lo: Float32Array; hi: Float32Array } | null = null;
      for (const size of BLOCKS) {
        if (values.length < size * 2) break;
        const n = Math.ceil(values.length / size);
        const lo = new Float32Array(n).fill(NaN);
        const hi = new Float32Array(n).fill(NaN);
        for (let b = 0; b < n; b++) {
          let min = Infinity;
          let max = -Infinity;
          if (prev) {
            // from the level below: `size / prev.size` of its blocks
            const per = size / prev.size;
            for (let k = b * per; k < Math.min((b + 1) * per, prev.lo.length); k++) {
              if (prev.lo[k] < min) min = prev.lo[k];
              if (prev.hi[k] > max) max = prev.hi[k];
            }
          } else {
            for (let i = b * size; i < Math.min((b + 1) * size, values.length); i++) {
              const v = values[i];
              if (v < min) min = v;
              if (v > max) max = v;
            }
          }
          if (min <= max) {
            lo[b] = min;
            hi[b] = max;
          }
        }
        this.levels.push({ size, lo, hi });
        prev = this.levels[this.levels.length - 1];
      }
    }

    /** Smallest and largest finite value of samples [a, b), or NaN for none. */
    extent(a: number, b: number): [number, number] {
      let min = Infinity;
      let max = -Infinity;
      const scan = (from: number, to: number) => {
        for (let i = from; i < to; i++) {
          const v = this.values[i];
          if (v < min) min = v;
          if (v > max) max = v;
        }
      };
      // the coarsest level with at least two whole blocks inside the range, then the edges at finer levels
      let level = -1;
      for (let l = this.levels.length - 1; l >= 0; l--) {
        if (b - a >= this.levels[l].size * 2) {
          level = l;
          break;
        }
      }
      const span = (from: number, to: number, l: number) => {
        if (l < 0) return scan(from, to);
        const { size, lo, hi } = this.levels[l];
        const b0 = Math.ceil(from / size);
        const b1 = Math.floor(to / size);
        if (b1 <= b0) return span(from, to, l - 1);
        span(from, b0 * size, l - 1);
        for (let k = b0; k < b1; k++) {
          if (lo[k] < min) min = lo[k];
          if (hi[k] > max) max = hi[k];
        }
        span(b1 * size, to, l - 1);
      };
      span(a, b, level);
      return min <= max ? [min, max] : [NaN, NaN];
    }
  }

  /**
   * Samples [start, end) of every series as points with a shared x (sample positions): every sample
   * when there are few enough, else four points per bucket (first, min, max, last) for `buckets`
   * buckets. Non-finite values become null, which leaves a gap.
   */
  function decimate(series: Pyramid[], start: number, end: number, buckets: number): (number | null)[][] {
    const n = series.length ? series[0].values.length : 0;
    const a = Math.max(0, Math.floor(start));
    const b = Math.min(n, Math.ceil(end));
    const fin = (v: number) => (Number.isFinite(v) ? v : null);
    if (b <= a) return [[], ...series.map(() => [])];
    if (b - a <= buckets * 4) {
      const x: number[] = [];
      for (let i = a; i < b; i++) x.push(i);
      return [x, ...series.map((s) => x.map((i) => fin(s.values[i])))];
    }
    const x: number[] = [];
    const ys: (number | null)[][] = series.map(() => []);
    for (let k = 0; k < buckets; k++) {
      const s = a + Math.floor(((b - a) * k) / buckets);
      const e = a + Math.floor(((b - a) * (k + 1)) / buckets);
      const w = e - s;
      x.push(s, s + w / 3, s + (2 * w) / 3, e - 1);
      series.forEach((p, j) => {
        const [min, max] = p.extent(s, e);
        ys[j].push(fin(p.values[s]), fin(min), fin(max), fin(p.values[e - 1]));
      });
    }
    return [x, ...ys];
  }

  return { parseWaveform, Pyramid, decimate };
}

export const { parseWaveform, Pyramid, decimate } = waveformKit();
export type Pyramid = InstanceType<typeof Pyramid>;
