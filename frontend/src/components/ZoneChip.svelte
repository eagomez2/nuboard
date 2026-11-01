<script lang="ts">
  import { ask, notice } from '../lib/dialog.svelte';
  import { LOCAL, MACHINE, timeZone } from '../lib/timezone.svelte';
  import { allZones, fmtOffset, makeZone, offsetPref, parseZone } from '../lib/tz';

  // The zone times are shown in. Optional: by default ("Local time") times read as they
  // always have, in this browser's zone. "Machine time" shows each run on the clock of
  // the machine that recorded it; any other pick is one zone for everything. Only how
  // times are written changes; data, queries and links stay the same. A dot marks a
  // picked zone that differs from the browser's.
  let now = $state(Date.now() / 1000);
  $effect(() => {
    const timer = setInterval(() => (now = Date.now() / 1000), 60_000);
    return () => clearInterval(timer);
  });

  const kit = $derived(timeZone.kit);
  const isMachine = $derived(timeZone.pref === MACHINE);
  const isLocal = $derived(timeZone.pref === LOCAL);
  const differs = $derived(!isLocal && timeZone.differs(now));
  const browserNow = $derived(`${timeZone.browser}, ${fmtOffset(timeZone.browserKit.offsetAt(now))}`);
  const short = $derived(kit.abbr(now));
  const place = $derived('id' in kit.spec ? kit.spec.id.split('/').pop()!.replaceAll('_', ' ') : '');
  const title = $derived(
    isMachine
      ? "Machine time: each run's times are shown on the clock of the machine that recorded it, as saved with the run. " +
          'An axis shared by runs from different zones is in UTC, and says so. Runs whose machine zone is unknown ' +
          `show local time (${browserNow}), marked "(local)". Click to change, or pick Local time to go back.`
      : isLocal
        ? `Local time: times are shown as they always have been, in this browser's time zone (${browserNow}). ` +
          "Nothing is converted. Click to show them in another zone or on each machine's clock (optional)."
        : `Times are shown in ${kit.name}${'id' in kit.spec ? ` (${fmtOffset(kit.offsetAt(now))} now)` : ''}` +
          (differs ? `, not in this browser's zone (${browserNow})` : '') +
          '. Display only: data, queries and links are not affected. Click to change, or pick Local time to go back.',
  );

  // whole hours, plus the half and quarter hours some places use
  const FIXED = [
    ...Array.from({ length: 27 }, (_, i) => (i - 12) * 3600),
    -9.5 * 3600,
    -3.5 * 3600,
    3.5 * 3600,
    4.5 * 3600,
    5.5 * 3600,
    5.75 * 3600,
    6.5 * 3600,
    8.75 * 3600,
    9.5 * 3600,
    10.5 * 3600,
    12.75 * 3600,
  ].sort((a, b) => a - b);

  async function pick() {
    const t = Date.now() / 1000;
    const offsetOf = (id: string) => fmtOffset(makeZone({ id }).offsetAt(t));
    const options = [
      { value: LOCAL, label: 'Local time (default)', detail: `${timeZone.browser} ${offsetOf(timeZone.browser)}` },
      { value: MACHINE, label: 'Machine time', detail: "each run on its own machine's clock" },
      { value: 'UTC', label: 'UTC' },
      ...allZones()
        .filter((z) => z !== 'UTC')
        .map((z) => ({ value: z, label: z.replaceAll('_', ' '), detail: offsetOf(z) })),
      ...FIXED.filter((s) => s !== 0).map((s) => ({
        value: offsetPref(s),
        label: fmtOffset(s),
        detail: 'fixed, no daylight saving',
      })),
    ];
    const res = await ask(
      'Time zone',
      [
        {
          label: 'Show times in',
          combo: options,
          value: '',
          preselect: timeZone.pref,
          placeholder: 'Type a city, zone or offset (UTC-03:00)',
          newLabel: 'Use',
          hint: 'Optional, and only changes how times are shown in this browser. Named zones follow daylight saving at each moment; fixed offsets never change.',
        },
      ],
      { confirm: 'Apply' },
    );
    if (!res) return;
    const value = res[0].trim() || timeZone.pref;
    const known = options.find((o) => o.value.toLowerCase() === value.toLowerCase() || o.label === value);
    const chosen = known?.value ?? value;
    const spec = parseZone(chosen);
    if (chosen !== LOCAL && chosen !== MACHINE && 'id' in spec && spec.id !== chosen) {
      await notice('Unknown time zone', `${chosen} is not a time zone this browser knows. Times are unchanged.`);
      return;
    }
    timeZone.set(chosen);
  }
</script>

<button class="btn zone" class:differs {title} aria-label="Time zone. {title}" onclick={pick}>
  {#if isLocal}
    <span class="place local">Local time</span>
  {:else if isMachine}
    <span class="place local">Machine time</span>
  {:else}
    <span class="mono short">{short}</span>
    {#if place && place !== short}<span class="place">{place}</span>{/if}
  {/if}
  {#if differs}<span class="dot" aria-hidden="true"></span>{/if}
</button>

<style>
  .zone {
    position: relative;
    height: 40px;
    border-radius: 12px;
    padding: 0 12px;
    gap: 6px;
    box-shadow: var(--lift);
    white-space: nowrap;
    font-size: 12px;
  }
  .short {
    color: var(--text);
  }
  .place {
    color: var(--muted);
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .dot {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
  }
  @media (max-width: 900px) {
    .place:not(.local) {
      display: none;
    }
  }
</style>
