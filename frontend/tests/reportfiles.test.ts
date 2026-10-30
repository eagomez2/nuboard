import { describe, expect, it } from 'vitest';
import type { RunBrief, RunsResponse } from '../src/lib/api';
import { audioMarkdown, isAudio, isAudioPath, noMediaIn } from '../src/lib/reportfiles';

const run = (project: string, media_count?: number) => ({ project, media_count }) as unknown as RunBrief;
const list = (runs: RunBrief[], total = runs.length) => ({ runs, total }) as unknown as RunsResponse;

describe('noMediaIn', () => {
  it('is true only when every run of the project counted no media', () => {
    expect(noMediaIn(list([run('a', 0), run('a', 0), run('b', 3)]), 'a')).toBe(true);
    expect(noMediaIn(list([run('a', 0), run('a', 2)]), 'a')).toBe(false);
    expect(noMediaIn(list([run('b', 3)]), 'a')).toBe(true); // no runs at all: nothing to add
  });
  it('keeps the item on when it cannot be sure', () => {
    expect(noMediaIn(null, 'a')).toBe(false); // runs not loaded yet
    expect(noMediaIn(list([run('a', 0)], 5), 'a')).toBe(false); // a query hides some runs
    expect(noMediaIn(list([run('a', 0), run('a')]), 'a')).toBe(false); // an older catalog
  });
});

describe('audio uploads', () => {
  it('recognizes audio by type or extension', () => {
    expect(isAudio({ name: 'take.FLAC', type: '' })).toBe(true);
    expect(isAudio({ name: 'x.bin', type: 'audio/mpeg' })).toBe(true);
    expect(isAudio({ name: 'clip.webm', type: 'video/webm' })).toBe(true);
    expect(isAudio({ name: 'notes.txt', type: 'text/plain' })).toBe(false);
    expect(isAudioPath('files/0123456789abcdef.wav')).toBe(true);
    expect(isAudioPath('files/sub/x.wav')).toBe(false);
  });
  it('writes a link with the caption as its text', () => {
    expect(audioMarkdown('files/ab.wav', 'A [take]\none')).toBe('[A  take  one](files/ab.wav)');
    expect(audioMarkdown('files/ab.wav', '  ')).toBe('[Audio](files/ab.wav)');
  });
});
