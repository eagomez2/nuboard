export type DiffRow = {
  left: string | null;
  right: string | null;
  ln: number | null;
  rn: number | null;
  kind: 'same' | 'del' | 'add' | 'mod';
};

/** Line diff (LCS) laid out side by side. Falls back to positional comparison for huge inputs. */
export function sideBySide(a: string, b: string): DiffRow[] {
  const A = a.replace(/\n$/, '').split('\n');
  const B = b.replace(/\n$/, '').split('\n');
  const n = A.length;
  const m = B.length;
  if (n * m > 4_000_000) {
    const rows: DiffRow[] = [];
    for (let i = 0; i < Math.max(n, m); i++) {
      const l = i < n ? A[i] : null;
      const r = i < m ? B[i] : null;
      rows.push({
        left: l,
        right: r,
        ln: l === null ? null : i + 1,
        rn: r === null ? null : i + 1,
        kind: l === r ? 'same' : 'mod',
      });
    }
    return rows;
  }
  const dp = new Uint32Array((n + 1) * (m + 1));
  const W = m + 1;
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i * W + j] = A[i] === B[j] ? dp[(i + 1) * W + j + 1] + 1 : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1]);
  const ops: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && A[i] === B[j]) {
      ops.push({ left: A[i], right: B[j], ln: i + 1, rn: j + 1, kind: 'same' });
      i++;
      j++;
    } else if (j < m && (i >= n || dp[i * W + j + 1] >= dp[(i + 1) * W + j])) {
      ops.push({ left: null, right: B[j], ln: null, rn: j + 1, kind: 'add' });
      j++;
    } else {
      ops.push({ left: A[i], right: null, ln: i + 1, rn: null, kind: 'del' });
      i++;
    }
  }
  // Pair adjacent deletions and additions into modified rows.
  const rows: DiffRow[] = [];
  for (let k = 0; k < ops.length;) {
    if (ops[k].kind === 'same') {
      rows.push(ops[k++]);
      continue;
    }
    const dels: DiffRow[] = [];
    const adds: DiffRow[] = [];
    while (k < ops.length && ops[k].kind !== 'same') (ops[k].kind === 'del' ? dels : adds).push(ops[k++]);
    for (let t = 0; t < Math.max(dels.length, adds.length); t++) {
      const d = dels[t];
      const ad = adds[t];
      rows.push({
        left: d?.left ?? null,
        right: ad?.right ?? null,
        ln: d?.ln ?? null,
        rn: ad?.rn ?? null,
        kind: d && ad ? 'mod' : d ? 'del' : 'add',
      });
    }
  }
  return rows;
}

/** Flatten nested objects to dotted keys. */
export function flatten(obj: unknown, prefix = '', out: Record<string, unknown> = {}): Record<string, unknown> {
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) flatten(v, prefix ? `${prefix}.${k}` : k, out);
  } else if (prefix) {
    out[prefix] = obj;
  }
  return out;
}

/** A run of text in a changed line, `changed` when it is not in the other line. */
export type WordPart = { text: string; changed: boolean };

/**
 * Word diff of two lines (LCS over words and the spaces between them): the parts of `a` and of
 * `b`, with the words only one side has marked as changed. Lines too long to compare word by word
 * come back whole and changed.
 */
export function wordDiff(a: string, b: string): [WordPart[], WordPart[]] {
  const A = a.split(/(\s+)/).filter((t) => t !== '');
  const B = b.split(/(\s+)/).filter((t) => t !== '');
  const n = A.length;
  const m = B.length;
  if (n * m > 1_000_000) return [[{ text: a, changed: true }], [{ text: b, changed: true }]];
  const W = m + 1;
  const dp = new Uint32Array((n + 1) * W);
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i * W + j] = A[i] === B[j] ? dp[(i + 1) * W + j + 1] + 1 : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1]);
  const left: WordPart[] = [];
  const right: WordPart[] = [];
  const push = (out: WordPart[], text: string, changed: boolean) => {
    const last = out[out.length - 1];
    if (last && last.changed === changed) last.text += text;
    else out.push({ text, changed });
  };
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && A[i] === B[j]) {
      push(left, A[i++], false);
      push(right, B[j++], false);
    } else if (j < m && (i === n || dp[i * W + j + 1] >= dp[(i + 1) * W + j])) push(right, B[j++], true);
    else push(left, A[i++], true);
  }
  return [left, right];
}
