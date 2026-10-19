// Terminal output as a terminal shows it: ANSI color and style codes (SGR) drawn as
// styled HTML, and `\r` redrawing its line (progress bars). Other escape codes are dropped.

const ESC = String.fromCharCode(27);
const CODE = new RegExp(
  `${ESC}\\[([0-9;:?]*)([A-Za-z])|${ESC}\\][^\\x07${ESC}]*(?:\\x07|${ESC}\\\\)|${ESC}[()][A-Z0-9]|${ESC}[=>]`,
  'g',
);

/** True for text with escape codes or `\r` redraws, which reads better drawn as a terminal. */
export const isTerminalText = (text: string) => text.includes(`${ESC}[`) || /\r(?!\n)/.test(text);

/** Each line as its last redraw: what follows the last `\r`, keeping earlier codes so styles carry over. */
function redraw(text: string): string {
  return text
    .split('\n')
    .map((line) => {
      const parts = line.replace(/\r+$/, '').split('\r');
      if (parts.length === 1) return line;
      const codes = parts
        .slice(0, -1)
        .map((p) => (p.match(CODE) ?? []).join(''))
        .join('');
      return codes + parts[parts.length - 1];
    })
    .join('\n');
}

/** The visible text: no codes, one redraw per line. */
export function stripAnsi(text: string): string {
  return redraw(text).replace(CODE, '');
}

/** The raw text with each escape character shown as ␛. */
export const showEscapes = (text: string) => text.replaceAll(ESC, '␛');

type Style = {
  fg: string | null;
  bg: string | null;
  bold: boolean;
  dim: boolean;
  italic: boolean;
  underline: boolean;
  inverse: boolean;
  strike: boolean;
};
const plain = (): Style => ({
  fg: null,
  bg: null,
  bold: false,
  dim: false,
  italic: false,
  underline: false,
  inverse: false,
  strike: false,
});

/** A 256-color index as CSS: the 16 terminal colors follow the theme, the rest are fixed. */
function color256(n: number): string | null {
  if (!Number.isInteger(n) || n < 0 || n > 255) return null;
  if (n < 16) return `var(--ansi-${n})`;
  if (n >= 232) {
    const v = 8 + (n - 232) * 10;
    return `rgb(${v},${v},${v})`;
  }
  const i = n - 16;
  const level = (c: number) => (c ? 55 + c * 40 : 0);
  return `rgb(${level(Math.floor(i / 36))},${level(Math.floor(i / 6) % 6)},${level(i % 6)})`;
}

function applySgr(style: Style, params: string): Style {
  const s = { ...style };
  const nums = (params === '' ? '0' : params).split(/[;:]/).map((p) => (p === '' ? 0 : Number(p)));
  for (let i = 0; i < nums.length; i++) {
    const n = nums[i];
    if (n === 0) Object.assign(s, plain());
    else if (n === 1) s.bold = true;
    else if (n === 2) s.dim = true;
    else if (n === 3) s.italic = true;
    else if (n === 4) s.underline = true;
    else if (n === 7) s.inverse = true;
    else if (n === 9) s.strike = true;
    else if (n === 21 || n === 22) s.bold = s.dim = false;
    else if (n === 23) s.italic = false;
    else if (n === 24) s.underline = false;
    else if (n === 27) s.inverse = false;
    else if (n === 29) s.strike = false;
    else if (n >= 30 && n <= 37) s.fg = `var(--ansi-${n - 30})`;
    else if (n >= 90 && n <= 97) s.fg = `var(--ansi-${n - 90 + 8})`;
    else if (n >= 40 && n <= 47) s.bg = `var(--ansi-${n - 40})`;
    else if (n >= 100 && n <= 107) s.bg = `var(--ansi-${n - 100 + 8})`;
    else if (n === 39) s.fg = null;
    else if (n === 49) s.bg = null;
    else if (n === 38 || n === 48) {
      let c: string | null = null;
      if (nums[i + 1] === 5) {
        c = color256(nums[i + 2]);
        i += 2;
      } else if (nums[i + 1] === 2) {
        const [r, g, b] = nums.slice(i + 2, i + 5).map((v) => Math.max(0, Math.min(255, v || 0)));
        c = `rgb(${r},${g},${b})`;
        i += 4;
      }
      if (n === 38) s.fg = c;
      else s.bg = c;
    }
  }
  return s;
}

function css(s: Style): string {
  const fg = s.inverse ? (s.bg ?? 'var(--panel)') : s.fg;
  const bg = s.inverse ? (s.fg ?? 'var(--text)') : s.bg;
  const out: string[] = [];
  if (fg) out.push(`color:${fg}`);
  if (bg) out.push(`background:${bg}`);
  if (s.bold) out.push('font-weight:700');
  if (s.dim) out.push('opacity:.65');
  if (s.italic) out.push('font-style:italic');
  const deco = [s.underline && 'underline', s.strike && 'line-through'].filter(Boolean);
  if (deco.length) out.push(`text-decoration:${deco.join(' ')}`);
  return out.join(';');
}

const escapeHtml = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** The text as HTML: styled spans for colored runs, everything else escaped. */
export function ansiToHtml(text: string): string {
  const src = redraw(text);
  let style = plain();
  let out = '';
  let last = 0;
  const emit = (chunk: string) => {
    if (!chunk) return;
    const c = css(style);
    out += c ? `<span style="${c}">${escapeHtml(chunk)}</span>` : escapeHtml(chunk);
  };
  for (const m of src.matchAll(CODE)) {
    emit(src.slice(last, m.index));
    last = m.index! + m[0].length;
    if (m[2] === 'm') style = applySgr(style, m[1]);
  }
  emit(src.slice(last));
  return out;
}
