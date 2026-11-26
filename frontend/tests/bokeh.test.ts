import { describe, expect, it } from 'vitest';
import { bokehScripts } from '../src/lib/bokeh';

/** A fetch stand-in that serves the given BokehJS files and 404s the rest. */
function cdn(files: Record<string, string>): typeof fetch {
  return (async (url: string) => {
    const name = String(url).split('/').pop()!;
    return name in files ? new Response(files[name]) : new Response('', { status: 404 });
  }) as typeof fetch;
}

describe('bokehScripts', () => {
  it('inlines the core, widgets and tables files of the figure version', async () => {
    const get = cdn({
      'bokeh-3.10.2.min.js': 'core',
      'bokeh-widgets-3.10.2.min.js': 'widgets',
      'bokeh-tables-3.10.2.min.js': 'tables',
    });
    expect(await bokehScripts('3.10.2', get)).toEqual(['core', 'widgets', 'tables']);
  });

  it('keeps the core when an extra file is missing', async () => {
    const get = cdn({ 'bokeh-3.1.0.min.js': 'core', 'bokeh-tables-3.1.0.min.js': 'tables' });
    expect(await bokehScripts('3.1.0', get)).toEqual(['core', 'tables']);
  });

  it('gives up without the core file or a network', async () => {
    expect(await bokehScripts('3.10.2', cdn({ 'bokeh-widgets-3.10.2.min.js': 'w' }))).toBeNull();
    const offline = (async () => {
      throw new TypeError('offline');
    }) as typeof fetch;
    expect(await bokehScripts('3.10.2', offline)).toBeNull();
  });
});
