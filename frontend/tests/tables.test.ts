import { describe, expect, it } from 'vitest';
import { tableCsv } from '../src/lib/tables';

describe('tableCsv', () => {
  it('writes a header and one line per row, quoting where needed', () => {
    const csv = tableCsv({
      id: 'name',
      columns: [
        { name: 'name', type: 'text' },
        { name: 'acc', type: 'number' },
        { name: 'ok', type: 'bool' },
        { name: 'clip', type: 'audio' },
      ],
      rows: [
        ['a, "b"', 0.5, true, { $cell: 'cells/0.wav' }],
        ['line\nbreak', null, false, null],
      ],
    });
    expect(csv).toBe('name,acc,ok,clip\r\n"a, ""b""",0.5,true,cells/0.wav\r\n"line\nbreak",,false,\r\n');
  });
});
