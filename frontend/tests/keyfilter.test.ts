import { describe, expect, it } from 'vitest';
import { keyFilter, splitMarked } from '../src/lib/keyfilter';

const keys = [
  'config.optim.lr',
  'config.optim.name',
  'config.generator.config.weighted_sir_db.edge.min',
  'config.generator.config.weighted_sir_db.edge.max',
  'config.logging.debug',
  'last.train/loss',
];
const pick = (text: string, opts = {}) => keys.filter((k) => keyFilter(text, opts).test(k));

describe('settings key filter', () => {
  it('matches substrings ignoring case, and ANDs terms', () => {
    expect(pick('EDGE.min')).toEqual(['config.generator.config.weighted_sir_db.edge.min']);
    expect(pick('optim lr')).toEqual(['config.optim.lr']);
    expect(pick('')).toEqual(keys);
  });

  it('treats text in slashes, or every term with the regex toggle, as a regular expression', () => {
    expect(pick('/^config\\.generator\\..*\\.(min|max)$/')).toHaveLength(2);
    expect(pick('/optim\\.(lr|name)$/')).toEqual(['config.optim.lr', 'config.optim.name']);
    expect(pick('^last\\.', { regex: true })).toEqual(['last.train/loss']);
    expect(pick('a.b')).toEqual([]); // plain text: the dot is literal
  });

  it('excludes with a leading !', () => {
    expect(pick('config !generator !logging')).toEqual(['config.optim.lr', 'config.optim.name']);
    expect(pick('!/^config/')).toEqual(['last.train/loss']);
  });

  it('matches values only when asked', () => {
    expect(keyFilter('adamw').test('config.optim.name', ['adamw'])).toBe(false);
    expect(keyFilter('adamw', { values: true }).test('config.optim.name', ['adamw', 'sgd'])).toBe(true);
  });

  it('reports an invalid regex and lets everything pass', () => {
    const f = keyFilter('/(unclosed/');
    expect(f.error).toBeTruthy();
    expect(keys.every((k) => f.test(k))).toBe(true);
  });

  it('highlights what the including terms match', () => {
    const f = keyFilter('optim !name /l.$/');
    expect(f.highlight('config.optim.lr')).toEqual([
      [7, 12],
      [13, 15],
    ]);
    expect(splitMarked('config.optim.lr', f.highlight('config.optim.lr'))).toEqual([
      { text: 'config.', mark: false },
      { text: 'optim', mark: true },
      { text: '.', mark: false },
      { text: 'lr', mark: true },
    ]);
  });
});
