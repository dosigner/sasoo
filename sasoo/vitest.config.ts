import { defineConfig } from 'vitest/config';
import path from 'path';

// Pure-logic unit tests only. Frontend components and the Electron runtime
// are exercised through the app itself; anything tested here must stay free
// of DOM and Electron imports so a bare node environment suffices.
export default defineConfig({
  resolve: {
    // frontend/vite.config.ts의 '@' 별칭과 동일하게 맞춘다 — frontend/src 아래
    // 소스가 '@/...'로 서로를 import하므로, 이 별칭이 없으면 그런 파일을
    // 거치는 테스트가 모듈 해석 단계에서 바로 실패한다.
    alias: {
      '@': path.resolve(__dirname, './frontend/src'),
    },
  },
  test: {
    include: ['frontend/src/**/*.test.{ts,tsx}', 'electron/**/*.test.ts'],
    environment: 'node',
  },
});
