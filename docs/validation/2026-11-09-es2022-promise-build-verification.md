# ES2022 Promise 테스트 수정과 빌드 검증

`ReadingCodeBlock.dom.test.tsx`의 `Promise.withResolvers`를 기존 `Promise<void>` 생성자와 resolve 함수로 바꿨다. 클립보드 쓰기가 보류 중일 때 컴포넌트를 제거하고 그 후 Promise를 완료하는 기존 테스트 순서와 타이머 검증은 유지했다. TypeScript `target`과 `lib`는 ES2022 그대로다.

수정된 전체 프런트엔드 소스와 node_modules를 `/tmp/sasoo-promise-build-hqGN5U/frontend`에 별도로 복사해 기존 dist를 보존하고 외부 네트워크 차단 및 별도 HOME에서 검사했다.

- `pnpm exec vitest run src/components/ReadingCodeBlock.dom.test.tsx`: 9 passed.
- `pnpm test`: 46 files, 379 passed.
- `pnpm tsc --noEmit`: passed.
- `pnpm lint`: passed.
- `pnpm build`: passed. `tsc -b`와 Vite production build 완료, 격리 복사본에 dist 생성.

이번 변경은 테스트 전용이다. Electron 실행, 앱 패키징, 백엔드 회귀는 이번 수정 후 실행하지 않았다. 유료 호출과 실제 사용자 데이터 접근은 하지 않았다.
