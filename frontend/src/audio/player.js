/*
 * Waveform + spectrogram player with zoom, scroll, selection and loop, built
 * on wavesurfer.js. Ported from Esteban Gómez's audioviewer player: it runs
 * in a same-origin iframe (`audio.html`) and talks to the viewer through
 * postMessage (`nb-audio:*` messages, see `AudioFrame.svelte`) instead of the
 * Streamlit component protocol. Notes are on when the viewer asks for them
 * (`args.notes`).
 *
 * Players of the same sample group can follow each other (zoom, scroll,
 * cursor and selection) through a BroadcastChannel, and starting one player
 * pauses every other one on the page.
 *
 * A note typed for the selection is sent back to Python as the component
 * value (`{start, end, text, id}`), which appends it to the file's notes.
 * The notes that carry timestamps come back as `annotations` and are shown
 * in a lane above the waveform; clicking one selects its section again.
 *
 * In NuBoard a note on exactly the selected section opens for editing (the
 * form then also offers Delete, sent as `nb-audio:note-delete`).
 *
 * The full screen button lays the component's frame over the whole app
 * window (like Streamlit's own full screen view of a chart) and stretches
 * the waveform and spectrogram to fill it, under a header with the file's
 * label, name and tags. Esc or the close button puts it back.
 */
(() => {
  'use strict';

  const WaveSurfer = window.WaveSurfer;
  const $ = (id) => document.getElementById(id);
  const el = {
    player: $('player'),
    play: $('play'),
    current: $('current'),
    duration: $('duration'),
    selection: $('selection'),
    selectionText: $('selection-text'),
    loop: $('loop'),
    zoomSelection: $('zoom-selection'),
    clearSelection: $('clear-selection'),
    annotate: $('annotate'),
    noteForm: $('note-form'),
    noteTime: $('note-time'),
    noteText: $('note-text'),
    noteCancel: $('note-cancel'),
    noteDelete: $('note-delete'),
    noteSubmit: $('note-submit'),
    rate: $('rate'),
    zoomOut: $('zoom-out'),
    zoom: $('zoom'),
    zoomIn: $('zoom-in'),
    fit: $('fit'),
    minimap: $('minimap'),
    ruler: $('ruler'),
    notesLane: $('notes-lane'),
    waveform: $('waveform'),
    message: $('message'),
    fullscreen: $('fullscreen'),
    fsHeader: $('fs-header'),
    fsTitle: $('fs-title'),
    fsClose: $('fs-close'),
  };

  //: Highest zoom level, in pixels per second
  const MAX_PX_PER_SEC = 8000;
  const ZOOM_STEPS = 1000;

  let args = null;
  let theme = null;
  let structure = '';
  let ws = null;
  let regions = null;
  let annotations = [];
  let editing = null; // id of the note open in the form, or null for a new one
  let selection = null;
  let looping = false;
  let ready = false;
  let visible = false;
  let pending = null;
  let quietUntil = 0;
  let fullscreen = false;
  //: Waveform and spectrogram heights (per channel) in full screen
  let fsLayout = null;
  const id = Math.random().toString(36).slice(2);
  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('nuboard-audio-player') : null;

  // -------------------------------------------------------------------------
  // Protocol with the viewer (same origin, see AudioFrame.svelte)
  // -------------------------------------------------------------------------
  const MESSAGE = {
    'streamlit:componentReady': 'nb-audio:ready',
    'streamlit:setFrameHeight': 'nb-audio:height',
    'streamlit:setComponentValue': 'nb-audio:note',
  };

  // NOTE: An HTML export sets `NB_AUDIO_EMBED` ({args, theme}) before this
  // script: there is no viewer to talk to, so the player renders those args
  // itself and sizes its frame directly (the frame is same-origin)
  const embed = window.NB_AUDIO_EMBED;

  function send(type, data) {
    if (embed) {
      if (type === 'streamlit:setFrameHeight' && window.frameElement) {
        window.frameElement.style.height = data.height + 'px';
      }

      return;
    }

    window.parent.postMessage({ type: MESSAGE[type] || type, ...data }, window.location.origin);
  }

  let lastHeight = -1;
  function updateHeight() {
    // NOTE: The frame keeps its height in the page while it covers the
    // window, so the page does not move underneath
    if (fullscreen) {
      scheduleLayout();
      return;
    }

    const height = Math.ceil(el.player.getBoundingClientRect().height) + 2;

    if (height !== lastHeight) {
      lastHeight = height;
      send('streamlit:setFrameHeight', { height: height });
    }
  }

  window.addEventListener('message', (event) => {
    if (event.source !== window.parent) return;

    if (event.data && event.data.type === 'nb-audio:render') {
      onRender(event.data.args, event.data.theme);
    }
  });
  new ResizeObserver(updateHeight).observe(el.player);
  send('streamlit:componentReady', { apiVersion: 1 });

  // -------------------------------------------------------------------------
  // Theme
  // -------------------------------------------------------------------------
  function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());

    if (!m) return null;

    const n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function rgba(hex, alpha) {
    const c = hexToRgb(hex) || [128, 128, 128];
    return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${alpha})`;
  }

  function mix(a, b, t) {
    return a.map((v, i) => v + (b[i] - v) * t);
  }

  function colors() {
    const t = theme || {};
    const dark = t.base === 'dark';
    const text = t.textColor || (dark ? '#ECE9E1' : '#1B1A17');
    const bg = t.backgroundColor || (dark ? '#161614' : '#FAF9F6');
    const primary = t.primaryColor || (dark ? '#2E8B80' : '#0F5F5A');
    // NOTE: The dark theme's primary is too dim for thin lines
    const accent = dark ? mix(hexToRgb(primary), [255, 255, 255], 0.3) : null;
    return {
      dark: dark,
      text: text,
      bg: bg,
      secondaryBg: t.secondaryBackgroundColor || (dark ? '#22211E' : '#F1EFE9'),
      primary: primary,
      accent: accent ? `rgb(${accent.map(Math.round).join(', ')})` : primary,
      wave: rgba(text, dark ? 0.42 : 0.38),
      muted: rgba(text, 0.6),
      border: rgba(text, dark ? 0.16 : 0.13),
      font: t.font || 'IBM Plex Sans, sans-serif',
    };
  }

  //: Spectrogram colormaps as color stops (low to high level). "theme" goes
  //: from the background to the text color through the accent, so the
  //: spectrogram reads like the rest of the app in both themes
  function colormapStops(name, c) {
    switch (name) {
      case 'viridis':
        return ['#440154', '#46327E', '#365C8D', '#277F8E', '#1FA187', '#4AC16D', '#A0DA39', '#FDE725'];
      case 'magma':
        return ['#000004', '#1C1044', '#4F127B', '#812581', '#B5367A', '#E55064', '#FB8761', '#FEC287', '#FCFDBF'];
      case 'gray':
        return c.dark ? [c.bg, '#FFFFFF'] : [c.bg, '#000000'];
      default: {
        // Background, through the accent, to the text color
        const bg = hexToRgb(c.bg) || [255, 255, 255];
        const primary = hexToRgb(c.primary) || [0, 114, 178];
        const text = hexToRgb(c.text) || [0, 0, 0];
        const hex = (v) => '#' + v.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
        // Quiet levels stay near the background so a noise floor reads as quiet
        return [
          hex(bg),
          hex(mix(bg, primary, 0.12)),
          hex(mix(bg, primary, 0.45)),
          hex(primary),
          hex(mix(primary, text, 0.55)),
          hex(text),
        ];
      }
    }
  }

  //: 256 RGBA entries, ready to be copied into an ImageData
  function colormapTable(name, c) {
    const rgb = colormapStops(name, c).map((h) => hexToRgb(h) || [128, 128, 128]);
    const table = new Uint8ClampedArray(256 * 4);

    for (let i = 0; i < 256; i++) {
      const x = (i / 255) * (rgb.length - 1);
      const k = Math.min(Math.floor(x), rgb.length - 2);
      const v = mix(rgb[k], rgb[k + 1], x - k);
      table.set([v[0], v[1], v[2], 255], i * 4);
    }

    return table;
  }

  function applyTheme() {
    const c = colors();
    const style = document.documentElement.style;
    style.setProperty('--text', c.text);
    style.setProperty('--bg', c.bg);
    style.setProperty('--secondary-bg', c.secondaryBg);
    style.setProperty('--primary', c.primary);
    style.setProperty('--accent', c.accent);
    style.setProperty('--muted', c.muted);
    style.setProperty('--border', c.border);
    style.setProperty('--note-bg', rgba(c.primary, c.dark ? 0.3 : 0.14));
    style.setProperty('--note-bg-hover', rgba(c.primary, c.dark ? 0.5 : 0.28));
    // Streamlit's green and violet badges and inline code (folder label,
    // tags and file name of the full screen header)
    // Badges of the full screen header: the run (accent) and the caption
    style.setProperty('--green-bg', rgba(c.primary, c.dark ? 0.22 : 0.12));
    style.setProperty('--green-text', c.accent);
    style.setProperty('--violet-bg', c.secondaryBg);
    style.setProperty('--violet-text', c.muted);
    style.setProperty('--code-bg', c.secondaryBg);
    style.setProperty('--font', c.font);
    style.setProperty('--font-mono', (theme && theme.fontMono) || 'ui-monospace, monospace');
    style.colorScheme = c.dark ? 'dark' : 'light';
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------
  function formatTime(seconds, digits) {
    const s = Math.max(0, seconds || 0);
    const m = Math.floor(s / 60);
    const rest = (s - m * 60).toFixed(digits === undefined ? 3 : digits);
    return `${m}:${rest.padStart(digits === 0 ? 2 : 3 + (digits ?? 3), '0')}`;
  }

  function showMessage(text, isError) {
    el.message.hidden = !text;
    el.message.textContent = text || '';
    el.message.classList.toggle('error', !!isError);
  }

  function fitPxPerSec() {
    const width = el.waveform.clientWidth || 600;
    const duration = (ws && ws.getDuration()) || args.duration || 1;
    return width / duration;
  }

  function currentPxPerSec() {
    const pps = ws ? ws.options.minPxPerSec : 0;
    return pps > 0 ? pps : fitPxPerSec();
  }

  function sliderToPxPerSec(value) {
    const fit = fitPxPerSec();
    const max = Math.max(fit, MAX_PX_PER_SEC);
    return fit * Math.pow(max / fit, value / ZOOM_STEPS);
  }

  function pxPerSecToSlider(pps) {
    const fit = fitPxPerSec();
    const max = Math.max(fit * 1.0001, MAX_PX_PER_SEC);
    const ratio = Math.log(Math.max(pps, fit) / fit) / Math.log(max / fit);
    return Math.round(Math.min(1, ratio) * ZOOM_STEPS);
  }

  function broadcast(message) {
    if (!channel) return;

    if (message.type !== 'play' && performance.now() < quietUntil) return;

    channel.postMessage({ ...message, id: id, group: args.group });
  }

  function linked(message) {
    return args && args.link && args.group && message.group === args.group && message.id !== id;
  }

  // -------------------------------------------------------------------------
  // Time ruler (drawn here rather than by the timeline plugin, so the labels
  // stay readable at every zoom level)
  // -------------------------------------------------------------------------
  const STEPS = [
    0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600,
  ];

  function rulerLabel(t, step) {
    const m = Math.floor(t / 60 + 1e-9);
    const s = t - m * 60;
    const digits = step >= 1 ? 0 : Math.ceil(-Math.log10(step) - 1e-9);
    const sec = Math.abs(s)
      .toFixed(digits)
      .padStart(digits ? 3 + digits : 2, '0');
    return `${m}:${sec}`;
  }

  function drawRuler() {
    if (!ws || !ready) return;

    const canvas = el.ruler;
    const width = el.waveform.clientWidth;
    const height = 18;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const c = colors();
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const pps = currentPxPerSec();
    const start = ws.getScroll() / pps;
    const end = start + width / pps;
    const step = STEPS.find((x) => x * pps >= 72) || STEPS[STEPS.length - 1];
    const minor = step / 5;
    ctx.font = `10.5px ${c.font}`;
    ctx.textBaseline = 'top';

    for (let i = Math.floor(start / minor); i * minor <= end; i++) {
      const x = Math.round((i * minor - start) * pps) + 0.5;
      const major = i % 5 === 0;
      ctx.fillStyle = major ? c.muted : c.border;
      ctx.fillRect(x - 0.5, 0, 1, major ? 18 : 5);

      if (major) ctx.fillText(rulerLabel(i * minor, step), x + 4, 2);
    }

    drawNotes();
  }

  // -------------------------------------------------------------------------
  // Notes lane
  // -------------------------------------------------------------------------
  //: Rows of the lane (overlapping notes stack, extra ones share the last)
  const NOTE_ROWS = 3;
  const NOTE_ROW_HEIGHT = 18;

  function setAnnotations(list) {
    annotations = (list || []).filter((a) => a.end >= a.start).sort((a, b) => a.start - b.start || a.end - b.end);

    // Rows are assigned in time (not pixels), so they stay put while
    // zooming
    const ends = [];

    for (const a of annotations) {
      let row = ends.findIndex((end) => end <= a.start);

      if (row < 0) row = Math.min(ends.length, NOTE_ROWS - 1);

      ends[row] = Math.max(ends[row] || 0, a.end);
      a.row = row;
    }

    const rows = Math.min(ends.length, NOTE_ROWS);
    el.notesLane.hidden = !annotations.length;
    el.notesLane.style.height = `${rows * NOTE_ROW_HEIGHT}px`;
    drawNotes();
    updateHeight();
  }

  function drawNotes() {
    el.notesLane.textContent = '';

    if (!ws || !ready || !annotations.length) return;

    const width = el.waveform.clientWidth;
    const pps = currentPxPerSec();
    const offset = ws.getScroll();

    for (const a of annotations) {
      const left = a.start * pps - offset;
      const span = Math.max((a.end - a.start) * pps, 8);

      if (left > width || left + span < 0) continue;

      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'note-chip';
      chip.textContent = a.text;
      chip.title =
        `${formatTime(a.start)} – ${formatTime(a.end)}  ${a.text}\n` +
        `Click to select${args.notes ? ' (then N to edit)' : ''}, double-click to zoom in`;
      chip.style.left = `${left}px`;
      chip.style.width = `${span}px`;
      chip.style.top = `${a.row * NOTE_ROW_HEIGHT}px`;

      chip.note = a;
      chip.addEventListener('click', () => selectRange(a.start, a.end));
      chip.addEventListener('dblclick', () => zoomToRange(a.start, a.end));
      el.notesLane.appendChild(chip);
    }

    markActiveNote();
  }

  // Highlights the note whose section is selected (without redrawing, so
  // a double-click lands on the same element as the click before it)
  function markActiveNote() {
    el.annotate.textContent = noteAtSelection() ? 'Edit note' : 'Note';

    for (const chip of el.notesLane.children) {
      const a = chip.note;
      chip.classList.toggle(
        'active',
        !!selection && Math.abs(selection.start - a.start) < 1e-3 && Math.abs(selection.end - a.end) < 1e-3,
      );
    }
  }

  // -------------------------------------------------------------------------
  // Spectrogram
  //
  // Computed once per file at a fixed hop (a quarter of the window) and
  // stored already mapped to the display rows, then drawn for the visible
  // part only. Zooming and scrolling just redraw what is on screen, so
  // their cost does not grow with the length of the file or the zoom level.
  // Zoomed out, each pixel column averages the frames it covers; zoomed in
  // past the hop, frames are interpolated.
  // -------------------------------------------------------------------------
  //: Levels mapped to the colormap, in dB relative to a full-scale sine.
  //: Fixed (not per file), so folders can be compared by eye.
  const DB_TOP = -10;
  const DB_RANGE = 90;
  //: Lowest frequency of the logarithmic scale
  const LOG_MIN_HZ = 20;

  let spec = null;
  let specBox = null;
  let specCanvas = null;
  let specToken = 0;
  let specFrame = 0;

  function fftTables(n) {
    const levels = Math.round(Math.log2(n));
    const reverse = new Uint32Array(n);

    for (let i = 0; i < n; i++) {
      let r = 0;

      for (let b = 0; b < levels; b++) r |= ((i >> b) & 1) << (levels - 1 - b);

      reverse[i] = r;
    }

    const cos = new Float32Array(n / 2);
    const sin = new Float32Array(n / 2);

    for (let i = 0; i < n / 2; i++) {
      cos[i] = Math.cos((2 * Math.PI * i) / n);
      sin[i] = Math.sin((2 * Math.PI * i) / n);
    }

    const window = new Float32Array(n);

    for (let i = 0; i < n; i++) {
      window[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / n);
    }

    return { n, reverse, cos, sin, window };
  }

  //: In-place radix-2 FFT
  function fft(re, im, t) {
    const n = t.n;

    for (let i = 0; i < n; i++) {
      const j = t.reverse[i];

      if (j > i) {
        let x = re[i];
        re[i] = re[j];
        re[j] = x;
        x = im[i];
        im[i] = im[j];
        im[j] = x;
      }
    }

    for (let size = 2; size <= n; size *= 2) {
      const half = size / 2;
      const step = n / size;

      for (let i = 0; i < n; i += size) {
        for (let j = i, k = 0; j < i + half; j++, k += step) {
          const l = j + half;
          const tre = re[l] * t.cos[k] + im[l] * t.sin[k];
          const tim = -re[l] * t.sin[k] + im[l] * t.cos[k];
          re[l] = re[j] - tre;
          im[l] = im[j] - tim;
          re[j] += tre;
          im[j] += tim;
        }
      }
    }
  }

  const toMel = (f) => 2595 * Math.log10(1 + f / 700);
  const fromMel = (m) => 700 * (Math.pow(10, m / 2595) - 1);

  //: Frequency at a relative height (0 = bottom, 1 = top) of the display
  function rowFrequency(y, fmax) {
    switch (args.scale) {
      case 'mel':
        return fromMel(toMel(fmax) * y);
      case 'logarithmic':
        return LOG_MIN_HZ * Math.pow(fmax / LOG_MIN_HZ, y);
      default:
        return fmax * y;
    }
  }

  //: Relative height of a frequency (inverse of `rowFrequency`)
  function frequencyRow(f, fmax) {
    switch (args.scale) {
      case 'mel':
        return toMel(f) / toMel(fmax);
      case 'logarithmic':
        return Math.log(f / LOG_MIN_HZ) / Math.log(fmax / LOG_MIN_HZ);
      default:
        return f / fmax;
    }
  }

  async function computeSpectrogram(buffer) {
    const token = ++specToken;
    const n = args.fftSize;
    const hop = n / 4;
    const rows = specHeight();
    const sampleRate = buffer.sampleRate;
    const fmax = sampleRate / 2;
    const frames = Math.ceil(buffer.length / hop) + 1;
    const t = fftTables(n);
    const re = new Float32Array(n);
    const im = new Float32Array(n);
    const rowMax = new Float64Array(rows);
    // Bins of each display row (every row gets at least one bin)
    const lo = new Int32Array(rows);
    const hi = new Int32Array(rows);

    for (let r = 0; r < rows; r++) {
      const f0 = rowFrequency(r / rows, fmax);
      const f1 = rowFrequency((r + 1) / rows, fmax);
      lo[r] = Math.min(n / 2, Math.round((f0 / sampleRate) * n));
      hi[r] = Math.max(lo[r], Math.min(n / 2, Math.round((f1 / sampleRate) * n) - 1));
    }

    // Power of a full-scale sine through the Hann window
    const ref = (n / 4) * (n / 4);
    const floor = DB_TOP - DB_RANGE;
    const out = [];
    let last = performance.now();

    for (let c = 0; c < buffer.numberOfChannels; c++) {
      const data = buffer.getChannelData(c);
      const values = new Uint8Array(frames * rows);

      for (let f = 0; f < frames; f++) {
        // Frames are centered on f * hop
        const start = f * hop - n / 2;

        for (let i = 0; i < n; i++) {
          const k = start + i;
          re[i] = k >= 0 && k < data.length ? data[k] * t.window[i] : 0;
          im[i] = 0;
        }

        fft(re, im, t);
        rowMax.fill(0);

        for (let r = 0; r < rows; r++) {
          let m = 0;

          for (let k = lo[r]; k <= hi[r]; k++) {
            const p = re[k] * re[k] + im[k] * im[k];

            if (p > m) m = p;
          }

          const db = 10 * Math.log10(m / ref + 1e-20);
          const v = ((db - floor) / DB_RANGE) * 255;
          values[f * rows + r] = v < 0 ? 0 : v > 255 ? 255 : v;
        }

        // Keep the page responsive while computing
        if (performance.now() - last > 30) {
          await new Promise((resolve) => setTimeout(resolve, 0));

          if (token !== specToken) return;

          last = performance.now();
        }
      }

      out.push(values);
    }

    spec = {
      channels: out,
      frames: frames,
      rows: rows,
      framesPerSec: sampleRate / hop,
      fmax: fmax,
      colormap: colormapTable(args.colormap, colors()),
    };
    el.player.dataset.spectrogram = 'true';
    requestSpectrogram();
  }

  function requestSpectrogram() {
    if (specFrame) return;

    specFrame = requestAnimationFrame(() => {
      specFrame = 0;
      drawSpectrogram();
    });
  }

  function drawSpectrogram() {
    if (!specCanvas || !ws) return;

    const width = Math.max(1, el.waveform.clientWidth);
    const rows = specHeight();
    const channels = Math.max(1, args.channels || 1);
    const height = rows * channels;
    specBox.style.width = `${width}px`;

    if (specCanvas.width !== width || specCanvas.height !== height) {
      specCanvas.width = width;
      specCanvas.height = height;
    }

    const ctx = specCanvas.getContext('2d');

    if (!spec) {
      ctx.clearRect(0, 0, width, height);
      return;
    }

    const image = ctx.createImageData(width, height);
    const pixels = image.data;
    const lut = spec.colormap;
    const pps = currentPxPerSec();
    const start = ws.getScroll() / pps;
    const fps = spec.framesPerSec;
    // NOTE: Computed for another height (full screen was just entered or
    // left, and the new one is on its way): stretch the stored rows
    const srcRows = spec.rows;
    const column = new Uint8Array(srcRows);
    const sums = new Float32Array(srcRows);
    const source = new Int32Array(rows);

    for (let r = 0; r < rows; r++) {
      source[r] = Math.min(srcRows - 1, Math.floor((r * srcRows) / rows));
    }

    for (let c = 0; c < spec.channels.length && c < channels; c++) {
      const values = spec.channels[c];

      for (let x = 0; x < width; x++) {
        const t0 = (start + x / pps) * fps;
        const t1 = (start + (x + 1) / pps) * fps;

        if (t0 >= spec.frames - 1) break;

        if (t1 - t0 >= 1) {
          // Several frames per pixel: their average
          const f0 = Math.max(0, Math.round(t0));
          const f1 = Math.min(spec.frames, Math.max(f0 + 1, Math.round(t1)));
          sums.fill(0);

          for (let f = f0; f < f1; f++) {
            const offset = f * srcRows;

            for (let r = 0; r < srcRows; r++) sums[r] += values[offset + r];
          }

          for (let r = 0; r < srcRows; r++) column[r] = sums[r] / (f1 - f0);
        } else {
          // Zoomed in past the hop: interpolate between frames
          const t = Math.max(0, (t0 + t1) / 2);
          const f = Math.min(Math.floor(t), spec.frames - 2);
          const w = t - f;
          const a = f * srcRows;
          const b = a + srcRows;

          for (let r = 0; r < srcRows; r++) {
            column[r] = values[a + r] * (1 - w) + values[b + r] * w;
          }
        }

        for (let r = 0; r < rows; r++) {
          const y = c * rows + (rows - 1 - r);
          const p = (y * width + x) * 4;
          const q = column[source[r]] * 4;
          pixels[p] = lut[q];
          pixels[p + 1] = lut[q + 1];
          pixels[p + 2] = lut[q + 2];
          pixels[p + 3] = 255;
        }
      }
    }

    ctx.putImageData(image, 0, 0);
    drawFrequencyLabels(ctx, rows, channels);
  }

  function drawFrequencyLabels(ctx, rows, channels) {
    const c = colors();
    const candidates = [100, 200, 500, 1000, 2000, 5000, 10000, 20000];
    ctx.font = `10px ${c.font}`;
    ctx.textBaseline = 'middle';

    for (let ch = 0; ch < channels; ch++) {
      let lastY = Infinity;

      for (const f of candidates) {
        if (f >= spec.fmax) break;

        const y = ch * rows + rows - frequencyRow(f, spec.fmax) * rows;

        if (y > (ch + 1) * rows - 8 || y < ch * rows + 8 || lastY - y < 22) {
          continue;
        }

        lastY = y;
        const label = f >= 1000 ? `${f / 1000} kHz` : `${f} Hz`;
        const w = ctx.measureText(label).width;
        ctx.fillStyle = rgba(c.bg, 0.7);
        ctx.fillRect(0, y - 7, w + 8, 14);
        ctx.fillStyle = c.text;
        ctx.fillText(label, 4, y + 0.5);
      }
    }
  }

  function createSpectrogram() {
    spec = null;
    specToken++;
    specBox = specCanvas = null;

    if (!(args.spectrogramHeight > 0)) return;

    const channels = Math.max(1, args.channels || 1);
    const height = specHeight();
    // NOTE: Inside wavesurfer's scrolled area so the cursor, hover line and
    // selection cover it and clicks/drags seek and select like on the
    // waveform; sticky so it stays in view while the waveform scrolls
    specBox = document.createElement('div');
    specBox.setAttribute('part', 'spectrogram');
    specBox.style.cssText =
      'position: sticky; left: 0; display: block; margin-top: 2px;' + `height: ${height * channels}px;`;
    specCanvas = document.createElement('canvas');
    specCanvas.style.cssText = 'display: block; width: 100%; height: 100%;';
    specBox.appendChild(specCanvas);
    ws.getWrapper().appendChild(specBox);
  }

  // -------------------------------------------------------------------------
  // Zoom and scroll
  // -------------------------------------------------------------------------
  function setZoom(pps, anchorTime, fromRemote) {
    if (!ws || !ready) return;

    const fit = fitPxPerSec();
    const target = Math.min(Math.max(pps, fit), Math.max(fit, MAX_PX_PER_SEC));
    const old = currentPxPerSec();
    const scroll = ws.getScroll();
    const anchor = anchorTime === undefined ? (scroll + el.waveform.clientWidth / 2) / old : anchorTime;
    const offset = anchor * old - scroll;

    // NOTE: 0 lets wavesurfer fill the width exactly (no scrollbar)
    ws.zoom(target <= fit * 1.001 ? 0 : target);
    ws.setScroll(Math.max(0, anchor * target - offset));
    el.zoom.value = pxPerSecToSlider(target);

    if (!fromRemote) {
      broadcast({ type: 'view', pps: target, start: ws.getScroll() / target });
    }
  }

  function zoomBy(factor, anchorTime) {
    setZoom(currentPxPerSec() * factor, anchorTime);
  }

  function zoomToRange(start, end) {
    const width = el.waveform.clientWidth || 600;
    const span = Math.max(end - start, 0.01);
    const pps = (width / span) * 0.9;
    setZoom(pps, start);
    const actual = currentPxPerSec();
    ws.setScroll(Math.max(0, (start - span * 0.05) * actual));
    broadcast({ type: 'view', pps: actual, start: ws.getScroll() / actual });
  }

  // -------------------------------------------------------------------------
  // Selection
  // -------------------------------------------------------------------------
  function setSelection(region, fromRemote) {
    selection = region;
    el.selection.hidden = !region;

    if (region) {
      const span = region.end - region.start;
      el.selectionText.textContent =
        `${region.start.toFixed(3)} – ${region.end.toFixed(3)} s ` + `(${span.toFixed(3)} s)`;
    } else {
      looping = false;
      el.loop.classList.remove('on');
      closeNoteForm();
    }

    markActiveNote();

    if (!fromRemote) {
      broadcast({
        type: 'select',
        start: region ? region.start : null,
        end: region ? region.end : null,
      });
    }

    updateHeight();
  }

  function applyRemoteSelection(start, end) {
    if (!regions) return;

    regions.clearRegions();

    if (start === null) {
      setSelection(null, true);
      return;
    }

    const region = regions.addRegion({
      start: start,
      end: end,
      color: rgba(colors().primary, colors().dark ? 0.28 : 0.16),
    });
    styleRegion(region);
    setSelection(region, true);
  }

  function styleRegion(region) {
    const handles = region.element ? region.element.querySelectorAll("[part~='region-handle']") : [];

    for (const handle of handles) {
      handle.style.borderColor = colors().accent;
    }
  }

  function selectRange(start, end) {
    if (!regions) return;

    regions.clearRegions();
    const region = regions.addRegion({
      start: start,
      end: end,
      color: rgba(colors().primary, colors().dark ? 0.28 : 0.16),
    });
    styleRegion(region);
    setSelection(region);
  }

  function clearSelection() {
    if (regions) regions.clearRegions();
    setSelection(null);
  }

  // -------------------------------------------------------------------------
  // Notes
  // -------------------------------------------------------------------------
  function noteAtSelection() {
    if (!selection) return null;

    return (
      annotations.find((a) => Math.abs(selection.start - a.start) < 1e-3 && Math.abs(selection.end - a.end) < 1e-3) ||
      null
    );
  }

  function openNoteForm() {
    if (!selection || !args.notes) return;

    const note = noteAtSelection();
    editing = note ? note.id : null;
    el.noteText.value = note ? note.text : '';
    el.noteDelete.hidden = !note;
    el.noteSubmit.textContent = note ? 'Save' : 'Add';
    el.noteTime.textContent = `${formatTime(selection.start)} – ${formatTime(selection.end)}`;
    el.noteForm.hidden = false;
    el.noteText.focus();
    updateHeight();
  }

  function closeNoteForm() {
    if (el.noteForm.hidden) return;

    el.noteForm.hidden = true;
    el.noteText.value = '';
    updateHeight();
  }

  function submitNote() {
    const text = el.noteText.value.trim();

    if (!selection || !text) return;

    send('streamlit:setComponentValue', {
      dataType: 'json',
      value: {
        start: selection.start,
        end: selection.end,
        text: text,
        // A fresh id makes repeated notes count as new values
        id: editing || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      },
    });
    closeNoteForm();
    el.player.focus();
  }

  function deleteNote() {
    if (editing) send('nb-audio:note-delete', { id: editing });

    closeNoteForm();
    el.player.focus();
  }

  // -------------------------------------------------------------------------
  // Playback
  // -------------------------------------------------------------------------
  function togglePlay() {
    if (!ws || !ready) return;

    if (ws.isPlaying()) {
      ws.pause();
      return;
    }

    if (selection) {
      const t = ws.getCurrentTime();
      const inside = t >= selection.start && t < selection.end - 0.005;
      const start = inside ? t : selection.start;
      ws.play(start, looping ? undefined : selection.end);
      return;
    }

    ws.play();
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------
  function destroy() {
    if (ws) ws.destroy();

    ws = null;
    regions = null;
    selection = null;
    ready = false;
    spec = specBox = specCanvas = null;
    specToken++;
    delete el.player.dataset.ready;
    delete el.player.dataset.spectrogram;
    el.minimap.innerHTML = '';
    el.ruler.getContext('2d').clearRect(0, 0, el.ruler.width, el.ruler.height);
    el.waveform.innerHTML = '';
    el.selection.hidden = true;
    closeNoteForm();
  }

  function build() {
    destroy();
    const c = colors();
    const channels = Math.max(1, args.channels || 1);
    const sampleRate = args.sampleRate || 44100;
    const height = waveHeight();

    el.waveform.style.minHeight = `${channels * (height + specHeight()) + 20}px`;
    el.duration.textContent = formatTime(args.duration);
    showMessage('Loading…');

    const plugins = [];
    regions = WaveSurfer.Regions.create();
    plugins.push(regions);
    plugins.push(
      WaveSurfer.Hover.create({
        lineColor: c.accent,
        lineWidth: 1,
        labelBackground: c.secondaryBg,
        labelColor: c.text,
        labelSize: '10.5px',
        formatTimeCallback: (s) => formatTime(s),
      }),
    );

    plugins.push(
      WaveSurfer.Minimap.create({
        container: el.minimap,
        height: 26,
        waveColor: rgba(c.text, c.dark ? 0.3 : 0.24),
        progressColor: rgba(c.primary, 0.75),
        cursorColor: c.accent,
        cursorWidth: 1,
        overlayColor: rgba(c.primary, c.dark ? 0.3 : 0.14),
        normalize: true,
        interact: true,
      }),
    );

    ws = WaveSurfer.create({
      container: el.waveform,
      sampleRate: sampleRate,
      height: height,
      waveColor: c.wave,
      progressColor: c.dark ? c.accent : c.primary,
      cursorColor: c.accent,
      cursorWidth: 1.5,
      splitChannels: channelOptions(height),
      normalize: !!args.normalize,
      minPxPerSec: 0,
      fillParent: true,
      autoScroll: true,
      autoCenter: false,
      dragToSeek: false,
      hideScrollbar: false,
      plugins: plugins,
    });

    regions.enableDragSelection({
      color: rgba(c.primary, c.dark ? 0.28 : 0.16),
    });

    regions.on('region-created', (region) => {
      styleRegion(region);

      for (const other of regions.getRegions()) {
        if (other !== region) other.remove();
      }

      setSelection(region);
    });
    regions.on('region-updated', (region) => setSelection(region));
    regions.on('region-double-clicked', (region, e) => {
      e.stopPropagation();
      zoomToRange(region.start, region.end);
    });

    ws.on('ready', (duration) => {
      ready = true;
      el.player.dataset.ready = 'true';
      createSpectrogram();

      if (specBox) {
        computeSpectrogram(ws.getDecodedData()).catch((error) => {
          showMessage(`Could not compute the spectrogram: ${error}`, true);
        });
      }

      showMessage('');
      el.waveform.style.minHeight = '';
      el.duration.textContent = formatTime(duration);
      el.zoom.value = 0;
      drawRuler();

      if (pending) {
        const p = pending;
        pending = null;
        applyRemote(p.view);
        applyRemote(p.select);
      }

      updateHeight();
    });
    ws.on('error', (error) => {
      showMessage(`Could not load the audio: ${error.message || error}`, true);
      el.waveform.style.minHeight = '';
      updateHeight();
    });
    ws.on('timeupdate', (t) => {
      el.current.textContent = formatTime(t);

      if (looping && selection && ws.isPlaying() && t >= selection.end) {
        ws.setTime(selection.start);
      }
    });
    ws.on('play', () => {
      el.player.classList.add('playing');
      broadcast({ type: 'play' });
    });
    ws.on('pause', () => el.player.classList.remove('playing'));
    ws.on('finish', () => el.player.classList.remove('playing'));
    ws.on('interaction', (t) => broadcast({ type: 'seek', time: t }));
    ws.on('scroll', (start) => {
      drawRuler();
      requestSpectrogram();

      if (ready) broadcast({ type: 'view', pps: currentPxPerSec(), start });
    });
    ws.on('redrawcomplete', () => {
      drawRuler();
      requestSpectrogram();
      updateHeight();
    });

    ws.setPlaybackRate(parseFloat(el.rate.value), true);
    load(ws);
  }

  async function fetchBlob(url) {
    const response = await fetch(url);

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    return response.blob();
  }

  //: Audio embedded in the standalone page as a data URL. It is decoded
  //: here and played from the data URL itself: viewers that open the page
  //: with a content security policy often refuse to fetch data URLs or to
  //: play blob URLs (which `loadBlob` uses)
  async function loadEmbedded(instance) {
    const text = atob(args.url.slice(args.url.indexOf(',') + 1));
    const bytes = new Uint8Array(text.length);

    for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);

    const context = new OfflineAudioContext(1, 1, args.sampleRate || 44100);
    const buffer = await context.decodeAudioData(bytes.buffer);
    const channels = [];

    for (let c = 0; c < buffer.numberOfChannels; c++) {
      channels.push(buffer.getChannelData(c));
    }

    if (instance === ws) {
      await instance.load(args.url, channels, buffer.duration);
    }
  }

  // NOTE: Fetched once as a blob that both decoding and playback use.
  // Streaming from the URL would keep a connection open per player, and
  // browsers only open a few per server, so players further down the page
  // would wait for the ones above
  async function load(instance) {
    try {
      if (args.url.startsWith('data:')) {
        await loadEmbedded(instance);
        return;
      }

      const blob = await fetchBlob(args.url);

      if (instance === ws) await instance.loadBlob(blob);
    } catch (error) {
      if (instance !== ws) return;

      showMessage(`Could not load the audio: ${error.message || error}`, true);
      el.waveform.style.minHeight = '';
      updateHeight();
    }
  }

  // -------------------------------------------------------------------------
  // Linked players
  // -------------------------------------------------------------------------
  function applyRemote(message) {
    if (!message || !ws || !ready) return;

    quietUntil = performance.now() + 200;

    switch (message.type) {
      case 'view': {
        const pps = message.pps;

        if (Math.abs(pps - currentPxPerSec()) / pps > 0.001) {
          setZoom(pps, message.start, true);
        }

        ws.setScroll(Math.max(0, message.start * currentPxPerSec()));
        break;
      }

      case 'select':
        applyRemoteSelection(message.start, message.end);
        break;

      case 'seek':
        if (!ws.isPlaying()) ws.setTime(message.time);
        break;
    }
  }

  if (channel) {
    channel.onmessage = (event) => {
      const message = event.data;

      if (message.type === 'play') {
        if (message.id !== id && ws && ws.isPlaying()) ws.pause();
        return;
      }

      if (!linked(message)) return;

      if (!ready) {
        pending = pending || {};
        pending[message.type === 'select' ? 'select' : 'view'] = message;
        return;
      }

      applyRemote(message);
    };
  }

  // -------------------------------------------------------------------------
  // Controls
  // -------------------------------------------------------------------------
  el.play.addEventListener('click', togglePlay);
  el.zoomIn.addEventListener('click', () => zoomBy(2));
  el.zoomOut.addEventListener('click', () => zoomBy(0.5));
  el.fit.addEventListener('click', () => setZoom(0));
  el.zoom.addEventListener('input', () => setZoom(sliderToPxPerSec(Number(el.zoom.value))));
  el.rate.addEventListener('change', () => {
    if (ws) ws.setPlaybackRate(parseFloat(el.rate.value), true);
  });
  el.loop.addEventListener('click', () => {
    looping = !looping;
    el.loop.classList.toggle('on', looping);

    // Keep playing, now without the stop at the end of the selection
    if (ws && ws.isPlaying() && selection) {
      const t = ws.getCurrentTime();
      ws.play(t, looping ? undefined : selection.end);
    }
  });
  el.zoomSelection.addEventListener('click', () => {
    if (selection) zoomToRange(selection.start, selection.end);
  });
  el.clearSelection.addEventListener('click', clearSelection);
  el.annotate.addEventListener('click', openNoteForm);
  el.fullscreen.addEventListener('click', toggleFullscreen);
  el.fsClose.addEventListener('click', exitFullscreen);
  el.noteCancel.addEventListener('click', closeNoteForm);
  el.noteDelete.addEventListener('click', deleteNote);
  el.noteForm.addEventListener('submit', (e) => {
    e.preventDefault();
    submitNote();
  });
  el.noteText.addEventListener('keydown', (e) => {
    e.stopPropagation(); // Typing must not trigger the player shortcuts

    if (e.key === 'Escape') {
      e.preventDefault();
      closeNoteForm();
      el.player.focus();
    }
  });

  // Ctrl / Cmd + wheel (and trackpad pinch) zooms around the pointer; a
  // plain wheel scrolls the page as usual
  el.waveform.addEventListener(
    'wheel',
    (e) => {
      if (!(e.ctrlKey || e.metaKey) || !ws || !ready) return;

      e.preventDefault();
      const rect = el.waveform.getBoundingClientRect();
      const pps = currentPxPerSec();
      const time = (ws.getScroll() + e.clientX - rect.left) / pps;
      zoomBy(Math.exp(-e.deltaY * 0.0025), time);
    },
    { passive: false },
  );

  document.addEventListener('keydown', (e) => {
    if (e.target && e.target.tagName === 'SELECT') return;
    if (!ws || !ready) return;

    const step = e.shiftKey ? 5 : 1;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        togglePlay();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        ws.setTime(Math.max(0, ws.getCurrentTime() - step));
        break;
      case 'ArrowRight':
        e.preventDefault();
        ws.setTime(Math.min(ws.getDuration(), ws.getCurrentTime() + step));
        break;
      case '+':
      case '=':
        zoomBy(2, ws.getCurrentTime());
        break;
      case '-':
      case '_':
        zoomBy(0.5, ws.getCurrentTime());
        break;
      case '0':
        setZoom(0);
        break;
      case 'l':
      case 'L':
        if (selection) el.loop.click();
        break;
      case 'z':
      case 'Z':
        if (selection) zoomToRange(selection.start, selection.end);
        break;
      case 'n':
      case 'N':
        if (selection) {
          e.preventDefault();
          openNoteForm();
        }
        break;
      case 'f':
      case 'F':
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        toggleFullscreen();
        break;
      case 'Escape':
        if (fullscreen) exitFullscreen();
        else clearSelection();

        break;
    }
  });

  // -------------------------------------------------------------------------
  // Full screen
  // -------------------------------------------------------------------------
  function waveHeight() {
    return fullscreen && fsLayout ? fsLayout.wave : args.waveHeight;
  }

  function specHeight() {
    return fullscreen && fsLayout ? fsLayout.spec : args.spectrogramHeight;
  }

  function channelOptions(height) {
    const channels = Math.max(1, args.channels || 1);

    if (channels < 2) return undefined;

    const c = colors();
    return Array.from({ length: channels }, () => ({
      waveColor: c.wave,
      progressColor: c.primary,
      height: height,
    }));
  }

  //: The file's label, name and tags, as in the sample group's card
  function setHeader(header) {
    const h = header || {};
    const parts = [];

    if (h.label) parts.push(['badge label', h.label]);
    if (h.name) parts.push(['fs-name', h.name]);

    for (const tag of h.tags || []) parts.push(['badge tag', tag]);

    el.fsTitle.textContent = '';

    for (const [className, text] of parts) {
      const span = document.createElement('span');
      span.className = className;
      span.textContent = text;
      el.fsTitle.appendChild(span);
    }

    el.fsTitle.title = h.name || '';
  }

  //: Heights that fill the window below the controls, a third of each
  //: channel for the waveform and the rest for its spectrogram
  function computeLayout() {
    const channels = Math.max(1, args.channels || 1);
    const top = el.waveform.getBoundingClientRect().top - el.player.getBoundingClientRect().top;
    // Bottom padding, wavesurfer's scrollbar and the spectrogram's margin
    const free = Math.max(0, window.innerHeight - top - 30) / channels;

    if (!(args.spectrogramHeight > 0)) {
      return { wave: Math.max(args.waveHeight, Math.floor(free)), spec: 0 };
    }

    const wave = Math.max(args.waveHeight, Math.round(free / 3));
    const spec = Math.max(args.spectrogramHeight, Math.floor(free - wave - 2));
    return { wave: wave, spec: spec };
  }

  //: Applies the current heights to the waveform and spectrogram without
  //: decoding again (the spectrogram is recomputed for its new height)
  function applyLayout() {
    if (!args) return;

    if (!ws || !ready) {
      reserveSpace();
      return;
    }

    const channels = Math.max(1, args.channels || 1);
    const wave = waveHeight();

    if (ws.options.height !== wave) {
      ws.setOptions({ height: wave, splitChannels: channelOptions(wave) });
    }

    if (specBox) {
      specBox.style.height = `${specHeight() * channels}px`;
      requestSpectrogram();

      if (spec && spec.rows !== specHeight()) {
        window.clearTimeout(specTimer);
        specTimer = window.setTimeout(() => {
          if (ws && ready) {
            computeSpectrogram(ws.getDecodedData()).catch(() => {});
          }
        }, 150);
      }
    }

    el.zoom.value = pxPerSecToSlider(currentPxPerSec());
    drawRuler();
  }

  let specTimer = 0;
  let layoutFrame = 0;

  function scheduleLayout() {
    if (layoutFrame) return;

    layoutFrame = requestAnimationFrame(() => {
      layoutFrame = 0;

      if (!fullscreen) return;

      const next = computeLayout();

      if (!fsLayout || next.wave !== fsLayout.wave || next.spec !== fsLayout.spec) {
        fsLayout = next;
        applyLayout();
      }
    });
  }

  let frameStyle = null;
  let holderHeight = null;

  //: Lays the frame over the app window (the frame is same-origin, so its
  //: element in the app page can be styled from here)
  function coverWindow(on) {
    let frame;

    try {
      frame = window.frameElement;
    } catch {
      frame = null;
    }

    if (!frame) return;

    const holder = frame.parentElement;

    if (on) {
      frameStyle = frame.getAttribute('style');
      // Keeps the frame's place in the page while it is lifted out of it
      holderHeight = holder ? holder.style.minHeight : null;

      if (holder) {
        holder.style.minHeight = `${frame.getBoundingClientRect().height}px`;
      }

      const props = {
        position: 'fixed',
        top: '0',
        left: '0',
        width: '100vw',
        height: '100vh',
        'max-width': 'none',
        margin: '0',
        'z-index': '1000500',
      };

      for (const [name, value] of Object.entries(props)) {
        frame.style.setProperty(name, value, 'important');
      }

      window.parent.document.addEventListener('keydown', onParentKey, true);
      return;
    }

    if (frameStyle === null) frame.removeAttribute('style');
    else frame.setAttribute('style', frameStyle);

    if (holder) holder.style.minHeight = holderHeight || '';

    window.parent.document.removeEventListener('keydown', onParentKey, true);
  }

  //: Esc pressed while the app page has the focus
  function onParentKey(e) {
    if (e.key === 'Escape' && fullscreen) {
      e.preventDefault();
      e.stopPropagation();
      exitFullscreen();
    }
  }

  function enterFullscreen() {
    if (fullscreen || !args) return;

    fullscreen = true;
    document.documentElement.classList.add('fullscreen');
    el.player.classList.add('fullscreen');
    el.fsHeader.hidden = false;
    el.fullscreen.title = 'Exit full screen (Esc)';

    try {
      coverWindow(true);
    } catch {
      // The page could not be reached: the player still fills its frame
    }

    fsLayout = computeLayout();
    applyLayout();
    el.player.focus();
  }

  function exitFullscreen() {
    if (!fullscreen) return;

    fullscreen = false;
    fsLayout = null;
    document.documentElement.classList.remove('fullscreen');
    el.player.classList.remove('fullscreen');
    el.fsHeader.hidden = true;
    el.fullscreen.title = 'Full screen (F)';

    try {
      coverWindow(false);
    } catch {
      // Nothing to restore
    }

    applyLayout();
    lastHeight = -1;
    updateHeight();
    el.player.focus();
  }

  function toggleFullscreen() {
    if (fullscreen) exitFullscreen();
    else enterFullscreen();
  }

  window.addEventListener('resize', () => {
    if (fullscreen) scheduleLayout();
  });

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  function onRender(newArgs, newTheme) {
    // NOTE: Every rerun sends the same arguments; only rebuild (and decode
    // the audio again) when the arguments or the theme changed
    // (the notes, name and tags do not need a rebuild either)
    const { annotations: notes, header, ...rest } = newArgs;
    const key = JSON.stringify([rest, newTheme || {}]);

    if (key !== structure) {
      structure = key;
      args = newArgs;
      theme = newTheme || {};
      applyTheme();
      el.annotate.hidden = !args.notes;

      if (visible) build();
      else reserveSpace();
    }

    setAnnotations(notes);
    setHeader(header);

    updateHeight();
  }

  function reserveSpace() {
    const channels = Math.max(1, args.channels || 1);
    el.duration.textContent = formatTime(args.duration);
    el.waveform.style.minHeight = `${channels * (waveHeight() + specHeight()) + 20}px`;
  }

  // Decode and draw only once the player scrolls into view, so a page full
  // of long files stays responsive. The frame's position in the app page
  // is checked directly (the component frame is same-origin); an
  // IntersectionObserver alone misses frames that appear in view after a
  // rerun.
  function inView() {
    try {
      const frame = window.frameElement;

      if (!frame) return true;

      const rect = frame.getBoundingClientRect();
      const height = window.parent.innerHeight;
      return rect.width > 0 && rect.bottom > -300 && rect.top < height + 300;
    } catch {
      return true; // Not reachable: load right away
    }
  }

  function checkVisible() {
    if (visible || !inView()) return;

    visible = true;
    window.clearInterval(visibilityTimer);

    if (args && !ws) build();
  }

  const visibilityTimer = window.setInterval(checkVisible, 400);
  new IntersectionObserver(checkVisible, { rootMargin: '300px' }).observe(el.player);

  if (embed) {
    onRender(embed.args, embed.theme);
    // the export calls this when its light/dark toggle changes
    window.nbAudioTheme = (theme) => onRender(embed.args, theme);
  }
})();
