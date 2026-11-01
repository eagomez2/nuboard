import { describe, expect, it } from 'vitest';
import {
  describeZones,
  fmtOffset,
  machineZones,
  makeZone,
  offsetFromRunId,
  offsetPref,
  parseZone,
} from '../src/lib/tz';

const utc = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0) => Date.UTC(y, mo - 1, d, h, mi, s) / 1000;
const H = 3600;

describe('makeZone offsets', () => {
  it('follows daylight saving at each moment, not today', () => {
    const santiago = makeZone({ id: 'America/Santiago' });
    expect(santiago.offsetAt(utc(2026, 1, 15, 12))).toBe(-3 * H);
    expect(santiago.offsetAt(utc(2026, 7, 15, 12))).toBe(-4 * H);
    const berlin = makeZone({ id: 'Europe/Berlin' });
    expect(berlin.offsetAt(utc(2026, 1, 15))).toBe(1 * H);
    expect(berlin.offsetAt(utc(2026, 7, 15))).toBe(2 * H);
  });

  it('switches exactly at the transition', () => {
    // Europe/Berlin: 2026-03-29 01:00 UTC, clocks go from 02:00 to 03:00
    const berlin = makeZone({ id: 'Europe/Berlin' });
    expect(berlin.offsetAt(utc(2026, 3, 29, 0, 59, 59))).toBe(1 * H);
    expect(berlin.offsetAt(utc(2026, 3, 29, 1, 0, 0))).toBe(2 * H);
  });

  it('handles half-hour daylight saving and quarter-hour zones', () => {
    const lordHowe = makeZone({ id: 'Australia/Lord_Howe' });
    expect(lordHowe.offsetAt(utc(2026, 1, 15))).toBe(11 * H);
    expect(lordHowe.offsetAt(utc(2026, 7, 15))).toBe(10.5 * H);
    expect(makeZone({ id: 'Asia/Kathmandu' }).offsetAt(utc(2026, 1, 15))).toBe(5.75 * H);
  });

  it('keeps a fixed offset all year', () => {
    const fixed = makeZone({ offset: -3 * H });
    expect(fixed.offsetAt(utc(2026, 1, 15))).toBe(-3 * H);
    expect(fixed.offsetAt(utc(2026, 7, 15))).toBe(-3 * H);
    expect(fixed.name).toBe('UTC−03:00');
  });
});

describe('makeZone format', () => {
  const opts: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  };

  it('matches Intl with the same zone for any moment', () => {
    for (const id of [
      'America/Santiago',
      'Europe/Berlin',
      'Asia/Kathmandu',
      'Australia/Lord_Howe',
      'America/New_York',
    ]) {
      const kit = makeZone({ id });
      const ref = new Intl.DateTimeFormat(undefined, { ...opts, timeZone: id });
      for (let i = 0; i < 400; i++) {
        const t = utc(2024, 1, 1) + Math.floor(i * 197_531.7); // about 2.5 years, at odd times
        expect(kit.format(t, opts)).toBe(ref.format(new Date(t * 1000)));
      }
    }
  });

  it('writes a fixed offset by plain arithmetic', () => {
    const kit = makeZone({ offset: 5.5 * H });
    expect(kit.format(utc(2026, 10, 13, 20, 0), { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })).toBe(
      '01:30',
    );
  });
});

describe('fromWall', () => {
  it('round-trips ordinary times', () => {
    const kit = makeZone({ id: 'America/Santiago' });
    const t = utc(2026, 10, 13, 10, 20);
    expect(kit.fromWall(t + kit.offsetAt(t))).toBe(t);
  });

  it('maps a skipped wall time to just after the gap', () => {
    const berlin = makeZone({ id: 'Europe/Berlin' });
    // 02:30 local on 2026-03-29 does not exist
    const t = berlin.fromWall(utc(2026, 3, 29, 2, 30));
    expect(berlin.format(t, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })).toBe('03:30');
  });
});

describe('ticks', () => {
  it('puts day ticks on local midnights across a clock change', () => {
    const berlin = makeZone({ id: 'Europe/Berlin' });
    const ticks = berlin.ticks(utc(2026, 3, 26), utc(2026, 4, 2), 10);
    expect(ticks.length).toBeGreaterThan(4);
    for (const t of ticks) {
      expect(t.day).toBe(true);
      expect(berlin.format(t.t, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })).toBe('00:00');
    }
    const gaps = ticks.slice(1).map((t, i) => t.t - ticks[i].t);
    expect(gaps).toContain(23 * H); // the day the clocks go forward is 23 hours long
  });

  it('skips the hour that does not exist and never repeats a tick', () => {
    const berlin = makeZone({ id: 'Europe/Berlin' });
    const ticks = berlin.ticks(utc(2026, 3, 28, 22), utc(2026, 3, 29, 6), 10);
    const labels = ticks.map((t) => t.label);
    expect(labels).not.toContain('02:00');
    expect(new Set(ticks.map((t) => t.t)).size).toBe(ticks.length);
  });

  it('labels the same moment the same way the formatter does', () => {
    const kit = makeZone({ id: 'America/Santiago' });
    for (const t of kit.ticks(utc(2026, 10, 13, 0), utc(2026, 10, 13, 12), 12)) {
      if (!t.day) expect(t.label).toBe(kit.format(t.t, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }));
    }
  });

  it('uses calendar months for long ranges', () => {
    const kit = makeZone({ id: 'America/Santiago' });
    const ticks = kit.ticks(utc(2025, 11, 20), utc(2026, 6, 20), 8);
    expect(ticks[0].label).toBe('Dec');
    expect(ticks[1]).toMatchObject({ label: '2026', day: true }); // January
    for (const t of ticks)
      expect(kit.format(t.t, { day: 'numeric', hour: '2-digit', hourCycle: 'h23' })).toMatch(/^1,? 00$/);
  });
});

describe('parseZone', () => {
  it('reads every kind of preference', () => {
    expect(parseZone('UTC')).toEqual({ offset: 0 });
    expect(parseZone('UTC-03:00')).toEqual({ offset: -3 * H });
    expect(parseZone('UTC−03:00')).toEqual({ offset: -3 * H });
    expect(parseZone('utc+5:30')).toEqual({ offset: 5.5 * H });
    expect(parseZone('America/Santiago')).toEqual({ id: 'America/Santiago' });
    expect('id' in parseZone('browser')).toBe(true);
  });

  it('falls back to the browser zone for anything unknown', () => {
    const browser = parseZone('browser');
    expect(parseZone('Mars/Olympus')).toEqual(browser);
    expect(parseZone('UTC+99:00')).toEqual(browser);
  });

  it('writes offsets both ways', () => {
    expect(fmtOffset(-10800)).toBe('UTC−03:00');
    expect(fmtOffset(20700)).toBe('UTC+05:45');
    expect(offsetPref(-10800)).toBe('UTC-03:00');
  });
});

describe('machine zone', () => {
  it('reads the offset from the run id of an older run', () => {
    // the machine's local time was 07:20 when it was 10:20:37 UTC
    expect(offsetFromRunId('20261013T0720-755037e9', utc(2026, 10, 13, 10, 20, 37))).toBe(-3 * H);
    expect(offsetFromRunId('20251001-0930_baseline_ab12cd', utc(2025, 10, 1, 7, 30, 59))).toBe(2 * H);
    expect(offsetFromRunId('20261013T0720-755037e9', utc(2026, 10, 13, 1, 50, 2))).toBe(5.5 * H);
    expect(offsetFromRunId('my-custom-id', utc(2026, 10, 13))).toBeNull();
    expect(offsetFromRunId('20261013T0720-755037e9', utc(2026, 10, 20))).toBeNull(); // a week off: not an offset
  });

  it('uses the recorded offsets of each session', () => {
    const meta = {
      created: utc(2026, 10, 13, 10, 20),
      sessions: [
        { session: 0, started: 1, ended: 2, utc_offset: -10800, utc_offset_end: -10800, host: 'lab' },
        { session: 1, started: 3, ended: null, utc_offset: 3600, host: 'cluster' },
      ],
    };
    const zones = machineZones(meta, '20261013T0720-755037e9');
    expect(zones.map((z) => [z.offset, z.host, z.derived])).toEqual([
      [-10800, 'lab', false],
      [3600, 'cluster', false],
    ]);
    expect(describeZones(zones)).toBe('session 0: UTC−03:00 · lab; session 1: UTC+01:00 · cluster');
  });

  it('flags a clock change during a session', () => {
    const meta = { sessions: [{ session: 0, started: 1, ended: 2, utc_offset: -10800, utc_offset_end: -14400 }] };
    expect(describeZones(machineZones(meta, 'x'))).toBe('UTC−03:00 → UTC−04:00 (clock change)');
  });

  it('falls back to the run id for older runs, first session only', () => {
    const meta = {
      created: utc(2026, 10, 13, 10, 20, 37),
      env: { host: 'lab' },
      sessions: [
        { session: 0, started: utc(2026, 10, 13, 10, 20, 37), ended: 2 },
        { session: 1, started: 3, ended: 4 },
      ],
    };
    const zones = machineZones(meta, '20261013T0720-755037e9');
    expect(zones[0]).toMatchObject({ offset: -10800, derived: true, host: 'lab' });
    expect(zones[1]).toMatchObject({ offset: null, derived: false });
    expect(describeZones(zones)).toBe(
      'session 0: ≈ UTC−03:00 (from run id) · lab; session 1: unknown (not recorded by older versions)',
    );
  });

  it('leaves TensorBoard imports unknown', () => {
    const meta = {
      created: utc(2026, 10, 13, 10, 20, 37),
      notes: 'Imported from TensorBoard logs in /data/tb',
      sessions: [{ session: 0, started: 1, ended: 2 }],
    };
    expect(describeZones(machineZones(meta, '20261013T0720-755037e9'), true)).toBe('unknown (imported run)');
  });
});

describe('machineOffsetAt', () => {
  it('picks the session that was running at each time', async () => {
    const { machineOffsetAt } = await import('../src/lib/tz');
    const zones = machineZones(
      {
        sessions: [
          { session: 0, started: 100, utc_offset: -10800 },
          { session: 1, started: 500, utc_offset: 3600 },
        ],
      },
      'x',
    );
    expect(machineOffsetAt(zones, 50)).toBe(-10800);
    expect(machineOffsetAt(zones, 300)).toBe(-10800);
    expect(machineOffsetAt(zones, 500)).toBe(3600);
    expect(machineOffsetAt(zones, 9000)).toBe(3600);
  });
});
