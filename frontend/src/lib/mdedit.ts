// Markdown editing commands for the report editor's toolbar.
//
// Each command takes the text and the selection and returns one replacement (`from`..`to`
// becomes `insert`) plus the selection afterwards, so the editor can apply it as a single
// typing step that the browser's own undo and redo understand. The text stays plain
// Markdown; underline, which Markdown lacks, is written as `<u>…</u>`.

export interface Sel {
  text: string;
  start: number;
  end: number;
}

export interface Edit {
  from: number;
  to: number;
  insert: string;
  selStart: number;
  selEnd: number;
}

export type Inline = 'bold' | 'italic' | 'underline' | 'strike' | 'code' | 'link';
export type Block = 'h1' | 'h2' | 'h3' | 'bullet' | 'numbered' | 'check' | 'quote';
export type Format = Inline | Block | 'codeblock' | 'paragraph';

const MARKS: Record<Exclude<Inline, 'link'>, [string, string]> = {
  bold: ['**', '**'],
  italic: ['_', '_'],
  underline: ['<u>', '</u>'],
  strike: ['~~', '~~'],
  code: ['`', '`'],
};

// What counts as each format when reading existing text (italic also in its `*x*` spelling)
const SPANS: Record<Inline, RegExp[]> = {
  bold: [/\*\*(.+?)\*\*/g, /__(.+?)__/g],
  italic: [/(?<![\w*])\*(?!\*)(.+?)(?<!\*)\*(?![\w*])/g, /(?<![\w_])_(?!_)(.+?)(?<!_)_(?![\w_])/g],
  underline: [/<u>(.*?)<\/u>/g],
  strike: [/~~(.+?)~~/g],
  code: [/`([^`\n]+)`/g],
  link: [/(?<!!)\[([^\]\n]*)\]\([^)\s]*(?:\s+"[^"]*")?\)/g],
};

const PREFIX: Record<Block, string> = {
  h1: '# ',
  h2: '## ',
  h3: '### ',
  bullet: '- ',
  numbered: '1. ',
  check: '- [ ] ',
  quote: '> ',
};

const HEADING = /^#{1,6}\s+/;
const QUOTE = /^>\s?/;
const CHECK = /^(\s*)[-*+]\s+\[[ xX]\]\s+/;
const BULLET = /^(\s*)[-*+]\s+/;
const NUMBERED = /^(\s*)\d+[.)]\s+/;
const FENCE = /^\s*(```|~~~)/;

const lineStart = (text: string, pos: number) => text.lastIndexOf('\n', pos - 1) + 1;
const lineEnd = (text: string, pos: number) => {
  const i = text.indexOf('\n', pos);
  return i < 0 ? text.length : i;
};

interface Span {
  a: number; // the whole span, markers included
  b: number;
  innerA: number; // the text inside the markers
  innerB: number;
}

/** The span of `format` around the selection, on the selection's line, or null. */
function spanAt(sel: Sel, format: Inline): Span | null {
  const ls = lineStart(sel.text, sel.start);
  const le = lineEnd(sel.text, sel.start);
  if (sel.end > le) return null;
  const line = sel.text.slice(ls, le);
  for (const re of SPANS[format]) {
    re.lastIndex = 0;
    for (const m of line.matchAll(re)) {
      const a = ls + m.index;
      const b = a + m[0].length;
      const innerA = a + m[0].indexOf(m[1]);
      const innerB = innerA + m[1].length;
      const caretOnEdge = sel.start === sel.end && (sel.start === a || sel.start === b);
      if (sel.start >= a && sel.end <= b && !caretOnEdge) return { a, b, innerA, innerB };
    }
  }
  return null;
}

/** The word around a caret, as [start, end], or null when the caret is not in a word. */
function wordAt(text: string, pos: number): [number, number] | null {
  const isWord = (c: string | undefined) => !!c && /[\p{L}\p{N}_\-.']/u.test(c);
  let a = pos;
  let b = pos;
  while (isWord(text[a - 1])) a--;
  while (isWord(text[b])) b++;
  return a < b ? [a, b] : null;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Remove a span's markers, keeping the selection on the same text. */
function unwrap(sel: Sel, s: Span): Edit {
  const inner = sel.text.slice(s.innerA, s.innerB);
  const at = (p: number) => s.a + clamp(p, s.innerA, s.innerB) - s.innerA;
  return { from: s.a, to: s.b, insert: inner, selStart: at(sel.start), selEnd: at(sel.end) };
}

function toggleInline(sel: Sel, format: Inline): Edit {
  const span = spanAt(sel, format);
  if (span) return unwrap(sel, span);
  const { text } = sel;
  let { start, end } = sel;

  if (format === 'link') {
    if (start === end) [start, end] = wordAt(text, start) ?? [start, end];
    const label = text.slice(start, end) || 'text';
    const insert = `[${label}](https://)`;
    // with a label, select the URL to type over; without one, the label
    const urlAt = start + label.length + 3;
    return start === end
      ? { from: start, to: end, insert, selStart: start + 1, selEnd: start + 1 + label.length }
      : { from: start, to: end, insert, selStart: urlAt, selEnd: urlAt + 'https://'.length };
  }

  const [open, close] = MARKS[format];
  if (text.slice(start, end).includes('\n')) {
    // each non-empty line on its own: Markdown emphasis does not cross lines
    const from = lineStart(text, start);
    const to = lineEnd(text, end);
    const insert = text
      .slice(from, to)
      .split('\n')
      .map((l) =>
        l.replace(/^(\s*)(.*?)(\s*)$/, (_, lead, body, trail) => (body ? lead + open + body + close + trail : l)),
      )
      .join('\n');
    return { from, to, insert, selStart: from, selEnd: from + insert.length };
  }
  if (start === end) {
    const word = wordAt(text, start);
    if (!word)
      return { from: start, to: end, insert: open + close, selStart: start + open.length, selEnd: start + open.length };
    const offset = start - word[0];
    [start, end] = word;
    const insert = open + text.slice(start, end) + close;
    return {
      from: start,
      to: end,
      insert,
      selStart: start + open.length + offset,
      selEnd: start + open.length + offset,
    };
  }
  // keep spaces at the edges of the selection outside the markers
  while (start < end && /\s/.test(text[start])) start++;
  while (end > start && /\s/.test(text[end - 1])) end--;
  const insert = open + text.slice(start, end) + close;
  return { from: start, to: end, insert, selStart: start + open.length, selEnd: end + open.length };
}

/** Which block format a line has (a heading level, quote or list), or null. */
function blockOf(line: string): Block | null {
  const h = line.match(HEADING);
  if (h) {
    const level = h[0].trim().length;
    return level <= 3 ? (`h${level}` as Block) : null;
  }
  if (QUOTE.test(line)) return 'quote';
  if (CHECK.test(line)) return 'check';
  if (BULLET.test(line)) return 'bullet';
  if (NUMBERED.test(line)) return 'numbered';
  return null;
}

/** A line without its heading, quote or list marker (list indentation is kept). */
function stripBlock(line: string, family: 'heading' | 'quote' | 'list' | 'all'): string {
  let out = line;
  if (family === 'heading' || family === 'all') out = out.replace(HEADING, '');
  if (family === 'quote' || family === 'all') out = out.replace(QUOTE, '');
  if (family === 'list' || family === 'all') {
    const m = out.match(CHECK) ?? out.match(BULLET) ?? out.match(NUMBERED);
    if (m) out = m[1] + out.slice(m[0].length);
  }
  return out;
}

const familyOf = (b: Block) => (b.startsWith('h') ? 'heading' : b === 'quote' ? 'quote' : 'list');

function toggleBlock(sel: Sel, format: Block | 'paragraph'): Edit {
  const { text } = sel;
  const from = lineStart(text, sel.start);
  const to = lineEnd(text, sel.end > sel.start && text[sel.end - 1] === '\n' ? sel.end - 1 : sel.end);
  const lines = text.slice(from, to).split('\n');
  const filled = lines.filter((l) => l.trim());
  const all = format !== 'paragraph' && filled.length > 0 && filled.every((l) => blockOf(l) === format);
  let n = 0;
  const out = lines.map((l) => {
    if (!l.trim() && lines.length > 1) return l;
    if (format === 'paragraph') return stripBlock(l, 'all');
    // headings replace every other block marker; lists and quotes replace their own kind
    const bare = stripBlock(l, format.startsWith('h') ? 'all' : familyOf(format));
    if (all) return bare;
    const indent = format.startsWith('h') ? '' : (bare.match(/^\s*/)?.[0] ?? '');
    const prefix = format === 'numbered' ? `${++n}. ` : PREFIX[format];
    return indent + prefix + bare.slice(indent.length);
  });
  const insert = out.join('\n');
  if (lines.length === 1) {
    const shift = insert.length - (to - from);
    const caret = (p: number) => Math.max(from, p + shift);
    return { from, to, insert, selStart: caret(sel.start), selEnd: caret(sel.end) };
  }
  return { from, to, insert, selStart: from, selEnd: from + insert.length };
}

/** The fence lines of the code block around `pos`, as [open line start, close line end], or null. */
function fenceAt(text: string, pos: number): [number, number] | null {
  const lines = text.split('\n');
  let at = 0;
  let open: number | null = null;
  for (const line of lines) {
    const end = at + line.length;
    if (FENCE.test(line)) {
      if (open === null) open = at;
      else {
        if (pos >= open && pos <= end) return [open, end];
        open = null;
      }
    }
    at = end + 1;
  }
  return null;
}

function toggleCodeBlock(sel: Sel): Edit {
  const { text } = sel;
  const fence = fenceAt(text, sel.start);
  if (fence) {
    const [a, b] = fence;
    const body = text.slice(lineEnd(text, a) + 1, lineStart(text, b) - 1);
    const shift = lineEnd(text, a) + 1 - a;
    return {
      from: a,
      to: b,
      insert: body,
      selStart: clamp(sel.start - shift, a, a + body.length),
      selEnd: clamp(sel.end - shift, a, a + body.length),
    };
  }
  const from = lineStart(text, sel.start);
  const to = lineEnd(text, sel.end);
  const body = text.slice(from, to);
  const insert = '```\n' + body + '\n```';
  return { from, to, insert, selStart: from + 4, selEnd: from + 4 + body.length };
}

/** Put `block` on lines of its own after the selection's line, with a blank line around it. */
export function insertBlock(sel: Sel, block: string, select?: [number, number]): Edit {
  const { text } = sel;
  const ls = lineStart(text, sel.end);
  const le = lineEnd(text, sel.end);
  const empty = !text.slice(ls, le).trim();
  // an empty line is replaced; otherwise the block goes after the line
  const from = empty ? ls : le;
  const prevBlank = ls === 0 || !text.slice(lineStart(text, ls - 1), ls - 1).trim();
  const before = empty ? (prevBlank ? '' : '\n') : '\n\n';
  const rest = text.slice(le);
  const nextBlank = !rest.slice(1).split('\n')[0].trim();
  const after = rest === '' ? '\n' : nextBlank ? '' : '\n';
  const base = from + before.length;
  const [a, b] = select ?? [block.length, block.length];
  return { from, to: le, insert: before + block + after, selStart: base + a, selEnd: base + b };
}

/** A Markdown table of `rows` body rows and `cols` columns, with the first header cell selected. */
export function insertTable(sel: Sel, rows: number, cols: number): Edit {
  const head = Array.from({ length: cols }, (_, i) => `Column ${i + 1}`);
  const lines = [
    `| ${head.join(' | ')} |`,
    `| ${head.map(() => '---').join(' | ')} |`,
    ...Array.from({ length: rows }, () => `| ${head.map(() => '   ').join(' | ')} |`),
  ];
  return insertBlock(sel, lines.join('\n'), [2, 2 + head[0].length]);
}

export const insertRule = (sel: Sel): Edit => insertBlock(sel, '---');

/** Apply a toolbar command: inline formats wrap or unwrap, block formats prefix lines. */
export function toggle(sel: Sel, format: Format): Edit {
  if (format === 'codeblock') return toggleCodeBlock(sel);
  if (format in PREFIX || format === 'paragraph') return toggleBlock(sel, format as Block | 'paragraph');
  return toggleInline(sel, format as Inline);
}

/** The formats active at the selection, for the toolbar's pressed buttons. */
export function activeFormats(sel: Sel): Set<Format> {
  const out = new Set<Format>();
  if (fenceAt(sel.text, sel.start)) {
    out.add('codeblock');
    return out;
  }
  for (const f of Object.keys(SPANS) as Inline[]) if (spanAt(sel, f)) out.add(f);
  const line = sel.text.slice(lineStart(sel.text, sel.start), lineEnd(sel.text, sel.start));
  const block = blockOf(line);
  if (block) out.add(block);
  else if (!HEADING.test(line)) out.add('paragraph');
  return out;
}

/** Apply an edit to a string (what the textarea does; used by tests). */
export function applyEdit(text: string, e: Edit): Sel {
  return { text: text.slice(0, e.from) + e.insert + text.slice(e.to), start: e.selStart, end: e.selEnd };
}
