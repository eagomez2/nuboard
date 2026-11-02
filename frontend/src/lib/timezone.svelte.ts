// The viewer's display time zone: a per-viewer preference kept in localStorage.
// It changes how wall-clock times are written, never the data, queries or URLs.
//
// The default, "browser" ("Local time"), is the viewer's own zone, as before. "machine"
// shows each run on the clock of the machine that recorded it (the UTC offset saved
// with each session). Anything else is one zone for everything (see `parseZone`).
import { browserZone, machineOffsetAt, machineZones, makeZone, parseZone, type SessionZone, type ZoneKit } from './tz';

const KEY = 'timeZone';
export const MACHINE = 'machine';
export const LOCAL = 'browser';

function load(): string {
  try {
    const raw = localStorage.getItem(KEY);
    return raw === null ? LOCAL : (JSON.parse(raw) as string);
  } catch {
    return LOCAL;
  }
}

/** What a run brief or run.json tells about the machine(s) it ran on. */
export interface RunZoneInfo {
  id: string;
  created?: number | null;
  notes?: string;
  host?: string | null;
  sessions?: Record<string, any>[];
}

/** How times shared by several runs (an axis, a read-out) are written. */
export interface SharedZone {
  kit: ZoneKit;
  /** Why this zone, for a caption: `machine time`, `runs from different zones`, `local time`, or ''. */
  note: string;
}

class TimeZoneState {
  /** `browser` (default), `machine`, `UTC`, a fixed offset such as `UTC-03:00`, or an IANA zone. */
  pref = $state(load());
  machine = $derived(this.pref === MACHINE);
  /** The zone picked for everything; the browser's own zone in machine mode. */
  kit: ZoneKit = $derived(makeZone(parseZone(this.machine ? 'browser' : this.pref)));
  /** The browser's own zone, for comparison. */
  readonly browser = browserZone();
  browserKit: ZoneKit = makeZone({ id: this.browser });
  private fixed = new Map<number, ZoneKit>();
  private zones = new WeakMap<object, SessionZone[]>();
  readonly utc = makeZone({ offset: 0 });

  set(pref: string) {
    this.pref = pref || LOCAL;
    try {
      localStorage.setItem(KEY, JSON.stringify(this.pref));
    } catch {
      /* private mode: the choice just doesn't persist */
    }
  }

  /** Whether the picked zone writes times differently from the browser's clock at `t`. */
  differs(t = Date.now() / 1000): boolean {
    return !this.machine && this.kit.offsetAt(t) !== this.browserKit.offsetAt(t);
  }

  /** The sessions and machine zones of a run (cached per run object). */
  zonesOf(run: RunZoneInfo): SessionZone[] {
    let z = this.zones.get(run);
    if (!z) {
      z = machineZones(
        { created: run.created, notes: run.notes, env: { host: run.host }, sessions: run.sessions },
        run.id,
      );
      this.zones.set(run, z);
    }
    return z;
  }

  private offsetKit(offset: number): ZoneKit {
    let k = this.fixed.get(offset);
    if (!k) {
      k = makeZone({ offset });
      this.fixed.set(offset, k);
    }
    return k;
  }

  /**
   * The kit for time `t` of `run`: the machine's clock in machine mode (the local
   * zone when the machine's is not known), else the picked zone. `known` is false
   * when machine time was asked for but is not known.
   */
  kitAt(t: number, run?: RunZoneInfo | null): { kit: ZoneKit; known: boolean } {
    if (!this.machine) return { kit: this.kit, known: true };
    if (!run) return { kit: this.browserKit, known: false };
    const off = machineOffsetAt(this.zonesOf(run), t);
    return off === null ? { kit: this.browserKit, known: false } : { kit: this.offsetKit(off), known: true };
  }

  /**
   * One zone for an axis or read-out shared by `runs`. In machine mode it is their
   * machines' zone when they all share one, UTC when they differ, and local time
   * when none is known.
   */
  shared(runs: (RunZoneInfo | null | undefined)[]): SharedZone {
    if (!this.machine) return { kit: this.kit, note: '' };
    const offsets = new Set<number>();
    let unknown = false;
    for (const r of runs) {
      if (!r) continue;
      for (const z of this.zonesOf(r)) {
        if (z.offset === null) unknown = true;
        else offsets.add(z.offset);
      }
    }
    if (offsets.size === 1 && !unknown) return { kit: this.offsetKit([...offsets][0]), note: 'machine time' };
    if (!offsets.size) return { kit: this.browserKit, note: 'local time, machine zone unknown' };
    return { kit: this.utc, note: 'runs from different zones' };
  }
}

export const timeZone = new TimeZoneState();
