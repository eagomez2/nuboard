# Known limitations

What NuBoard does not do yet, or does with a trade-off.

- Charts plot rank 0 only, as TensorBoard does; other ranks are read from
  Python, and timers of every rank are compared in the **Timing** tab.
- Bokeh figures need `cdn.bokeh.org` when viewed; Plotly and Vega-Lite work
  offline.
- Smoothing is applied to the downsampled series the server sends (about
  one to two points per pixel), not to every raw point.
- The run list sends the whole filtered list to the browser; at tens of
  thousands of runs this should become paged.
- Runs on Windows are covered by design (no colons, atomic replace with
  retries, case-collision check) but were only tested on Linux so far.
- Edits of a run's stars, tags, notes and properties are safe within one
  viewer, and stale edits of notes and properties are caught, but two viewers
  (or a viewer and `Run.set_field`) saving the same run within the same few
  milliseconds can still lose one edit, and a sync tool restoring an older
  `annotations.json` wins. See
  [Editing from several places](../guide/viewer.md#editing-from-several-places).
