/**
 * Entry of `audio.html`, the waveform player frame. wavesurfer.js and its
 * plugins are bundled (the viewer works offline) and exposed the way the
 * player script expects them, as `window.WaveSurfer.{Regions,Hover,Minimap}`.
 */
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import WaveSurfer from 'wavesurfer.js';
import Hover from 'wavesurfer.js/dist/plugins/hover.esm.js';
import Minimap from 'wavesurfer.js/dist/plugins/minimap.esm.js';
import Regions from 'wavesurfer.js/dist/plugins/regions.esm.js';
import './player.css';

Object.assign(window, { WaveSurfer: Object.assign(WaveSurfer, { Regions, Hover, Minimap }) });
// @ts-expect-error plain script, no types
import('./player.js');
