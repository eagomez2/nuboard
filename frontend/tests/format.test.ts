import { describe, expect, it } from 'vitest';
import { chartMetric, tailName } from '../src/lib/format';

describe('tailName', () => {
  it('keeps short names and cuts long ones from the start, at a slash when it can', () => {
    expect(tailName('val/acc', 20)).toBe('val/acc');
    expect(tailName('timing/callbacks/EarlyStopping.on_val_end', 28)).toBe('…/EarlyStopping.on_val_end');
    expect(tailName('a_very_long_metric_name_without_slashes', 12)).toBe('…out_slashes');
    expect(tailName('timing/callbacks/EarlyStopping.on_val_end', 28).length).toBeLessThanOrEqual(28);
  });
});

describe('chartMetric', () => {
  it('prefers a loss among the scalars most runs logged', () => {
    expect(
      chartMetric([
        { name: 'acc', runs: 10 },
        { name: 'train/loss', runs: 10 },
      ]),
    ).toBe('train/loss');
  });
  it('skips a loss that only a few runs logged', () => {
    const counts = [
      { name: 'loss', runs: 3 },
      { name: 'train/loss', runs: 57 },
      { name: 'lr', runs: 60 },
    ];
    expect(chartMetric(counts)).toBe('train/loss');
  });
  it('takes the most logged scalar when no loss is common', () => {
    expect(
      chartMetric([
        { name: 'loss', runs: 1 },
        { name: 'acc', runs: 9 },
        { name: 'f1', runs: 10 },
      ]),
    ).toBe('f1');
  });
  it('takes a scalar the newest run logged', () => {
    const counts = [
      { name: 'loss', runs: 4 },
      { name: 'train/loss', runs: 4 },
      { name: 'acc', runs: 7 },
    ];
    expect(chartMetric(counts)).toBe('loss');
    expect(chartMetric(counts, ['train/loss', 'acc'])).toBe('train/loss');
    expect(chartMetric(counts, ['other'])).toBe('loss'); // nothing shared: as without it
  });
  it('is empty without scalars', () => {
    expect(chartMetric([])).toBe('');
  });
});
