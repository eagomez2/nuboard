// Pins that are patterns, such as `checkpoints/*/best_*.pth`.
import type { RunFile } from './api';

export const isPattern = (pin: string) => /[*?]/.test(pin);

/** A pattern as a regular expression over a whole path: `*` within a folder, `**` across folders, `?` one character. */
export function patternRegex(pin: string): RegExp {
  let re = '';
  for (let i = 0; i < pin.length; i++) {
    const c = pin[i];
    if (c === '*' && pin[i + 1] === '*' && pin[i + 2] === '/') {
      re += '(?:.*/)?'; // `**/`: any folders, or none
      i += 2;
    } else if (c === '*' && pin[i + 1] === '*') {
      re += '.*';
      i++;
    } else if (c === '*') re += '[^/]*';
    else if (c === '?') re += '[^/]';
    else re += c.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${re}$`, 'i');
}

/** The files of one run a pin names, newest first. */
export function pinMatches(pin: string, files: RunFile[]): RunFile[] {
  if (!isPattern(pin)) return files.filter((f) => f.path === pin);
  const re = patternRegex(pin);
  return files.filter((f) => re.test(f.path)).sort((a, b) => b.mtime - a.mtime);
}
