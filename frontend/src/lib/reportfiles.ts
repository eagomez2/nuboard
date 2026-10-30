// Turning files picked in the report editor into Markdown: images and attached text files
// are uploaded and linked, inline text files are pasted in as Markdown, code or a table.

/** Default size limits, used until the server says otherwise (`Info.upload_limits`). */
export const LIMITS = { image: 20 * 1024 * 1024, text: 5 * 1024 * 1024 };

export const TEXT_ACCEPT =
  '.txt,.md,.markdown,.log,.csv,.tsv,.json,.jsonl,.yaml,.yml,.toml,.ini,.cfg,.xml,.py,.sh,.js,.ts,.c,.h,.cpp,.rs,.go,.java,.rb,.sql,.r,.jl,.tex,.diff,.patch,text/*';

const LANGS: Record<string, string> = {
  py: 'python',
  ipynb: 'json',
  js: 'javascript',
  mjs: 'javascript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  json: 'json',
  jsonl: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'toml',
  ini: 'ini',
  cfg: 'ini',
  xml: 'xml',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  ps1: 'powershell',
  c: 'c',
  h: 'c',
  cc: 'cpp',
  cpp: 'cpp',
  hpp: 'cpp',
  cu: 'cuda',
  rs: 'rust',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  rb: 'ruby',
  sql: 'sql',
  r: 'r',
  jl: 'julia',
  lua: 'lua',
  tex: 'latex',
  diff: 'diff',
  patch: 'diff',
  csv: 'csv',
  tsv: 'tsv',
};

export const extOf = (name: string) => (name.includes('.') ? name.split('.').pop()!.toLowerCase() : '');
export const isMarkdown = (name: string) => ['md', 'markdown'].includes(extOf(name));
export const isTable = (name: string) => ['csv', 'tsv'].includes(extOf(name));
export const langOf = (name: string) => LANGS[extOf(name)] ?? 'text';

/** The text of a file, or why it is not accepted: too large, NUL bytes or not UTF-8. */
export function decodeText(bytes: Uint8Array, name: string, limit = LIMITS.text): { text: string } | { error: string } {
  if (bytes.length > limit)
    return { error: `${name} is ${(bytes.length / 1e6).toFixed(1)} MB; text files can be at most ${limit / 1e6} MB.` };
  if (bytes.includes(0)) return { error: `${name} is not a text file: it has NUL bytes.` };
  try {
    return { text: new TextDecoder('utf-8', { fatal: true }).decode(bytes) };
  } catch {
    return { error: `${name} is not UTF-8 text.` };
  }
}

/** Rows of a CSV or TSV file; quoted fields may hold the separator, quotes and newlines. */
export function parseDelimited(text: string, sep = ','): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"' && !field) quoted = true;
    else if (c === sep) {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else field += c;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((f) => f.trim()));
}

const cell = (s: string) =>
  s
    .replace(/\|/g, '\\|')
    .replace(/\s*\n\s*/g, ' ')
    .trim();

/** A GFM table of a CSV or TSV file: its first row is the header. */
export function tableMarkdown(text: string, name: string): string {
  const rows = parseDelimited(text, extOf(name) === 'tsv' ? '\t' : ',');
  if (!rows.length) return '';
  const cols = Math.max(...rows.map((r) => r.length));
  const line = (r: string[]) => `| ${Array.from({ length: cols }, (_, i) => cell(r[i] ?? '')).join(' | ')} |`;
  return [line(rows[0]), `| ${Array(cols).fill('---').join(' | ')} |`, ...rows.slice(1).map(line)].join('\n');
}

/** A fenced code block that no backtick run inside `text` can close early. */
export function codeBlock(text: string, lang: string): string {
  const longest = Math.max(2, ...[...text.matchAll(/`+/g)].map((m) => m[0].length));
  const fence = '`'.repeat(longest + 1);
  return `${fence}${lang}\n${text.replace(/\n+$/, '')}\n${fence}`;
}

/** The Markdown a text file is pasted in as: Markdown as is, a table, or a code block under its name. */
export function inlineText(text: string, name: string, asTable = false): string {
  if (isMarkdown(name)) return text.replace(/\s+$/, '');
  if (asTable && isTable(name)) {
    const table = tableMarkdown(text, name);
    if (table) return `*${name}*\n\n${table}`;
  }
  return `*${name}*\n\n${codeBlock(text, langOf(name))}`;
}

/** The link an attached file is written as; the viewer shows it as a collapsible block. */
export const attachmentMarkdown = (name: string, path: string) =>
  `[${name.replace(/[[\]]/g, '')}](${path} "attachment")`;

/** The image line of an uploaded image, with its caption as a paragraph below. */
export function imageMarkdown(path: string, alt: string, caption: string): string {
  const line = `![${alt.replace(/[[\]]/g, '')}](${path})`;
  return caption.trim() ? `${line}\n\n*${caption.trim()}*` : line;
}
