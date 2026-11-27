import { describe, expect, it } from 'vitest';
import { chartFileNames, pngBytes } from '../src/lib/chartfiles';

describe('picked charts in a .zip', () => {
  it('names each PNG after its scalar, safe on every platform', () => {
    expect(chartFileNames(['train/loss', 'val/acc', 'lr'])).toEqual(['train_loss.png', 'val_acc.png', 'lr.png']);
    expect(chartFileNames(['a:b*c?', ' /x/ '])).toEqual(['a_b_c.png', 'x.png']);
  });

  it('keeps names apart when two scalars map to one, ignoring case', () => {
    expect(chartFileNames(['a/b', 'a_b', 'A_B'])).toEqual(['a_b.png', 'a_b-2.png', 'A_B-3.png']);
    expect(chartFileNames(['///'])).toEqual(['chart.png']);
  });

  it('decodes the bytes of a PNG data URL', () => {
    const bytes = pngBytes('data:image/png;base64,iVBORw0KGgo=');
    expect([...bytes]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });
});
