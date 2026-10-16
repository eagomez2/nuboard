/** What `mountPoints` returns: the controls of one point cloud view. */
export interface PointsView {
  /** Back to the starting angle, zoom and position. */
  reset(): void;
  /** Redraw on another background (a CSS color), e.g. after a theme change. */
  setBackground(color: string): void;
  /** Stop listening to the canvas and its size. */
  destroy(): void;
}

/**
 * Draw a point cloud on a canvas you can rotate (drag), pan (shift-drag or
 * right-drag), zoom (wheel, once the view was clicked) and reset
 * (double-click).
 *
 * A small software renderer: each point is projected with a perspective
 * camera that orbits the cloud (z is up) and written into the canvas's pixels
 * with a depth buffer, so a million points draw in a few frames' time without
 * WebGL. Points are colored by `colors` or else by height.
 *
 * The function is self-contained (no imports and no names from outside it),
 * so the HTML export embeds it with `mountPoints.toString()`.
 *
 * @param canvas - The canvas to draw on; it is sized to its CSS box.
 * @param buffer - N x 3 little-endian float32 positions, then N x 3 RGB bytes
 *   when `hasColors`.
 * @param count - N, the number of points.
 * @param hasColors - Whether the buffer carries colors.
 * @param background - The background color, as CSS.
 */
export function mountPoints(
  canvas: HTMLCanvasElement,
  buffer: ArrayBuffer,
  count: number,
  hasColors: boolean,
  background: string,
): PointsView {
  const pos = new Float32Array(buffer, 0, count * 3);
  const rgb = hasColors ? new Uint8Array(buffer, count * 12, count * 3) : null;
  const ctx = canvas.getContext('2d')!;

  // Centered and scaled into the unit sphere
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < count * 3; i++) {
    const v = pos[i];
    if (!Number.isFinite(v)) continue;
    const a = i % 3;
    if (v < lo[a]) lo[a] = v;
    if (v > hi[a]) hi[a] = v;
  }
  const mid = [0, 1, 2].map((a) => (Number.isFinite(lo[a]) ? (lo[a] + hi[a]) / 2 : 0));
  let radius = 0;
  for (let i = 0; i < count; i++) {
    const dx = pos[i * 3] - mid[0];
    const dy = pos[i * 3 + 1] - mid[1];
    const dz = pos[i * 3 + 2] - mid[2];
    const r = dx * dx + dy * dy + dz * dz;
    if (r > radius) radius = r;
  }
  radius = Math.sqrt(radius) || 1;
  const xyz = new Float32Array(count * 3);
  for (let i = 0; i < count * 3; i++) xyz[i] = (pos[i] - mid[i % 3]) / radius;

  // Colors packed as ImageData words (little-endian ABGR)
  const VIRIDIS = [
    [68, 1, 84],
    [59, 82, 139],
    [33, 145, 140],
    [94, 201, 98],
    [253, 231, 37],
  ];
  const color = new Uint32Array(count);
  const zlo = lo[2];
  const zspan = hi[2] - lo[2] || 1;
  for (let i = 0; i < count; i++) {
    let r: number, g: number, b: number;
    if (rgb) {
      r = rgb[i * 3];
      g = rgb[i * 3 + 1];
      b = rgb[i * 3 + 2];
    } else {
      const t = Math.min(Math.max((pos[i * 3 + 2] - zlo) / zspan, 0), 1) * (VIRIDIS.length - 1);
      const k = Math.min(Math.floor(t), VIRIDIS.length - 2);
      const f = t - k;
      r = VIRIDIS[k][0] + (VIRIDIS[k + 1][0] - VIRIDIS[k][0]) * f;
      g = VIRIDIS[k][1] + (VIRIDIS[k + 1][1] - VIRIDIS[k][1]) * f;
      b = VIRIDIS[k][2] + (VIRIDIS[k + 1][2] - VIRIDIS[k][2]) * f;
    }
    color[i] = (255 << 24) | (Math.round(b) << 16) | (Math.round(g) << 8) | Math.round(r);
  }

  let bg = 0;
  function setBackground(css: string) {
    const probe = document.createElement('canvas').getContext('2d')!;
    probe.fillStyle = css;
    probe.fillRect(0, 0, 1, 1);
    const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
    bg = (255 << 24) | (b << 16) | (g << 8) | r;
    schedule(1);
  }

  // Camera: orbit angles, zoom and pan (in device pixels)
  const START = { yaw: -0.7, pitch: 0.45, zoom: 1, panX: 0, panY: 0 };
  let cam = { ...START };
  let image: ImageData | null = null;
  let depth = new Float32Array(0);
  let frame = 0;
  let pending = 1;

  function draw(stride: number) {
    const w = canvas.width;
    const h = canvas.height;
    if (!w || !h) return;
    if (!image || image.width !== w || image.height !== h) {
      image = ctx.createImageData(w, h);
      depth = new Float32Array(w * h);
    }
    const px = new Uint32Array(image.data.buffer);
    px.fill(bg);
    depth.fill(Infinity);
    const cy = Math.cos(cam.yaw);
    const sy = Math.sin(cam.yaw);
    const cp = Math.cos(cam.pitch);
    const sp = Math.sin(cam.pitch);
    const scale = Math.min(w, h) * 0.45 * cam.zoom;
    const ox = w / 2 + cam.panX;
    const oy = h / 2 + cam.panY;
    const dist = 3;
    const ratio = window.devicePixelRatio || 1;
    const size = Math.max(1, Math.round((count > 200000 ? 1 : count > 20000 ? 1.5 : 2.5) * ratio));
    for (let i = 0; i < count; i += stride) {
      const x = xyz[i * 3];
      const y = xyz[i * 3 + 1];
      const z = xyz[i * 3 + 2];
      const xr = x * cy - y * sy;
      const yr = x * sy + y * cy;
      const d = yr * cp - z * sp;
      const up = yr * sp + z * cp;
      const f = dist / (dist + d);
      if (!(f > 0)) continue;
      const sx = Math.round(ox + xr * scale * f - size / 2);
      const sy2 = Math.round(oy - up * scale * f - size / 2);
      for (let yy = sy2; yy < sy2 + size; yy++) {
        if (yy < 0 || yy >= h) continue;
        for (let xx = sx; xx < sx + size; xx++) {
          if (xx < 0 || xx >= w) continue;
          const j = yy * w + xx;
          if (d < depth[j]) {
            depth[j] = d;
            px[j] = color[i];
          }
        }
      }
    }
    ctx.putImageData(image, 0, 0);
  }

  function schedule(stride: number) {
    pending = frame ? Math.min(pending, stride) : stride;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      draw(pending);
    });
  }

  // While dragging, very large clouds draw a subset so rotation stays smooth
  const dragStride = Math.max(1, Math.ceil(count / 150000));
  let drag: { x: number; y: number; pan: boolean } | null = null;
  let engaged = false;
  let wheelTimer: ReturnType<typeof setTimeout> | undefined;
  const onDown = (e: PointerEvent) => {
    engaged = true;
    drag = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 };
    canvas.setPointerCapture(e.pointerId);
  };
  const onMove = (e: PointerEvent) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (drag.pan) {
      const ratio = window.devicePixelRatio || 1;
      cam.panX += dx * ratio;
      cam.panY += dy * ratio;
    } else {
      cam.yaw += dx * 0.01;
      cam.pitch = Math.min(Math.max(cam.pitch + dy * 0.01, -1.55), 1.55);
    }
    schedule(dragStride);
  };
  const onUp = () => {
    drag = null;
    schedule(1);
  };
  const onWheel = (e: WheelEvent) => {
    if (!engaged) return; // let the page scroll until the view is clicked
    e.preventDefault();
    cam.zoom = Math.min(Math.max(cam.zoom * Math.exp(-e.deltaY * 0.0015), 0.2), 40);
    schedule(dragStride);
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => schedule(1), 120);
  };
  const onLeave = () => (engaged = false);
  const reset = () => {
    cam = { ...START };
    schedule(1);
  };
  const noMenu = (e: Event) => e.preventDefault();
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointerleave', onLeave);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('dblclick', reset);
  canvas.addEventListener('contextmenu', noMenu);
  canvas.style.touchAction = 'none';
  canvas.style.cursor = 'grab';

  const resize = () => {
    const ratio = window.devicePixelRatio || 1;
    const w = Math.round(canvas.clientWidth * ratio);
    const h = Math.round(canvas.clientHeight * ratio);
    if (w === canvas.width && h === canvas.height) return;
    canvas.width = w;
    canvas.height = h;
    schedule(1);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  setBackground(background);

  return {
    reset,
    setBackground,
    destroy() {
      observer.disconnect();
      cancelAnimationFrame(frame);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('dblclick', reset);
      canvas.removeEventListener('contextmenu', noMenu);
    },
  };
}
