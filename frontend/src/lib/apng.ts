/** One composed frame of an animated PNG, ready to draw. */
export interface ApngFrame {
  image: ImageBitmap;
  /** How long it shows, in seconds. */
  delay: number;
}

/** An animated PNG decoded into composed frames. */
export interface Apng {
  width: number;
  height: number;
  frames: ApngFrame[];
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  view.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}

interface RawFrame {
  width: number;
  height: number;
  x: number;
  y: number;
  delay: number;
  dispose: number;
  blend: number;
  data: Uint8Array[];
}

const SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);

/**
 * Decode an animated PNG into frames composed as the format says (offsets,
 * dispose and blend operations), so a player can show any frame on its own.
 * Each frame is rebuilt as a still PNG and decoded by the browser. Null when
 * the bytes are not an animated PNG.
 */
export async function decodeApng(buf: ArrayBuffer): Promise<Apng | null> {
  const bytes = new Uint8Array(buf);
  const view = new DataView(buf);
  if (bytes.length < 8 || bytes.subarray(0, 8).some((b, i) => b !== SIGNATURE[i])) return null;
  let ihdr: Uint8Array | null = null;
  const shared: Uint8Array[] = []; // PLTE, tRNS, gAMA, ...: copied into every frame
  const frames: RawFrame[] = [];
  let animated = false;
  for (let p = 8; p + 8 <= bytes.length;) {
    const len = view.getUint32(p);
    const type = String.fromCharCode(...bytes.subarray(p + 4, p + 8));
    const data = bytes.subarray(p + 8, p + 8 + len);
    p += 12 + len;
    if (type === 'IHDR') ihdr = data;
    else if (type === 'acTL') animated = true;
    else if (type === 'fcTL') {
      const d = new DataView(data.buffer, data.byteOffset, data.byteLength);
      const den = d.getUint16(22) || 100;
      frames.push({
        width: d.getUint32(4),
        height: d.getUint32(8),
        x: d.getUint32(12),
        y: d.getUint32(16),
        delay: d.getUint16(20) / den,
        dispose: data[24],
        blend: data[25],
        data: [],
      });
    } else if (type === 'IDAT') {
      // the default image is a frame only when an fcTL comes before it
      if (frames.length) frames[frames.length - 1].data.push(data);
    } else if (type === 'fdAT') {
      frames[frames.length - 1]?.data.push(data.subarray(4));
    } else if (type === 'IEND') break;
    else if (!frames.length && type !== 'IDAT') shared.push(chunk(type, data));
  }
  if (!animated || !ihdr || !frames.length) return null;
  const width = new DataView(ihdr.buffer, ihdr.byteOffset).getUint32(0);
  const height = new DataView(ihdr.buffer, ihdr.byteOffset).getUint32(4);
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d')!;
  const out: ApngFrame[] = [];
  for (const f of frames) {
    const head = ihdr.slice();
    new DataView(head.buffer).setUint32(0, f.width);
    new DataView(head.buffer).setUint32(4, f.height);
    const parts = [
      SIGNATURE,
      chunk('IHDR', head),
      ...shared,
      ...f.data.map((d) => chunk('IDAT', d)),
      chunk('IEND', new Uint8Array()),
    ];
    const still = await createImageBitmap(new Blob(parts as BlobPart[], { type: 'image/png' }));
    const before = f.dispose === 2 ? ctx.getImageData(f.x, f.y, f.width, f.height) : null;
    if (f.blend === 0) ctx.clearRect(f.x, f.y, f.width, f.height);
    ctx.drawImage(still, f.x, f.y);
    still.close();
    out.push({ image: await createImageBitmap(canvas), delay: f.delay });
    if (f.dispose === 1) ctx.clearRect(f.x, f.y, f.width, f.height);
    else if (before) ctx.putImageData(before, f.x, f.y);
  }
  return { width, height, frames: out };
}
