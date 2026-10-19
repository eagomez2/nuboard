import { describe, expect, it } from 'vitest';
import { ansiToHtml, isTerminalText, stripAnsi } from '../src/lib/ansi';

const E = String.fromCharCode(27);

describe('ansi', () => {
  it('draws colors and styles as spans and escapes HTML', () => {
    const html = ansiToHtml(`${E}[92m${E}[1mok${E}[0m <b> ${E}[38;5;196mred${E}[0m ${E}[38;2;1;2;3mrgb${E}[39m`);
    expect(html).toContain('<span style="color:var(--ansi-10);font-weight:700">ok</span>');
    expect(html).toContain(' &lt;b&gt; ');
    expect(html).toContain('<span style="color:rgb(255,0,0)">red</span>');
    expect(html).toContain('<span style="color:rgb(1,2,3)">rgb</span>');
  });

  it('keeps the last redraw of a line, with the styles set before it', () => {
    const text = `${E}[32m 10%\r 50%\r100%${E}[0m\nnext`;
    expect(stripAnsi(text)).toBe('100%\nnext');
    expect(ansiToHtml(text)).toBe('<span style="color:var(--ansi-2)">100%</span>\nnext');
  });

  it('drops other escape codes and tells terminal text apart', () => {
    expect(stripAnsi(`${E}[2K${E}[1Ga${E}]0;title\x07b`)).toBe('ab');
    expect(isTerminalText('a\r\nb')).toBe(false);
    expect(isTerminalText('a\rb')).toBe(true);
    expect(isTerminalText(`${E}[0m`)).toBe(true);
  });
});
