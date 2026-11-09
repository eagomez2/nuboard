import { describe, expect, it } from 'vitest';
import { tailName } from '../src/lib/format';

describe('tailName', () => {
  it('keeps short names and cuts long ones from the start, at a slash when it can', () => {
    expect(tailName('val/acc', 20)).toBe('val/acc');
    expect(tailName('timing/callbacks/EarlyStopping.on_val_end', 28)).toBe('…/EarlyStopping.on_val_end');
    expect(tailName('a_very_long_metric_name_without_slashes', 12)).toBe('…out_slashes');
    expect(tailName('timing/callbacks/EarlyStopping.on_val_end', 28).length).toBeLessThanOrEqual(28);
  });
});
