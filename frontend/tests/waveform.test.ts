import { describe, expect, it } from 'vitest';
import { decimate, parseWaveform, Pyramid } from '../src/lib/waveform';

function wav(samples: number[], rate: number): ArrayBuffer {
  const out = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (at: number, s: string) => [...s].forEach((c, i) => out.setUint8(at + i, c.charCodeAt(0)));
  text(0, 'RIFF');
  out.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVEfmt ');
  out.setUint32(16, 16, true);
  out.setUint16(20, 1, true);
  out.setUint16(22, 1, true);
  out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true);
  out.setUint16(32, 2, true);
  out.setUint16(34, 16, true);
  text(36, 'data');
  out.setUint32(40, samples.length * 2, true);
  samples.forEach((v, i) => out.setInt16(44 + i * 2, v, true));
  return out.buffer;
}

describe('waveform', () => {
  it('splits a waveform item into its channels and signals', () => {
    const audio = wav([0, 16384, -32768], 8000);
    const signal = new Float32Array([0.25, 0.5, NaN]);
    const bytes = new Uint8Array(audio.byteLength + 12);
    bytes.set(new Uint8Array(audio));
    bytes.set(new Uint8Array(signal.buffer), audio.byteLength);
    const data = parseWaveform(bytes.buffer, audio.byteLength, ['vad'], 3);
    expect(data.sampleRate).toBe(8000);
    expect([...data.channels[0]]).toEqual([0, 0.5, -1]);
    expect([...data.signals[0]].slice(0, 2)).toEqual([0.25, 0.5]);
  });

  it('keeps the exact extent of any range, as a scan of every sample would', () => {
    const values = new Float32Array(300_000).map((_, i) => Math.sin(i * 0.37) * ((i % 9973) / 9973));
    values[123_457] = 5;
    values[200_001] = NaN;
    const p = new Pyramid(values);
    for (const [a, b] of [
      [0, 300_000],
      [1, 299_999],
      [123_000, 124_000],
      [70, 4300],
      [5, 9],
    ]) {
      let min = Infinity;
      let max = -Infinity;
      for (let i = a; i < b; i++) {
        if (values[i] < min) min = values[i];
        if (values[i] > max) max = values[i];
      }
      expect(p.extent(a, b)).toEqual([min, max]);
    }
  });

  it('draws every sample when zoomed in, and first, min, max and last per bucket when zoomed out', () => {
    const values = new Float32Array(10_000).map((_, i) => (i === 5003 ? -2 : Math.sin(i / 50)));
    const [x, y] = decimate([new Pyramid(values)], 100, 140, 100);
    expect(x).toEqual(Array.from({ length: 40 }, (_, i) => 100 + i));
    expect(y[3]).toBe(values[103]);

    const [bx, by] = decimate([new Pyramid(values)], 0, 10_000, 100);
    expect(bx.length).toBe(400);
    // the bucket of sample 5003 (5000 to 5100) keeps its minimum
    expect(by[50 * 4]).toBe(values[5000]);
    expect(by[50 * 4 + 1]).toBe(-2);
    expect(Math.min(...(by as number[]))).toBe(-2);
  });
});
