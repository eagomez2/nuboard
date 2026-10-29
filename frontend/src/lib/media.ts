import type { MediaItem } from './api';

export interface AudioOptions {
  colormap: string;
  scale: string;
  fftSize: number;
  spectrogram: boolean;
  /** Amplitude labels on the waveform. */
  axis: boolean;
}

export type MediaKind = 'image' | 'audio' | 'video' | 'figure' | 'table' | 'points' | 'html' | 'text';
export const MEDIA_KINDS: MediaKind[] = ['image', 'audio', 'video', 'figure', 'table', 'points', 'html', 'text'];

/** MIME type of tables logged with `add_table`. */
export const TABLE_MIME = 'application/x-nuboard-table+json';

/** MIME type of point clouds logged with `add_point_cloud`. */
export const POINTS_MIME = 'application/x-nuboard-points';

/** MIME type of precision-recall curves logged with `add_pr_curve`. */
export const PR_MIME = 'application/x-nuboard-pr+json';

/** MIME type of distributions logged with `add_histogram`. */
export const HIST_MIME = 'application/x-nuboard-histogram+json';

/** MIME type of waveforms with signals logged with `add_figure(key, nb.WaveformFigure(...))`. */
export const WAVEFORM_MIME = 'application/x-nuboard-waveform';

/** File name extensions of downloaded media, by MIME type. */
const EXTENSIONS: Record<string, string> = {
  'image/png': '.png',
  'image/apng': '.png',
  'image/jpeg': '.jpg',
  'image/gif': '.gif',
  'image/webp': '.webp',
  'image/svg+xml': '.svg',
  'audio/wav': '.wav',
  'audio/flac': '.flac',
  'audio/mpeg': '.mp3',
  'audio/ogg': '.ogg',
  'audio/mp4': '.m4a',
  'audio/webm': '.webm',
  'video/mp4': '.mp4',
  'video/webm': '.webm',
  'video/quicktime': '.mov',
  'video/ogg': '.ogv',
  'text/html': '.html',
  'text/plain': '.txt',
  'application/vnd.plotly.v1+json': '.plotly.json',
  'application/vnd.vegalite+json': '.vl.json',
  'application/vnd.bokeh+json': '.bokeh.json',
  [TABLE_MIME]: '.json',
  [PR_MIME]: '.json',
  [HIST_MIME]: '.json',
  [POINTS_MIME]: '.bin',
};

/** The file name extension a downloaded item gets from its MIME type, such as `.png`. */
export function extensionOf(mime: string): string {
  return EXTENSIONS[mime] ?? (mime.endsWith('+json') || mime.endsWith('/json') ? '.json' : '.bin');
}

/** The kind a media item is filtered by on the Media page. */
export function kindOf(it: Pick<MediaItem, 'kind' | 'mime'>): MediaKind {
  if (it.kind === 'text') return 'text';
  if (it.mime === 'text/html' || it.kind === 'html') return 'html';
  if (it.kind === 'audio' || it.mime.startsWith('audio/')) return 'audio';
  if (it.kind === 'video' || it.mime.startsWith('video/')) return 'video';
  if (it.mime === POINTS_MIME) return 'points';
  if (it.mime === PR_MIME || it.mime === HIST_MIME || it.mime === WAVEFORM_MIME) return 'figure';
  if (it.mime === TABLE_MIME) return 'table';
  if (it.kind === 'figure' || /plotly|vega|bokeh|svg/.test(it.mime)) return 'figure';
  return 'image';
}

/** `media:` reference to one item of a run, as written in reports: `<run id>/<key>@<step>`. */
export function mediaRef(runId: string, key: string, step: number): string {
  return `${encodeURIComponent(runId)}/${key.split('/').map(encodeURIComponent).join('/')}@${step}`;
}

/** The Markdown line that embeds an item in a report. */
export function embedLine(runId: string, key: string, step: number, caption = ''): string {
  return `![${caption.replace(/[[\]]/g, '')}](media:${mediaRef(runId, key, step)})`;
}

/** The item shown at `target`: the last one at or before it, else the first one. */
export function itemAt<T extends { step: number }>(list: T[], target: number): T | null {
  if (!list.length) return null;
  let found: T | null = null;
  for (const it of list) if (it.step <= target) found = it;
  return found ?? list[0];
}
