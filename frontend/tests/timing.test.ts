import { describe, expect, it } from 'vitest';
import { fmtCount, fmtSeconds } from '../src/lib/format';
import { reservedPrefixes, sectionOf } from '../src/lib/prefixes';

describe('fmtSeconds', () => {
  it('writes durations with the precision timers need', () => {
    expect(fmtSeconds(0.00042)).toBe('420 µs');
    expect(fmtSeconds(0.0031)).toBe('3.1 ms');
    expect(fmtSeconds(0.803)).toBe('803 ms');
    expect(fmtSeconds(41.04)).toBe('41 s');
    expect(fmtSeconds(9.296)).toBe('9.3 s');
    expect(fmtSeconds(59.99)).toBe('60 s');
    expect(fmtSeconds(82)).toBe('1m 22s');
    expect(fmtSeconds(3599.6)).toBe('1h 00m');
    expect(fmtSeconds(4140)).toBe('1h 09m');
    expect(fmtSeconds(90000)).toBe('1d 1h');
    expect(fmtSeconds(null)).toBe('—');
  });
});

describe('fmtCount', () => {
  it('shortens large call counts', () => {
    expect(fmtCount(101)).toBe('101');
    expect(fmtCount(49_490)).toBe('49.5k');
    expect(fmtCount(1_040_000)).toBe('1.04M');
    expect(fmtCount(3.2e9)).toBe('3.2B');
  });
});

describe('reservedPrefixes', () => {
  it('collects each run’s own prefixes, with the defaults when unset', () => {
    const runs = [{ prefixes: { system: 'sys', timing: 'perf' } }, {}] as never[];
    const r = reservedPrefixes(runs);
    expect([...r.timing].sort()).toEqual(['perf', 'timing']);
    expect([...r.system].sort()).toEqual(['sys', 'system']);
    expect(sectionOf('timing/train/epoch')).toBe('timing');
    expect(sectionOf('loss')).toBe('other');
  });
});
