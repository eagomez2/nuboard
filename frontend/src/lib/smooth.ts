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
  return quantileOfSorted(finiteSorted(values), q);
}

/** The finite values of every array, in one sorted typed array (numeric sort, no boxing). */
function finiteSorted(values: ArrayLike<number>[]): Float64Array {
  let n = 0;
  for (const arr of values) n += arr.length;
  const all = new Float64Array(n);
  let k = 0;
  for (const arr of values)
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      if (Number.isFinite(v)) all[k++] = v;
    }
  return all.subarray(0, k).sort();
}

/** Quantile of already sorted values (linear interpolation); NaN if empty. */
function quantileOfSorted(sorted: Float64Array, q: number): number {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/**
 * Outlier-robust y range: the 1st–99th percentile of the data, widened to the
 * full range when that adds little, with 6% padding. Spikes get clipped
 * instead of flattening the interesting part of the curve.
 */
export function robustRange(values: ArrayLike<number>[]): [number, number] | null {
  // one sort serves all four quantiles (this runs on every zoom and redraw of a chart)
  const sorted = finiteSorted(values);
  const lo = quantileOfSorted(sorted, 0.01);
  const hi = quantileOfSorted(sorted, 0.99);
  const min = quantileOfSorted(sorted, 0);
  const max = quantileOfSorted(sorted, 1);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  const span = hi - lo || Math.abs(hi) || 1;
  const a = min >= lo - span * 0.25 ? min : lo;
  const b = max <= hi + span * 0.25 ? max : hi;
  const pad = (b - a || span) * 0.06;
  return [a - pad, b + pad];
}
