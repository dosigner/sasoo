import { defineConfig } from 'vitest/config';

// Pure-logic unit tests only. Frontend components and the Electron runtime
// are exercised through the app itself; anything tested here must stay free
// of DOM and Electron imports so a bare node environment suffices.
export default defineConfig({
  test: {
    include: ['frontend/src/**/*.test.{ts,tsx}', 'electron/**/*.test.ts'],
    environment: 'node',
  },
});
