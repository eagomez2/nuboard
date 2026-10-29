import { describe, expect, it } from 'vitest';
import { decimate, npyBytes, parseWaveform, Pyramid, signalFiles, waveformBundle } from '../src/lib/waveform';

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

  it('writes .npy files that NumPy reads: a 64-byte aligned header, then the values', () => {
    for (const n of [0, 3, 10_000_000]) {
      const npy = npyBytes(new Uint8Array(0), n);
      expect([...npy.subarray(0, 8)]).toEqual([0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59, 1, 0]);
      const len = npy[8] | (npy[9] << 8);
      expect((10 + len) % 64).toBe(0);
      const header = new TextDecoder().decode(npy.subarray(10, 10 + len));
      expect(header).toMatch(new RegExp(`^\\{'descr': '<f4', 'fortran_order': False, 'shape': \\(${n},\\), \\} *\\n$`));
    }
  });

  it('names signal files safely and uniquely, as the Python side does', () => {
    expect(signalFiles(['vad', 'a/b', 'A:B', 'VAD', '', 'a?b'])).toEqual([
      'signals/vad.npy',
      'signals/a_b.npy',
      'signals/A_B-2.npy',
      'signals/VAD-2.npy',
      'signals/signal.npy',
      'signals/a_b-3.npy',
    ]);
  });

  it('bundles the audio, one .npy per signal and metadata.json in a zip', () => {
    const audio = wav([0, 16384, -32768], 8000);
    const vad = new Float32Array([0.25, NaN, 1]);
    const gain = new Float32Array([-1, 0, 2]);
    const bytes = new Uint8Array(audio.byteLength + 24);
    bytes.set(new Uint8Array(audio));
    bytes.set(new Uint8Array(vad.buffer), audio.byteLength);
    bytes.set(new Uint8Array(gain.buffer), audio.byteLength + 12);
    const regions: Record<string, [number, number, string][]> = { target: [[0, 0.0002, 'speech']] };
    const { zip, metadata } = waveformBundle(bytes.buffer, {
      offset: audio.byteLength,
      names: ['speech/prob', 'gain'],
      samples: 3,
      range: [0, 1],
      caption: 'VAD',
      regions,
      run: { id: 'r1', name: 'base', project: 'p' },
      key: 'eval/vad',
      step: 12,
      exportedWith: 'nuboard 0.0.0',
    });

    // the stored members, read back from their local headers
    const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
    const files = new Map<string, Uint8Array>();
    for (let at = 0; view.getUint32(at, true) === 0x04034b50;) {
      const size = view.getUint32(at + 18, true);
      const nameLen = view.getUint16(at + 26, true);
      const name = new TextDecoder().decode(zip.subarray(at + 30, at + 30 + nameLen));
      files.set(name, zip.subarray(at + 30 + nameLen, at + 30 + nameLen + size));
      at += 30 + nameLen + size;
    }
    expect([...files.keys()]).toEqual(['audio.wav', 'signals/speech_prob.npy', 'signals/gain.npy', 'metadata.json']);
    expect([...files.get('audio.wav')!]).toEqual([...new Uint8Array(audio)]);
    const npy = files.get('signals/speech_prob.npy')!;
    const values = new Float32Array(npy.slice(npy.length - 12).buffer);
    expect(values[0]).toBe(0.25);
    expect(values[1]).toBeNaN();
    expect(values[2]).toBe(1);
    const meta = JSON.parse(new TextDecoder().decode(files.get('metadata.json')!));
    expect(meta).toEqual(metadata);
    expect(meta).toMatchObject({
      format: 'nuboard-waveform',
      format_version: 1,
      run: { id: 'r1', name: 'base', project: 'p' },
      key: 'eval/vad',
      step: 12,
      caption: 'VAD',
      audio: { file: 'audio.wav', sample_rate: 8000, channels: 1, samples: 3, duration: 0.000375 },
      range: [0, 1],
      regions,
      notes: [],
    });
    expect(meta.signals[0]).toEqual({
      name: 'speech/prob',
      file: 'signals/speech_prob.npy',
      dtype: 'float32',
      samples: 3,
    });
    // the end of the central directory counts the four members
    expect(view.getUint32(zip.length - 22, true)).toBe(0x06054b50);
    expect(view.getUint16(zip.length - 12, true)).toBe(4);
  });
});
