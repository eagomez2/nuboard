/**
 * BokehJS must match the version that wrote the figure; it is fetched once, when exporting.
 * The core file is required; the widgets and tables files are added when the CDN has them,
 * as in the viewer, so figures with widgets or data tables render in the export too.
 */
export async function bokehScripts(version: string, get: typeof fetch = fetch): Promise<string[] | null> {
  const base = 'https://cdn.bokeh.org/bokeh/release';
  const text = async (file: string): Promise<string | null> => {
    try {
      const res = await get(`${base}/${file}-${version}.min.js`);
      return res.ok ? await res.text() : null;
    } catch {
      return null;
    }
  };
  const [core, ...extras] = await Promise.all(['bokeh', 'bokeh-widgets', 'bokeh-tables'].map(text));
  if (core === null) return null;
  return [core, ...extras.filter((s): s is string => s !== null)];
}
