import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs.recommended,
  { languageOptions: { globals: { ...globals.browser } } },
  {
    files: ['**/*.svelte', '**/*.svelte.ts'],
    languageOptions: { parserOptions: { parser: ts.parser } },
  },
  {
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'svelte/no-at-html-tags': 'off',
      'svelte/prefer-svelte-reactivity': 'off',
    },
  },
  {
    // Wall-clock times are written only by lib/format.ts through lib/tz.ts, in the
    // zone picked in the header, so every view shows the same time.
    files: ['src/**/*.{ts,js,svelte}'],
    ignores: ['src/lib/tz.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'CallExpression[callee.property.name=/^toLocale(Date|Time)String$/]',
          message: 'Format times with fmtDate/fmtDateTime/fmtClock from lib/format.ts, so they follow the chosen zone.',
        },
        {
          selector:
            "CallExpression[callee.property.name='toLocaleString'][callee.object.type='NewExpression'][callee.object.callee.name='Date']",
          message: 'Format times with fmtDate/fmtDateTime/fmtClock from lib/format.ts, so they follow the chosen zone.',
        },
        {
          selector:
            'CallExpression[callee.property.name=/^get(FullYear|Month|Date|Day|Hours|Minutes|Seconds|TimezoneOffset)$/]',
          message: "Read wall-clock fields through the zone kit (lib/tz.ts), not the browser's zone.",
        },
        {
          selector: "MemberExpression[object.name='Intl'][property.name='DateTimeFormat']",
          message: 'Format times with lib/format.ts so they follow the chosen zone.',
        },
      ],
    },
  },
  { ignores: ['node_modules', 'dist', '../src'] },
);
