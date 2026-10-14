import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { NAME } from './src/lib/brand';

// The build lands inside the Python package so the wheel ships it.
export default defineConfig({
  plugins: [tailwindcss(), svelte(), { name: 'brand', transformIndexHtml: (html) => html.replaceAll('%NAME%', NAME) }],
  base: './',
  build: {
    outDir: '../src/nuboard/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 5000, // Plotly is one big lazy chunk, loaded only for Plotly figures
    rollupOptions: { input: { main: 'index.html', figure: 'figure.html', audio: 'audio.html' } },
  },
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:6070', changeOrigin: false } },
  },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
});
