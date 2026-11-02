// Time zones for display. Every stored time is Unix seconds (UTC); a zone only
// changes how those seconds are written out. Everything that shows a wall-clock
// time goes through one `ZoneKit`, so all views agree.

/** A named IANA zone (follows daylight saving), or a fixed offset east of UTC in seconds. */
export type ZoneSpec = { id: string } | { offset: number };

export interface Tick {
  t: number;
  label: string;
  /** A day (or month, year) boundary, drawn stronger. */
  day: boolean;
}

export interface ZoneKit {
  spec: ZoneSpec;
  /** The zone's name: an IANA id, `UTC` or `UTC−03:00`. */
  name: string;
  /** The zone's offset from UTC at Unix time `t`, in seconds. */
  offsetAt(t: number): number;
  /** Unix time of the wall-clock time `wall` (seconds since 1970-01-01 00:00 on the zone's clock). */
  fromWall(wall: number): number;
  /** Format `t` with `Intl.DateTimeFormat` options; `timeZone` is set by the kit. */
  format(t: number, opts: Intl.DateTimeFormatOptions): string;
  /** The zone's short name at `t`, such as `CLT`, `GMT-3` or `UTC+01:00`. */
  abbr(t: number): string;
  /** Axis ticks between `lo` and `hi`, at most about `room` of them, on the zone's clock. */
  ticks(lo: number, hi: number, room: number): Tick[];
}

/**
 * Build the kit for a zone.
 *
 * Self-contained on purpose (no imports, no outer names): exported reports inline
 * it with `toString()`, so their charts read times the same way as the viewer.
 * Formatting shifts the instant by the zone's offset and writes it out in UTC,
 * one code path for named zones and fixed offsets alike.
 */
export function makeZone(spec: ZoneSpec): ZoneKit {
  const pad = (n: number) => String(n).padStart(2, '0');
  const offsetName = (s: number) =>
    s === 0
      ? 'UTC'
      : `UTC${s < 0 ? '−' : '+'}${pad(Math.floor(Math.abs(s) / 3600))}:${pad(Math.floor((Math.abs(s) % 3600) / 60))}`;
  const formats = new Map<string, Intl.DateTimeFormat>();
  const formatter = (key: string, opts: Intl.DateTimeFormatOptions) => {
    let f = formats.get(key);
    if (!f) {
      f = new Intl.DateTimeFormat(undefined, opts);
      formats.set(key, f);
    }
    return f;
  };

  let offsetAt: (t: number) => number;
  let abbr: (t: number) => string;
  let name: string;

  if ('offset' in spec) {
    const fixed = spec.offset;
    name = offsetName(fixed);
    offsetAt = () => fixed;
    abbr = () => name;
  } else {
    const id = spec.id;
    name = id;
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: id,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
    });
    // Offsets change only on whole quarter hours of UTC, so one lookup per quarter hour is exact.
    const cache = new Map<number, number>();
    offsetAt = (t: number) => {
      const q = Math.floor(t / 900);
      let off = cache.get(q);
      if (off === undefined) {
        const at = q * 900;
        const p: Record<string, number> = {};
        for (const x of parts.formatToParts(new Date(at * 1000))) if (x.type !== 'literal') p[x.type] = Number(x.value);
        const wall = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second) / 1000;
        off = Math.round((wall - at) / 60) * 60;
        if (cache.size > 5000) cache.clear();
        cache.set(q, off);
      }
      return off;
    };
    const short = new Intl.DateTimeFormat(undefined, { timeZone: id, timeZoneName: 'short' });
    abbr = (t: number) => {
      const p = short.formatToParts(new Date(t * 1000)).find((x) => x.type === 'timeZoneName');
      return p ? p.value : offsetName(offsetAt(t));
    };
  }

  // A wall-clock time that happens twice (clocks set back) maps to the first; one that
  // never happens (clocks set forward) maps to just after the gap.
  const fromWall = (wall: number) => {
    let t = wall - offsetAt(wall);
    t = wall - offsetAt(t);
    return t;
  };

  const format = (t: number, opts: Intl.DateTimeFormatOptions) => {
    const key = JSON.stringify(opts);
    return formatter(key, { ...opts, timeZone: 'UTC' }).format(new Date((t + offsetAt(t)) * 1000));
  };

  const ticks = (lo: number, hi: number, room: number): Tick[] => {
    const out: Tick[] = [];
    if (!(hi > lo)) return out;
    const span = hi - lo;
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 3 * 3600, 6 * 3600, 12 * 3600];
    const daySteps = [1, 2, 7];
    room = Math.max(2, room);
    const step = steps.find((s) => span / s <= room);
    const dayLabel = (t: number) => format(t, { month: 'short', day: 'numeric' });
    if (step !== undefined) {
      const time = (t: number) =>
        format(
          t,
          step < 60
            ? { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }
            : { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' },
        );
      let wall = Math.ceil((lo + offsetAt(lo)) / step) * step;
      for (let n = 0; n < 1000; n++, wall += step) {
        const t = fromWall(wall);
        if (t > hi) break;
        if (t < lo || (out.length && out[out.length - 1].t === t)) continue;
        const midnight = wall % 86400 === 0;
        out.push({ t, day: midnight, label: midnight ? dayLabel(t) : time(t) });
      }
      return out;
    }
    const days = daySteps.find((d) => span / (d * 86400) <= room);
    if (days !== undefined) {
      let wall = Math.ceil((lo + offsetAt(lo)) / 86400) * 86400;
      if (days === 7) {
        // weeks start on Monday (1970-01-01 was a Thursday)
        const dow = (Math.floor(wall / 86400) + 3) % 7;
        if (dow) wall += (7 - dow) * 86400;
      }
      for (let n = 0; n < 1000; n++, wall += days * 86400) {
        const t = fromWall(wall);
        if (t > hi) break;
        if (t >= lo) out.push({ t, day: true, label: dayLabel(t) });
      }
      return out;
    }
    // months, quarters or years, on calendar boundaries
    const months = [1, 3, 6, 12, 24, 60].find((m) => span / (m * 30.44 * 86400) <= room) ?? 120;
    const start = new Date((lo + offsetAt(lo)) * 1000);
    let y = start.getUTCFullYear();
    let m =
      Math.ceil(
        (start.getUTCMonth() + (start.getUTCDate() > 1 || start.getUTCHours() || start.getUTCMinutes() ? 1 : 0)) /
          months,
      ) * months;
    for (let n = 0; n < 1000; n++) {
      y += Math.floor(m / 12);
      m %= 12;
      const t = fromWall(Date.UTC(y, m, 1) / 1000);
      if (t > hi) break;
      if (t >= lo)
        out.push({ t, day: m === 0, label: months >= 12 || m === 0 ? String(y) : format(t, { month: 'short' }) });
      m += months;
    }
    return out;
  };

  return { spec, name, offsetAt, fromWall, format, abbr, ticks };
}

/** An offset in seconds as `UTC−03:00`, `UTC+05:30` or `UTC`. */
export function fmtOffset(s: number): string {
  if (s === 0) return 'UTC';
  const a = Math.abs(s);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `UTC${s < 0 ? '−' : '+'}${pad(Math.floor(a / 3600))}:${pad(Math.floor((a % 3600) / 60))}`;
}

/** The browser's own zone, such as `America/Santiago`. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Whether `id` is a zone this browser knows. */
export function isZone(id: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: id });
    return true;
  } catch {
    return false;
  }
}

const FIXED = /^UTC\s*([+\-−])\s*(\d{1,2})(?::?(\d{2}))?$/i;

/**
 * Read a saved preference: `browser`, `UTC`, a fixed offset such as `UTC-03:00`,
 * or an IANA zone. Anything else (a zone this browser does not know) is the
 * browser's zone.
 */
export function parseZone(pref: string | null | undefined): ZoneSpec {
  const p = (pref ?? '').trim();
  if (!p || p === 'browser') return { id: browserZone() };
  if (/^(utc|gmt|z)$/i.test(p)) return { offset: 0 };
  const m = FIXED.exec(p);
  if (m) {
    const s = (Number(m[2]) * 3600 + Number(m[3] ?? 0) * 60) * (m[1] === '+' ? 1 : -1);
    if (Math.abs(s) <= 14 * 3600 && Number(m[3] ?? 0) < 60) return { offset: s };
  }
  return isZone(p) ? { id: p } : { id: browserZone() };
}

/** The preference text for a fixed offset, such as `UTC-03:00` (ASCII, so it can be typed). */
export function offsetPref(s: number): string {
  return fmtOffset(s).replace('−', '-');
}

/** Every IANA zone this browser knows, for the picker. */
export function allZones(): string[] {
  try {
    const list = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone');
    if (list?.length) return list;
  } catch {
    /* older browser */
  }
  return [browserZone(), 'UTC'];
}

/** What a run's `sessions` entry says about the machine it ran on. */
export interface SessionZone {
  session: number;
  /** When the session started, in Unix seconds; null when unknown. */
  started: number | null;
  /** The machine's UTC offset in seconds when the session started; null when unknown. */
  offset: number | null;
  /** The offset at `finish`, when recorded. */
  offsetEnd: number | null;
  host: string | null;
  /** Worked out from the run id, not recorded (runs from before offsets were recorded). */
  derived: boolean;
}

const ID_STAMP = /^(\d{4})(\d{2})(\d{2})[T-](\d{2})(\d{2})(?:[-_]|$)/;

/**
 * The machine's UTC offset at `init`, worked out from the run id.
 *
 * The id starts with the machine's local time at `init` to the minute
 * (`20261013T0720-…`, or `20261013-0720_…` before 0.17) and `created` is the
 * same moment in Unix seconds, so their difference, to the nearest quarter
 * hour, is the offset. Null when the id has no such stamp or the result is not
 * a real offset.
 */
export function offsetFromRunId(runId: string, created: number | null | undefined): number | null {
  const m = ID_STAMP.exec(runId);
  if (!m || !created || !Number.isFinite(created)) return null;
  const [y, mo, d, h, mi] = m.slice(1).map(Number);
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59) return null;
  const wall = Date.UTC(y, mo - 1, d, h, mi) / 1000;
  // the stamp is the local minute, so local time lies in [wall, wall + 60)
  const off = Math.round((wall + 30 - created) / 900) * 900;
  return Math.abs(off) <= 14 * 3600 ? off : null;
}

/**
 * The zone and host of each session of a run, from its run.json.
 *
 * Runs recorded by this version carry `utc_offset` (and `utc_offset_end`,
 * `host`) in each `sessions` entry. Older runs fall back to the offset in the
 * run id, for their first session only. TensorBoard imports carry the
 * importing machine's clock in their id, so they stay unknown.
 */
export function machineZones(meta: Record<string, any> | null | undefined, runId: string): SessionZone[] {
  const sessions: Record<string, any>[] = Array.isArray(meta?.sessions) ? meta!.sessions : [];
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  if (sessions.some((s) => num(s?.utc_offset) !== null)) {
    return sessions.map((s, i) => ({
      session: num(s?.session) ?? i,
      started: num(s?.started),
      offset: num(s?.utc_offset),
      offsetEnd: num(s?.utc_offset_end),
      host: typeof s?.host === 'string' ? s.host : null,
      derived: false,
    }));
  }
  const imported = typeof meta?.notes === 'string' && meta.notes.startsWith('Imported from TensorBoard');
  const created = num(meta?.created) ?? num(sessions[0]?.started);
  const first = imported ? null : offsetFromRunId(runId, created);
  const host = typeof meta?.env?.host === 'string' ? meta.env.host : null;
  const list = sessions.length ? sessions : [{}];
  return list.map((s, i) => ({
    session: num(s?.session) ?? i,
    started: num(s?.started) ?? (i === 0 ? created : null),
    offset: i === 0 ? first : null,
    offsetEnd: null,
    host: i === 0 ? host : null,
    derived: i === 0 && first !== null,
  }));
}

/** One line per session for run details, such as `UTC−03:00 · gpu-01`. */
export function describeZones(zones: SessionZone[], imported = false): string {
  const one = (z: SessionZone) => {
    if (z.offset === null) return imported ? 'unknown (imported run)' : 'unknown (not recorded by older versions)';
    let s = z.derived ? `≈ ${fmtOffset(z.offset)} (from run id)` : fmtOffset(z.offset);
    if (z.offsetEnd !== null && z.offsetEnd !== z.offset) s += ` → ${fmtOffset(z.offsetEnd)} (clock change)`;
    if (z.host) s += ` · ${z.host}`;
    return s;
  };
  if (zones.length <= 1) return zones.length ? one(zones[0]) : 'unknown';
  return zones.map((z) => `session ${z.session}: ${one(z)}`).join('; ');
}

/**
 * The machine's UTC offset at Unix time `t`: that of the latest session started
 * by then (the first session for earlier times). Null when it is not known.
 */
export function machineOffsetAt(zones: SessionZone[], t: number): number | null {
  let at = zones[0];
  for (const z of zones) if (z.started !== null && z.started <= t) at = z;
  return at ? at.offset : null;
}
