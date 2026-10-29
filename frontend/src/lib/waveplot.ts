// A waveform figure (`add_figure(key, nb.WaveformFigure(...))`), drawn the same way in the viewer
// (WaveformPlot.svelte) and in an HTML export of a report, with the rules in waveplot.css: what you
// see in the viewer is what the exported file shows.

import type uPlot from 'uplot';
import type { waveformKit } from './waveform';

type Kit = ReturnType<typeof waveformKit>;

/** A note on a section of the clip, added in the viewer (as on audio, in the run's annotations.json). */
export interface WaveformNote {
  id: string;
  start: number;
  end: number;
  text: string;
}

export interface WaveformInput {
  /** The item's bytes: the WAV, then `samples` float32 values per signal. */
  buffer: ArrayBuffer;
  /** Bytes of the WAV at the start of `buffer`. */
  offset: number;
  names: string[];
  /** The values at the bottom and top of the plot; -1 and 1 share the waveform's axis. */
  range: [number, number];
  samples: number;
  /** What the audio plays from: a blob URL in the viewer, a data URL in an export. */
  audioSrc: string;
  caption?: string | null;
  height?: number;
  /** Labelled regions logged with the figure, `[start, end, label]` in seconds, by track. */
  regions?: Record<string, [number, number, string][]> | null;
  notes?: WaveformNote[];
  /** Called with the new list when a note is added, edited or deleted; without it notes are read-only. */
  onnotes?: (notes: WaveformNote[]) => void;
  /** With it, a Download menu saves the audio (`<name>.wav`) and the data bundle (`<name>.zip`). */
  download?: WaveformDownload;
}

/** What the Download menu names the files after and writes in the bundle's metadata.json. */
export interface WaveformDownload {
  /** File name without the extension, such as `<run>-<key>-<step>`. */
  name: string;
  run: { id: string; name: string; project: string | null };
  key: string;
  step: number;
  /** Such as `nuboard 0.18.0`. */
  exportedWith: string;
}

/**
 * Draw a waveform figure in `box`: the samples with each signal over them, accurate at every zoom
 * (M4, see lib/waveform.ts), with the values at a sample under the pointer, the region tracks logged
 * with it in lanes under the plot, and the notes added in the viewer in a lane above it. Dragging
 * selects a section, to zoom to, loop or note; − / + / Fit, Ctrl/⌘ + wheel and double-click zoom,
 * Shift + wheel scrolls, the overview moves the view, and the play button plays from where the plot
 * was clicked (or the selection). It uses nothing from outside itself, so an export embeds it as
 * text (`mountWaveform.toString()`).
 */
export function mountWaveform(
  box: HTMLElement,
  kit: Kit,
  UPlot: typeof uPlot,
  input: WaveformInput,
): { restyle: () => void; setNotes: (notes: WaveformNote[]) => void; destroy: () => void } {
  const data = kit.parseWaveform(input.buffer, input.offset, input.names, input.samples);
  const values = [...data.channels, ...data.signals];
  const pyramids = values.map((v) => new kit.Pyramid(v));
  const rate = data.sampleRate;
  const duration = data.channels[0].length / rate;
  const nch = data.channels.length;
  const labels = [...(nch > 1 ? data.channels.map((_, c) => `ch ${c + 1}`) : ['audio']), ...input.names];
  const own = input.range[0] !== -1 || input.range[1] !== 1;
  const height = input.height ?? 240;
  // the plot's height: `height`, or what the window leaves it in full screen
  let plotHeight = height;
  let full = false;
  const tracks = Object.entries(input.regions ?? {});
  const editable = !!input.onnotes;
  let notes: WaveformNote[] = [];
  let view: [number, number] = [0, duration];
  let sel: [number, number] | null = null;
  let looping = false;
  let hoverT: number | null = null;
  let plot: uPlot | null = null;
  let frame = 0;
  let dots: HTMLElement[] = [];
  let editing: string | null = null;

  // the widget: toolbar, note form, notes lane, plot, region lanes, overview, legend and caption, and
  // the audio it plays
  const el = (tag: string, cls?: string, text?: string) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const icon = (cls: string, d: string) =>
    `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
  const button = (parent: HTMLElement, text: string, label: string, onclick: () => void) => {
    const b = el('button', '', text) as HTMLButtonElement;
    b.type = 'button';
    if (text !== label) b.setAttribute('aria-label', label);
    b.title = label;
    b.addEventListener('click', onclick);
    parent.appendChild(b);
    return b;
  };
  const root = el('div', 'nbwf');
  const bar = el('div', 'nbwf-bar');
  const play = el('button', 'nbwf-play') as HTMLButtonElement;
  play.type = 'button';
  play.setAttribute('aria-label', 'Play');
  play.title = 'Play / pause (click the plot to set where, or select a section; Space in full screen)';
  play.innerHTML = icon('nbwf-go', 'M8 5.5v13l10.5-6.5z') + icon('nbwf-pause', 'M7 5h3.5v14H7zM13.5 5H17v14h-3.5z');
  const time = el('span', 'nbwf-time');
  const read = el('span', 'nbwf-read');
  const selBox = el('span', 'nbwf-sel nbwf-zoom');
  const selText = el('span', 'nbwf-seltext');
  const zoomBox = el('span', 'nbwf-zoom nbwf-view');
  const form = el('form', 'nbwf-form') as HTMLFormElement;
  const formTime = el('span', 'nbwf-seltext');
  const noteText = el('input') as HTMLInputElement;
  noteText.type = 'text';
  noteText.placeholder = 'Note for this section (Enter to save, Esc to cancel)';
  noteText.setAttribute('aria-label', 'Note text');
  const notesLane = el('div', 'nbwf-notes');
  const plotEl = el('div', 'nbwf-plot');
  const lanes = el('canvas', 'nbwf-tracks') as HTMLCanvasElement;
  lanes.setAttribute('aria-label', `Regions: ${tracks.map(([name]) => name).join(', ')}`);
  const overview = el('canvas', 'nbwf-overview') as HTMLCanvasElement;
  overview.setAttribute('aria-label', 'Overview of the clip; drag to move the view');
  const cap = el('div', 'nbwf-cap');
  const audio = el('audio') as HTMLAudioElement;
  audio.preload = 'auto';
  audio.hidden = true;
  audio.src = input.audioSrc;
  bar.append(play, time, read, selBox, zoomBox);
  root.append(bar, form, notesLane, plotEl);
  if (tracks.length) root.append(lanes);
  root.append(overview, cap, audio);
  box.replaceChildren(root);

  const css = (name: string) => getComputedStyle(root).getPropertyValue(name).trim();
  const alpha = (color: string, a: string) => (/^#[0-9a-f]{6}$/i.test(color) ? color + a : color);
  const seriesVar = (k: number) => (k < nch ? 'var(--muted)' : `var(--s${((k - nch + 1) % 8) + 1})`);
  // the labels' colors: picked from each label's text among the colors no signal uses, so a label
  // keeps its color in every lane, run and step, and two labels of the figure never share one
  const hash = (text: string) => {
    let h = 0;
    for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
    return Math.abs(h);
  };
  const free = [1, 2, 3, 4, 5, 6, 7, 8].filter((c) => !input.names.some((_, k) => ((k + 1) % 8) + 1 === c));
  const labelColor = new Map<string, number>();
  const classes = [...new Set(tracks.flatMap(([, segs]) => segs.map((g) => g[2])))];
  for (const label of [...classes].sort((a, b) => hash(a) - hash(b) || (a < b ? -1 : 1))) {
    const taken = new Set(labelColor.values());
    let c = hash(label) % free.length;
    for (let k = 0; k < free.length && taken.has(free[c]); k++) c = (c + 1) % free.length;
    labelColor.set(label, free[c]);
  }
  const labelVar = (label: string) => `--s${labelColor.get(label) ?? 1}`;
  const swatch = (color: string) => {
    const i = el('i', 'nbwf-sw');
    i.style.background = color;
    return i;
  };
  const clock = (t: number, digits: number) => {
    const m = Math.floor(t / 60 + 1e-9);
    const s = Math.max(0, t - m * 60)
      .toFixed(digits)
      .padStart(digits ? digits + 3 : 2, '0');
    return `${m}:${s}`;
  };
  const tick = (t: number, step: number) => clock(t, Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9))));
  const value = (v: number) => {
    if (!Number.isFinite(v)) return '–';
    const a = Math.abs(v);
    return a !== 0 && (a < 1e-3 || a >= 1e5) ? v.toExponential(3) : String(Number(v.toPrecision(5)));
  };
  /** The segment of a track at time `t`, if any (segments are in time order). */
  const segmentAt = (segments: [number, number, string][], t: number) => {
    let lo = 0;
    let hi = segments.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (segments[mid][1] <= t) lo = mid + 1;
      else hi = mid - 1;
    }
    for (let k = lo; k < segments.length && segments[k][0] <= t; k++) if (segments[k][1] > t) return segments[k];
    return null;
  };
  // each track's rows: one row of all its segments, or, when they overlap (labels that can be on at
  // once), one row per label, as in a piano roll
  type Segment = [number, number, string];
  const trackRows = tracks.map(([name, segments]) => {
    let end = -Infinity;
    let overlap = false;
    for (const g of segments) {
      if (g[0] < end - 1e-9) overlap = true;
      end = Math.max(end, g[1]);
    }
    if (!overlap) return { name, rows: [segments] };
    const byLabel = new Map<string, Segment[]>();
    for (const g of segments) byLabel.set(g[2], [...(byLabel.get(g[2]) ?? []), g]);
    return { name, rows: [...byLabel.values()] };
  });
  /** The segments of a track at time `t`, one per row at most. */
  const activeAt = (rows: Segment[][], t: number) => rows.map((r) => segmentAt(r, t)).filter((g): g is Segment => !!g);
  const showTime = () => (time.textContent = `${clock(audio.currentTime, 3)} / ${clock(duration, 3)}`);
  const hint = () =>
    read.replaceChildren(
      el(
        'span',
        'nbwf-hint',
        `Drag to select${editable ? ' and note' : ''} · Ctrl/⌘ + wheel zooms · Shift + wheel scrolls · double-click shows all`,
      ),
    );
  /** Horizontal position in the plot element of time `t`, in CSS pixels. */
  const xOf = (t: number) => (plot ? plot.bbox.left / devicePixelRatio + plot.valToPos(t, 'x') : 0);

  // the legend (signals, then the labels of the regions) and the caption, with the clip's length and rate
  input.names.forEach((name, k) => {
    const s = el('span', 'nbwf-sig');
    s.append(swatch(seriesVar(nch + k)), name);
    cap.append(s);
  });
  classes.forEach((label) => {
    const s = el('span', 'nbwf-sig');
    s.append(swatch(`var(${labelVar(label)})`), label);
    cap.append(s);
  });
  cap.append([input.caption, `${duration.toFixed(2)} s`, `${rate / 1000} kHz`].filter(Boolean).join(' · '));

  const viewData = (u: uPlot | null): uPlot.AlignedData => {
    const columns = Math.max(64, Math.round(u ? u.bbox.width : plotEl.clientWidth * devicePixelRatio));
    const [x, ...ys] = kit.decimate(pyramids, view[0] * rate - 1, view[1] * rate + 2, columns);
    return [(x as number[]).map((i) => i / rate), ...ys] as uPlot.AlignedData;
  };

  // the whole clip under the plot, with the part in view highlighted; its waveform is drawn once per
  // size and theme, then only the view box moves
  let overviewBase: HTMLCanvasElement | null = null;
  let overviewKey = '';
  const drawOverview = () => {
    if (!plot) return;
    const dpr = devicePixelRatio;
    const width = overview.clientWidth;
    const left = plot.bbox.left / dpr;
    const w = plot.bbox.width / dpr;
    const h = 28;
    const key = `${width} ${w} ${dpr} ${css('--text')}`;
    if (!overviewBase || key !== overviewKey) {
      overviewKey = key;
      overviewBase = document.createElement('canvas');
      overviewBase.width = Math.round(width * dpr);
      overviewBase.height = Math.round(h * dpr);
      const base = overviewBase.getContext('2d')!;
      base.scale(dpr, dpr);
      base.fillStyle = alpha(css('--text') || '#888888', '59');
      const columns = Math.max(1, Math.round(w * dpr));
      const n = data.channels[0].length;
      for (let c = 0; c < columns; c++) {
        const a = Math.floor((n * c) / columns);
        const b = Math.max(a + 1, Math.floor((n * (c + 1)) / columns));
        let lo = Infinity;
        let hi = -Infinity;
        for (let k = 0; k < nch; k++) {
          const [min, max] = pyramids[k].extent(a, b);
          if (min < lo) lo = min;
          if (max > hi) hi = max;
        }
        if (!(lo <= hi)) continue;
        base.fillRect(left + c / dpr, h / 2 - hi * (h / 2), 1 / dpr, Math.max(1 / dpr, (hi - lo) * (h / 2)));
      }
    }
    overview.width = overviewBase.width;
    overview.height = overviewBase.height;
    const ctx = overview.getContext('2d')!;
    ctx.drawImage(overviewBase, 0, 0);
    ctx.scale(dpr, dpr);
    const a = left + (view[0] / duration) * w;
    const b = left + (view[1] / duration) * w;
    const accent = css('--nbwf-accent');
    ctx.fillStyle = alpha(accent, '29');
    ctx.fillRect(a, 0, Math.max(2, b - a), h);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(a + 0.5, 0.5, Math.max(2, b - a) - 1, h - 1);
  };

  // the region tracks, one lane each under the plot (a row per label when labels overlap): the track's
  // name in the axis gutter, then its segments in the color of their label, named when there is room
  const LANE = 18;
  const drawLanes = () => {
    if (!plot || !tracks.length) return;
    const dpr = devicePixelRatio;
    const width = lanes.clientWidth;
    const h = trackRows.reduce((n, t) => n + t.rows.length, 0) * LANE + (trackRows.length - 1) * 4;
    lanes.width = Math.round(width * dpr);
    lanes.height = Math.round(h * dpr);
    lanes.style.height = `${h}px`;
    const ctx = lanes.getContext('2d')!;
    ctx.scale(dpr, dpr);
    const left = plot.bbox.left / dpr;
    const right = left + plot.bbox.width / dpr;
    ctx.font = `11px ${css('--nbwf-mono')}`;
    ctx.textBaseline = 'middle';
    let y = 0;
    for (const { name, rows } of trackRows) {
      ctx.fillStyle = css('--faint');
      ctx.textAlign = 'right';
      ctx.fillText(name, left - 6, y + LANE / 2, left - 8);
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, y, right - left, rows.length * LANE);
      ctx.clip();
      ctx.textAlign = 'left';
      for (const row of rows) {
        for (const [start, end, label] of row) {
          if (end < view[0] || start > view[1]) continue;
          const a = Math.max(left, xOf(start));
          const b = Math.min(right, xOf(end));
          const color = css(labelVar(label)) || '#888888';
          ctx.fillStyle = alpha(color, '4d');
          ctx.fillRect(a, y + 2, Math.max(1, b - a), LANE - 4);
          ctx.fillStyle = color;
          ctx.fillRect(a, y + 2, Math.min(2, Math.max(1, b - a)), LANE - 4);
          if (b - a > ctx.measureText(label).width + 10) {
            ctx.fillStyle = css('--text');
            ctx.fillText(label, a + 5, y + LANE / 2, b - a - 8);
          }
        }
        y += LANE;
      }
      ctx.restore();
      y += 4;
    }
    if (hoverT !== null && hoverT >= view[0] && hoverT <= view[1]) {
      ctx.fillStyle = css('--muted');
      ctx.fillRect(Math.round(xOf(hoverT)), 0, 1, h);
    }
  };

  // the notes: chips in rows above the plot (overlapping notes stack, extra ones share the last row)
  const NOTE_ROWS = 3;
  const NOTE_ROW = 20;
  const drawNotes = () => {
    notesLane.replaceChildren();
    notesLane.hidden = !notes.length;
    if (!plot || !notes.length) return;
    const ends: number[] = [];
    const left = plot.bbox.left / devicePixelRatio;
    const right = left + plot.bbox.width / devicePixelRatio;
    for (const n of [...notes].sort((a, b) => a.start - b.start || a.end - b.end)) {
      let row = ends.findIndex((end) => end <= n.start);
      if (row < 0) row = Math.min(ends.length, NOTE_ROWS - 1);
      ends[row] = Math.max(ends[row] ?? 0, n.end);
      const a = xOf(n.start);
      const b = Math.max(xOf(n.end), a + 14);
      if (b < left || a > right) continue;
      const chip = el('button', 'nbwf-note', n.text) as HTMLButtonElement;
      chip.type = 'button';
      chip.title = `${clock(n.start, 3)} – ${clock(n.end, 3)}  ${n.text}\nClick to select${editable ? ' (then Note to edit)' : ''}, double-click to zoom in`;
      chip.style.left = `${Math.max(left, a)}px`;
      chip.style.width = `${Math.min(right, b) - Math.max(left, a)}px`;
      chip.style.top = `${row * NOTE_ROW}px`;
      chip.classList.toggle('active', !!sel && Math.abs(sel[0] - n.start) < 1e-3 && Math.abs(sel[1] - n.end) < 1e-3);
      chip.addEventListener('click', () => select(n.start, n.end));
      chip.addEventListener('dblclick', () =>
        setView(n.start - (n.end - n.start) * 0.05, n.end + (n.end - n.start) * 0.05),
      );
      notesLane.appendChild(chip);
    }
    notesLane.style.height = `${Math.min(ends.length, NOTE_ROWS) * NOTE_ROW}px`;
  };

  // the selection, drawn as uPlot's selection box, kept in seconds so it follows the zoom
  const showSelection = () => {
    selBox.hidden = !sel;
    if (!plot) return;
    if (!sel) {
      plot.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
      return;
    }
    const a = Math.max(0, plot.valToPos(sel[0], 'x'));
    const b = Math.min(plot.bbox.width / devicePixelRatio, plot.valToPos(sel[1], 'x'));
    plot.setSelect({ left: a, top: 0, width: Math.max(0, b - a), height: plot.bbox.height / devicePixelRatio }, false);
    selText.textContent = `${sel[0].toFixed(3)} – ${sel[1].toFixed(3)} s (${(sel[1] - sel[0]).toFixed(3)} s)`;
  };
  const noteAtSelection = () =>
    sel ? notes.find((n) => Math.abs(sel![0] - n.start) < 1e-3 && Math.abs(sel![1] - n.end) < 1e-3) : undefined;
  const select = (a: number, b: number) => {
    sel = [Math.max(0, Math.min(a, b)), Math.min(duration, Math.max(a, b))];
    closeForm();
    showSelection();
    drawNotes();
  };
  const clearSelection = () => {
    sel = null;
    looping = false;
    loopButton.classList.remove('on');
    closeForm();
    showSelection();
    drawNotes();
  };

  // the note form, for the selection: a note on exactly that section opens for editing
  const openForm = () => {
    if (!sel || !editable) return;
    const note = noteAtSelection();
    editing = note ? note.id : null;
    noteText.value = note ? note.text : '';
    deleteButton.hidden = !note;
    saveButton.textContent = note ? 'Save' : 'Add';
    formTime.textContent = `${clock(sel[0], 3)} – ${clock(sel[1], 3)}`;
    form.hidden = false;
    noteText.focus();
  };
  const closeForm = () => {
    form.hidden = true;
    editing = null;
  };
  const save = (next: WaveformNote[]) => {
    notes = next;
    drawNotes();
    input.onnotes?.(next);
  };

  const refresh = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!plot) return;
      plot.setData(viewData(plot), false);
      plot.setScale('x', { min: view[0], max: view[1] });
      drawOverview();
    });
  };
  // the selection, the region lanes and the notes, placed by time with the plot's current scale
  const placeByTime = () => {
    showSelection();
    drawLanes();
    drawNotes();
  };
  const setView = (a: number, b: number) => {
    const span = Math.min(Math.max(b - a, Math.min(duration, 32 / rate)), duration);
    const start = Math.min(Math.max(a, 0), duration - span);
    view = Number.isFinite(start) ? [start, start + span] : [0, duration];
    refresh();
  };
  const zoom = (factor: number, at = (view[0] + view[1]) / 2) =>
    setView(at - (at - view[0]) * factor, at + (view[1] - at) * factor);

  const build = () => {
    plot?.destroy();
    const muted = css('--muted');
    const grid = css('--grid');
    const font = `11px ${css('--nbwf-mono')}`;
    const wave = alpha(css('--text') || '#888888', '88');
    const colors = labels.map((_, k) => (k < nch ? wave : css(`--s${((k - nch + 1) % 8) + 1}`) || '#e69f00'));
    const zoomedIn = (u: uPlot) => (u.scales.x.max! - u.scales.x.min!) * rate < u.bbox.width / devicePixelRatio / 6;
    const series: uPlot.Series[] = [{}];
    labels.forEach((label, k) =>
      series.push({
        label,
        scale: k >= nch && own ? 'v' : 'y',
        stroke: colors[k],
        width: k < nch ? 1 : 1.5,
        points: { show: zoomedIn, size: k < nch ? 4 : 5, fill: colors[k], stroke: colors[k] },
      }),
    );
    // the left axis is as wide as the region lanes' names need
    const measure = document.createElement('canvas').getContext('2d')!;
    measure.font = font;
    const gutter = Math.max(50, ...tracks.map(([name]) => Math.ceil(measure.measureText(name).width) + 14));
    const axis = (scale: string, side: number): uPlot.Axis => ({
      scale,
      side,
      stroke: muted,
      grid: { show: side === 3, stroke: grid, width: 1 },
      ticks: { show: false },
      size: side === 3 ? gutter : 50,
      font,
      values: (u, splits) => splits.map((v) => String(Number(v.toPrecision(3)))),
    });
    plot = new UPlot(
      {
        width: plotEl.clientWidth || 600,
        height: plotHeight,
        series,
        legend: { show: false },
        padding: [10, own ? 0 : 28, 0, 0],
        scales: {
          x: { time: false, auto: false, range: () => view },
          y: { auto: false, range: [-1, 1] },
          v: { auto: false, range: [input.range[0], input.range[1]] },
        },
        axes: [
          {
            stroke: muted,
            grid: { stroke: grid, width: 1 },
            ticks: { show: false },
            size: 32,
            space: 110,
            font,
            values: (u, splits, _axis, _space, step) => splits.map((v) => tick(v, step)),
          },
          axis('y', 3),
          ...(own ? [axis('v', 1)] : []),
        ],
        cursor: {
          y: false,
          drag: { x: true, y: false, setScale: false },
          points: { show: false },
          bind: {
            dblclick: () => () => {
              setView(0, duration);
              return null;
            },
            mouseup: (u, _target, handler) => (e: MouseEvent) => {
              // a click (not a drag) sets the playhead
              if (u.select.width === 0 && u.cursor.left !== undefined && u.cursor.left >= 0) {
                audio.currentTime = u.posToVal(u.cursor.left, 'x');
                showTime();
                u.redraw(false, false);
              }
              const out = handler(e);
              showSelection();
              return out;
            },
          },
        },
        hooks: {
          // what is placed by time, once uPlot has applied the new scale (it does so after setScale returns)
          setScale: [(u, key) => key === 'x' && placeByTime()],
          ready: [placeByTime],
          setSize: [placeByTime],
          setSelect: [
            (u) => {
              if (u.select.width > 4) {
                select(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x'));
                if (sel && (audio.currentTime < sel[0] || audio.currentTime > sel[1])) {
                  audio.currentTime = sel[0];
                  showTime();
                }
              }
            },
          ],
          setCursor: [
            (u) => {
              const left = u.cursor.left;
              if (left === undefined || left < 0) {
                hoverT = null;
                hint();
                for (const d of dots) d.style.display = 'none';
                u.redraw(false, false);
                drawLanes();
                return;
              }
              const i = Math.min(input.samples - 1, Math.max(0, Math.round(u.posToVal(left, 'x') * rate)));
              hoverT = i / rate;
              const span = view[1] - view[0];
              const digits = span < 0.02 ? 5 : span < 0.2 ? 4 : span < 5 ? 3 : 2;
              // the time and sample, each series' value at it (with a dot where its line goes through
              // it), and the label of each region track there
              const parts: Node[] = [el('span', 'nbwf-at', `${clock(hoverT, digits)} · #${i}`)];
              const x = u.valToPos(hoverT, 'x');
              labels.forEach((label, k) => {
                const v = el('span', 'nbwf-val');
                v.append(swatch(seriesVar(k)), `${label} `, el('b', '', value(values[k][i])));
                parts.push(v);
                const y = u.valToPos(values[k][i], k >= nch && own ? 'v' : 'y');
                const inside = Number.isFinite(y) && y >= 0 && y <= u.bbox.height / devicePixelRatio;
                dots[k].style.display = inside ? 'block' : 'none';
                dots[k].style.transform = `translate(${x}px, ${y}px)`;
              });
              for (const { name, rows } of trackRows) {
                const on = activeAt(rows, hoverT);
                const v = el('span', 'nbwf-val');
                v.append(...on.map((g) => swatch(`var(${labelVar(g[2])})`)), `${name} `);
                v.append(el('b', '', on.length ? on.map((g) => g[2]).join(', ') : '–'));
                parts.push(v);
              }
              read.replaceChildren(...parts);
              u.redraw(false, false);
              drawLanes();
            },
          ],
          draw: [
            (u) => {
              const ctx = u.ctx;
              const { left, top, width, height: h } = u.bbox;
              ctx.save();
              // the regions under the pointer, lightly shaded
              if (hoverT !== null) {
                for (const g of trackRows.flatMap(({ rows }) => activeAt(rows, hoverT!))) {
                  const a = Math.max(left, u.valToPos(g[0], 'x', true));
                  const b = Math.min(left + width, u.valToPos(g[1], 'x', true));
                  ctx.fillStyle = alpha(css(labelVar(g[2])) || '#888888', '14');
                  ctx.fillRect(a, top, b - a, h);
                }
              }
              // the zero line and the playhead
              ctx.fillStyle = alpha(muted, '59');
              ctx.fillRect(left, Math.round(u.valToPos(0, 'y', true)), width, devicePixelRatio);
              const px = Math.round(u.valToPos(audio.currentTime, 'x', true));
              if (audio.currentTime > 0 && px >= left && px <= left + width) {
                ctx.fillStyle = css('--nbwf-accent');
                ctx.fillRect(px, top, 1.5 * devicePixelRatio, h);
              }
              ctx.restore();
            },
          ],
        },
      },
      viewData(null),
      plotEl,
    );
    dots = colors.map((color) => {
      const dot = el('div', 'nbwf-dot');
      dot.style.background = color;
      plot!.over.appendChild(dot);
      return dot;
    });
    plot.over.addEventListener(
      'wheel',
      (e: WheelEvent) => {
        if (!plot) return;
        const span = view[1] - view[0];
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          zoom(Math.exp(e.deltaY * 0.0025), plot.posToVal(e.offsetX, 'x'));
        } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
          e.preventDefault();
          const d = (e.shiftKey ? e.deltaY || e.deltaX : e.deltaX) / (plot.bbox.width / devicePixelRatio);
          setView(view[0] + d * span, view[1] + d * span);
        }
      },
      { passive: false },
    );
    overviewBase = null;
    refresh();
  };

  // the selection's controls, the zoom buttons and the note form
  selBox.append(selText);
  const loopButton = button(selBox, 'Loop', 'Loop', () => {
    looping = !looping;
    loopButton.classList.toggle('on', looping);
  });
  // as in the audio player: the selection's Zoom in, next to − / + / Fit for the whole view
  button(selBox, 'Zoom in', 'Zoom in to the selection', () => {
    if (!sel) return;
    const pad = (sel[1] - sel[0]) * 0.05;
    setView(sel[0] - pad, sel[1] + pad);
  });
  if (editable) button(selBox, 'Note', 'Note', openForm);
  button(selBox, '×', 'Clear the selection', clearSelection);
  button(zoomBox, '−', 'Zoom out', () => zoom(2));
  button(zoomBox, '+', 'Zoom in', () => zoom(0.5));
  button(zoomBox, 'Fit', 'Fit', () => setView(0, duration));
  // the Download menu: the audio as logged, or the bundle of audio, signals and metadata
  const dl = input.download;
  let closeMenu = () => {};
  if (dl) {
    const wrap = el('span', 'nbwf-dl');
    const menu = el('span', 'nbwf-dl-menu');
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    const toggle = button(wrap, '', 'Download', () => setMenu(menu.hidden));
    toggle.classList.add('nbwf-icon-btn');
    toggle.setAttribute('aria-haspopup', 'menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.innerHTML = icon('nbwf-dlicon', 'M11 4h2v9.2l3.3-3.3 1.4 1.4-5.7 5.7-5.7-5.7 1.4-1.4 3.3 3.3zM5 18h14v2H5z');
    const setMenu = (open: boolean) => {
      menu.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      if (open) document.addEventListener('pointerdown', outside, true);
      else document.removeEventListener('pointerdown', outside, true);
    };
    const outside = (e: Event) => {
      if (!wrap.contains(e.target as Node)) setMenu(false);
    };
    closeMenu = () => setMenu(false);
    const saveFile = (bytes: Uint8Array<ArrayBuffer>, type: string, filename: string) => {
      const url = URL.createObjectURL(new Blob([bytes], { type }));
      const a = el('a') as HTMLAnchorElement;
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMenu(false);
    };
    const item = (text: string, title: string, onclick: () => void) => {
      const b = button(menu, text, text, onclick);
      b.setAttribute('role', 'menuitem');
      b.title = title;
    };
    item('Audio (.wav)', 'The audio as logged', () =>
      saveFile(new Uint8Array(input.buffer, 0, input.offset), 'audio/wav', `${dl.name}.wav`),
    );
    item('Data (.zip)', 'The audio, one .npy per signal and metadata.json', () => {
      const { zip } = kit.waveformBundle(input.buffer, {
        offset: input.offset,
        names: input.names,
        samples: input.samples,
        range: input.range,
        caption: input.caption,
        regions: input.regions,
        notes,
        run: dl.run,
        key: dl.key,
        step: dl.step,
        exportedWith: dl.exportedWith,
      });
      saveFile(zip, 'application/zip', `${dl.name}.zip`);
    });
    menu.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setMenu(false);
        toggle.focus();
      }
    });
    wrap.append(menu);
    zoomBox.append(wrap);
  }
  const fullButton = button(zoomBox, '', 'Full screen', () => setFull(!full));
  fullButton.classList.add('nbwf-full-btn');
  fullButton.setAttribute('aria-pressed', 'false');
  fullButton.innerHTML =
    icon('nbwf-expand', 'M5 5h5v2H7v3H5zm9 0h5v5h-2V7h-3zM5 14h2v3h3v2H5zm12 0h2v5h-5v-2h3z') +
    icon('nbwf-shrink', 'M8 5h2v5H5V8h3zm6 0h2v3h3v2h-5zM5 14h5v5H8v-3H5zm9 0h5v2h-3v3h-2z');
  form.append(formTime, noteText);
  const saveButton = el('button', '', 'Add') as HTMLButtonElement;
  saveButton.type = 'submit';
  form.append(saveButton);
  const deleteButton = button(form, 'Delete', 'Delete', () => {
    if (editing) save(notes.filter((n) => n.id !== editing));
    closeForm();
  });
  button(form, 'Cancel', 'Cancel', closeForm);
  form.hidden = true;
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = noteText.value.trim();
    if (!sel || !text) return;
    const id = editing || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    save([...notes.filter((n) => n.id !== id), { id, start: sel[0], end: sel[1], text }]);
    closeForm();
  });
  noteText.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeForm();
  });

  // the playhead follows the audio, a page at a time; a selection plays (or loops) on its own
  const follow = () => {
    let t = audio.currentTime;
    if (sel && !audio.paused && t >= sel[1]) {
      if (looping) audio.currentTime = t = sel[0];
      else audio.pause();
    }
    showTime();
    root.classList.toggle('playing', !audio.paused);
    play.setAttribute('aria-label', audio.paused ? 'Play' : 'Pause');
    if (!plot) return;
    const span = view[1] - view[0];
    if (!audio.paused && (t > view[1] || t < view[0]) && span < duration) setView(t, t + span);
    plot.redraw(false, false);
    if (!audio.paused) requestAnimationFrame(follow);
  };
  audio.addEventListener('play', follow);
  audio.addEventListener('pause', follow);
  audio.addEventListener('seeked', follow);
  const togglePlay = () => {
    if (!audio.paused) return audio.pause();
    if (sel && (audio.currentTime < sel[0] || audio.currentTime >= sel[1] - 1e-3)) audio.currentTime = sel[0];
    else if (audio.currentTime >= duration - 1e-3) audio.currentTime = 0;
    void audio.play();
  };
  play.addEventListener('click', togglePlay);

  // pressing or dragging on the overview centers the view there
  const onOverview = (e: PointerEvent) => {
    if (!plot || !(e.buttons & 1)) return;
    overview.setPointerCapture(e.pointerId);
    const t = ((e.offsetX - plot.bbox.left / devicePixelRatio) / (plot.bbox.width / devicePixelRatio)) * duration;
    const span = view[1] - view[0];
    setView(t - span / 2, t + span / 2);
  };
  overview.addEventListener('pointerdown', onOverview);
  overview.addEventListener('pointermove', onOverview);
  const resize = new ResizeObserver(() => {
    if (plot && plotEl.clientWidth && plotEl.clientWidth !== plot.width) {
      plot.setSize({ width: plotEl.clientWidth, height: plotHeight });
      refresh();
    }
  });
  // full screen, as in the audio player: the figure covers the window and its plot takes the height
  // the controls, lanes and overview leave; its place in the page is kept, so nothing moves under it
  const fitHeight = () => {
    if (!plot) return;
    // what the rest of the figure takes: its other parts, the gaps between them and its padding
    const style = getComputedStyle(root);
    const parts = [...root.children].filter((c) => c !== plotEl && (c as HTMLElement).offsetHeight > 0);
    const rest =
      parts.reduce((sum, c) => sum + (c as HTMLElement).offsetHeight, 0) +
      parts.length * (parseFloat(style.rowGap) || 0) +
      (parseFloat(style.paddingTop) || 0) +
      (parseFloat(style.paddingBottom) || 0);
    const next = full ? Math.max(height, Math.floor(window.innerHeight - rest - 4)) : height;
    if (next === plotHeight) return;
    plotHeight = next;
    plot.setSize({ width: plotEl.clientWidth, height: plotHeight });
    refresh();
  };
  const setFull = (on: boolean) => {
    if (on === full) return;
    full = on;
    box.style.minHeight = on ? `${box.offsetHeight}px` : '';
    root.classList.toggle('nbwf-full', on);
    fullButton.setAttribute('aria-label', on ? 'Exit full screen' : 'Full screen');
    fullButton.title = on ? 'Exit full screen (Esc)' : 'Full screen';
    fullButton.setAttribute('aria-pressed', String(on));
    if (on) window.addEventListener('resize', fitHeight);
    else window.removeEventListener('resize', fitHeight);
    // the plot's own height first, then what the window leaves it once the layout has settled
    plotHeight = -1;
    if (full) requestAnimationFrame(fitHeight);
    else fitHeight();
  };
  // In full screen only, a plain Space (no modifier, not typing) plays and pauses, as in the audio
  // player (audio/player.js). It is held back on key up too, or a focused button would be pressed.
  const typing = (t: EventTarget | null) =>
    t instanceof HTMLElement && (t.isContentEditable || !!t.closest('input, textarea, select'));
  const onKey = (e: KeyboardEvent) => {
    if (!full) return;
    if (e.type === 'keydown' && e.key === 'Escape') {
      e.stopPropagation();
      setFull(false);
    } else if (e.key === ' ' && !(e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) && !typing(e.target)) {
      e.preventDefault();
      e.stopPropagation();
      if (e.type === 'keydown' && !e.repeat) togglePlay();
    }
  };
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('keyup', onKey, true);
  resize.observe(plotEl);
  // new colors when the light/dark theme changes
  const theme = new MutationObserver(build);
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  notes = [...(input.notes ?? [])];
  selBox.hidden = true;
  showTime();
  hint();
  build();
  return {
    restyle: build,
    setNotes: (next) => {
      notes = [...next];
      drawNotes();
    },
    destroy: () => {
      audio.pause();
      closeMenu();
      window.removeEventListener('resize', fitHeight);
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('keyup', onKey, true);
      resize.disconnect();
      theme.disconnect();
      cancelAnimationFrame(frame);
      plot?.destroy();
      plot = null;
      box.replaceChildren();
    },
  };
}
