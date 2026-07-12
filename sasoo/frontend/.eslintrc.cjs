/* eslint-env node */
// ESLint baseline for the Vite + React + TS frontend.
// Toolchain: eslint v8 + @typescript-eslint v7 + react-hooks + react-refresh
// (legacy .eslintrc format, matched to the `eslint . --ext ts,tsx` lint script).
//
// Philosophy: start from the recommended presets and keep them as errors, then
// make the smallest set of targeted adjustments needed to go green on the
// existing codebase without rewriting it. Each adjustment below is documented
// with its rationale.
module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  // Only src is linted; keep build output, deps, node-side scripts and config
  // files out of scope.
  ignorePatterns: [
    'dist',
    'node_modules',
    'scripts',
    '*.config.js',
    '*.config.ts',
    '*.config.d.ts',
    'vite-env.d.ts',
    '.eslintrc.cjs',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint', 'react-refresh'],
  rules: {
    // Respect the existing `_`-prefix convention for intentionally unused
    // bindings (e.g. `{ node: _node, ... }`, `variant: _variant`). This aligns
    // the rule with how the code is already written rather than relaxing it.
    '@typescript-eslint/no-unused-vars': [
      'error',
      {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        ignoreRestSiblings: true,
      },
    ],
    // Allow intentional infinite loops such as the `while (true)` stream reader
    // in lib/api.ts; still flags constant conditions in if/ternary/etc.
    'no-constant-condition': ['error', { checkLoops: false }],
    // Advisory-only rule. Enforcing it as a hard error would require changing
    // effect dependency arrays across existing hooks, which can alter runtime
    // behavior. rules-of-hooks (the correctness rule) stays on as an error.
    'react-hooks/exhaustive-deps': 'off',
    // Vite fast-refresh DX hint only (no correctness impact). The codebase
    // co-locates helpers/constants with components in several files; enforcing
    // this as an error would require restructuring those modules. Left off so
    // the baseline stays green without that churn.
    'react-refresh/only-export-components': 'off',
  },
  overrides: [
    {
      // PdfViewer wraps pdfjs-dist, whose runtime objects are weakly typed;
      // the `any` usages here are interop with that library. no-explicit-any
      // remains an error everywhere else in the codebase.
      files: ['src/components/PdfViewer.tsx'],
      rules: {
        '@typescript-eslint/no-explicit-any': 'off',
      },
    },
  ],
};
