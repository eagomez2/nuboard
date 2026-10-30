import { describe, expect, it } from 'vitest';
import { activeFormats, applyEdit, insertBlock, insertTable, toggle, type Format, type Sel } from '../src/lib/mdedit';

// `[` and `]` mark the selection (one `|` for a caret) in these strings
function sel(marked: string): Sel {
  if (marked.includes('|')) {
    const start = marked.indexOf('|');
    return { text: marked.replace('|', ''), start, end: start };
  }
  const start = marked.indexOf('[[');
  const text = marked.replace('[[', '').replace(']]', '');
  return { text, start, end: marked.indexOf(']]') - 2 };
}
function show(s: Sel): string {
  if (s.start === s.end) return s.text.slice(0, s.start) + '|' + s.text.slice(s.start);
  return s.text.slice(0, s.start) + '[[' + s.text.slice(s.start, s.end) + ']]' + s.text.slice(s.end);
}
const run = (marked: string, f: Format) => {
  const s = sel(marked);
  return show(applyEdit(s.text, toggle(s, f)));
};

describe('inline formats', () => {
  it('wrap the selection and select its text', () => {
    expect(run('a [[big]] cat', 'bold')).toBe('a **[[big]]** cat');
    expect(run('a [[big]] cat', 'italic')).toBe('a _[[big]]_ cat');
    expect(run('a [[big]] cat', 'underline')).toBe('a <u>[[big]]</u> cat');
    expect(run('a [[big]] cat', 'strike')).toBe('a ~~[[big]]~~ cat');
    expect(run('a [[big]] cat', 'code')).toBe('a `[[big]]` cat');
  });

  it('keep edge spaces outside and wrap the word under a caret', () => {
    expect(run('a[[ big ]]cat', 'bold')).toBe('a **[[big]]** cat');
    expect(run('a b|ig cat', 'bold')).toBe('a **b|ig** cat');
    expect(run('end |', 'bold')).toBe('end **|**');
  });

  it('toggle off when pressed inside the format, keeping the selection on the text', () => {
    expect(run('a **b|ig** cat', 'bold')).toBe('a b|ig cat');
    expect(run('a **[[big]]** cat', 'bold')).toBe('a [[big]] cat');
    expect(run('a <u>[[big]]</u> cat', 'underline')).toBe('a [[big]] cat');
    expect(run('a *b|ig* cat', 'italic')).toBe('a b|ig cat');
  });

  it('wrap each line of a multi-line selection', () => {
    expect(run('[[one\n\ntwo]]', 'bold')).toBe('[[**one**\n\n**two**]]');
  });

  it('write links and remove them', () => {
    expect(run('see [[docs]] now', 'link')).toBe('see [docs]([[https://]]) now');
    expect(run('see [do|cs](https://x.org) now', 'link')).toBe('see do|cs now');
  });
});

describe('block formats', () => {
  it('set, replace and remove headings', () => {
    expect(run('Tit|le', 'h2')).toBe('## Tit|le');
    expect(run('## Tit|le', 'h1')).toBe('# Tit|le');
    expect(run('## Tit|le', 'h2')).toBe('Tit|le');
    expect(run('## Tit|le', 'paragraph')).toBe('Tit|le');
  });

  it('turn lines into lists and back, numbering them', () => {
    expect(run('[[a\nb\nc]]', 'numbered')).toBe('[[1. a\n2. b\n3. c]]');
    expect(run('[[- a\n- b]]', 'bullet')).toBe('[[a\nb]]');
    expect(run('[[- a\n- b]]', 'check')).toBe('[[- [ ] a\n- [ ] b]]');
    expect(run('[[1. a\n2. b]]', 'quote')).toBe('[[> 1. a\n> 2. b]]');
  });

  it('wrap lines in a code fence and unwrap them', () => {
    expect(run('x = |1', 'codeblock')).toBe('```\n[[x = 1]]\n```');
    expect(run('```\nx = |1\n```', 'codeblock')).toBe('x = |1');
  });
});

describe('active formats', () => {
  const active = (marked: string) => [...activeFormats(sel(marked))].sort();
  it('reflect the formats around the caret', () => {
    expect(active('## a **b|c** d')).toEqual(['bold', 'h2']);
    expect(active('- [ ] _ta|sk_')).toEqual(['check', 'italic']);
    expect(active('plain |text')).toEqual(['paragraph']);
    expect(active('```\ncode|\n```')).toEqual(['codeblock']);
    expect(active('a [li|nk](u) <u>b</u>')).toEqual(['link', 'paragraph']);
  });
});

describe('inserted blocks', () => {
  it('go on their own paragraph after the current line', () => {
    const s = sel('Intro| text\nNext');
    expect(applyEdit(s.text, insertBlock(s, '![x](files/a.png)')).text).toBe('Intro text\n\n![x](files/a.png)\n\nNext');
    const e = sel('Intro\n\n|\n\nNext');
    expect(applyEdit(e.text, insertBlock(e, '---')).text).toBe('Intro\n\n---\n\nNext');
    const end = sel('Intro|');
    expect(applyEdit(end.text, insertBlock(end, '---')).text).toBe('Intro\n\n---\n');
  });

  it('build tables of the picked size with the first header selected', () => {
    const s = sel('|');
    const out = applyEdit(s.text, insertTable(s, 2, 3));
    expect(out.text).toBe(
      '| Column 1 | Column 2 | Column 3 |\n| --- | --- | --- |\n|     |     |     |\n|     |     |     |\n',
    );
    expect(out.text.slice(out.start, out.end)).toBe('Column 1');
  });
});
