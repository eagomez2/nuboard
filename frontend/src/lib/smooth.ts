/**
 * Debiased exponential moving average (as in TensorBoard / Adam's bias
 * correction): early points are not dragged toward zero. NaN/Inf inputs pass
 * through as NaN and do not disturb the running state.
 */
export function ema(values: ArrayLike<number>, weight: number): Float64Array {
  const out = new Float64Array(values.length);
  if (weight <= 0) {
    for (let i = 0; i < values.length; i++) out[i] = values[i];
    return out;
  }
  let last = 0;
  let n = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!Number.isFinite(v)) {
      out[i] = NaN;
      continue;
    }
    last = last * weight + (1 - weight) * v;
    n++;
    out[i] = last / (1 - Math.pow(weight, n));
  }
  return out;
}

/** Quantile of the finite values (linear interpolation); NaN if none. */
export function quantile(values: ArrayLike<number>[], q: number): number {
  const all: number[] = [];
  for (const arr of values) for (let i = 0; i < arr.length; i++) if (Number.isFinite(arr[i])) all.push(arr[i]);
  if (!all.length) return NaN;
  all.sort((a, b) => a - b);
  const pos = (all.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return all[lo] + (all[hi] - all[lo]) * (pos - lo);
}

/**
 * Outlier-robust y range: the 1st–99th percentile of the data, widened to the
 * full range when that adds little, with 6% padding. Spikes get clipped
 * instead of flattening the interesting part of the curve.
 */
export function robustRange(values: ArrayLike<number>[]): [number, number] | null {
  const lo = quantile(values, 0.01);
  const hi = quantile(values, 0.99);
  const min = quantile(values, 0);
  const max = quantile(values, 1);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  const span = hi - lo || Math.abs(hi) || 1;
  const a = min >= lo - span * 0.25 ? min : lo;
  const b = max <= hi + span * 0.25 ? max : hi;
  const pad = (b - a || span) * 0.06;
  return [a - pad, b + pad];
}
