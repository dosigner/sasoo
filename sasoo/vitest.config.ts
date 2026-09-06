import { defaultExclude, defineConfig } from 'vitest/config';
import path from 'path';

// Pure-logic unit tests only. Frontend components and the Electron runtime
// are exercised through the app itself; anything tested here must stay free
// of DOM and Electron imports so a bare node environment suffices.
//
// DOM을 쓰는 테스트는 `*.dom.test.tsx`로 두고 여기서 제외한다. jsdom은
// frontend 워크스페이스에만 설치되어 있어서(pnpm이 의존성을 격리한다) 이
// 설정으로 실행하면 `Cannot find package 'jsdom'`으로 워커가 죽는다. 그 테스트는
// CI의 `pnpm --dir=frontend test` 단계가 jsdom과 함께 돌리므로 검증에서 빠지지 않는다.
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
    exclude: [...defaultExclude, '**/*.dom.test.{ts,tsx}'],
    environment: 'node',
  },
});
