// A three-way merge of text by lines, for a report changed in two places since it was opened.

/** Pairs of matching line indexes between `a` and `b` (a longest common subsequence), or null. */
function matches(a: string[], b: string[]): Map<number, number> | null {
  const n = a.length;
  const m = b.length;
  // common prefix and suffix first: the usual edit touches a few lines in the middle
  let start = 0;
  while (start < n && start < m && a[start] === b[start]) start++;
  let endA = n;
  let endB = m;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const out = new Map<number, number>();
  for (let i = 0; i < start; i++) out.set(i, i);
  const rows = endA - start;
  const cols = endB - start;
  if (rows * cols > 4_000_000) return null; // too long to compare line by line
  const lcs: Uint32Array[] = Array.from({ length: rows + 1 }, () => new Uint32Array(cols + 1));
  for (let i = rows - 1; i >= 0; i--)
    for (let j = cols - 1; j >= 0; j--)
      lcs[i][j] = a[start + i] === b[start + j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  for (let i = 0, j = 0; i < rows && j < cols;) {
    if (a[start + i] === b[start + j]) {
      out.set(start + i, start + j);
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) i++;
    else j++;
  }
  for (let k = 0; endA + k < n; k++) out.set(endA + k, endB + k);
  return out;
}

const same = (x: string[], y: string[]) => x.length === y.length && x.every((v, i) => v === y[i]);

/**
 * Merge two edits of `base`. Lines changed on one side only are taken from that side, lines changed
 * the same way on both are taken once. Returns null when both changed the same lines differently,
 * or when the texts are too long to compare line by line.
 */
export function merge3(base: string, mine: string, theirs: string): string | null {
  if (mine === theirs || theirs === base) return mine;
  if (mine === base) return theirs;
  const O = base.split('\n');
  const A = mine.split('\n');
  const B = theirs.split('\n');
  const ma = matches(O, A);
  const mb = matches(O, B);
  if (!ma || !mb) return null;
  const out: string[] = [];
  let a = 0;
  let b = 0;
  let o = 0;
  for (let j = 0; j <= O.length; j++) {
    // a base line kept by both sides (or the end) closes a chunk
    const stable = j === O.length || (ma.has(j) && mb.has(j) && ma.get(j)! >= a && mb.get(j)! >= b);
    if (!stable) continue;
    const endA = j === O.length ? A.length : ma.get(j)!;
    const endB = j === O.length ? B.length : mb.get(j)!;
    const co = O.slice(o, j);
    const ca = A.slice(a, endA);
    const cb = B.slice(b, endB);
    if (same(ca, co)) out.push(...cb);
    else if (same(cb, co) || same(ca, cb)) out.push(...ca);
    else return null;
    if (j < O.length) out.push(O[j]);
    o = j + 1;
    a = endA + 1;
    b = endB + 1;
  }
  return out.join('\n');
}
