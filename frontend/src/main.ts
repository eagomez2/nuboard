import { mount } from 'svelte';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import 'uplot/dist/uPlot.min.css';
import './app.css';
import App from './App.svelte';
import { NAME } from './lib/brand';

document.title = NAME;
mount(App, { target: document.getElementById('app')! });
