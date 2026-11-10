# 최종 프런트엔드 빌드 진단

현재 checkout을 `/tmp/sasoo-final-build-check-y9kUpa/frontend`에 복사하고 별도 HOME과 외부 네트워크 차단을 사용했다. 기존 dist와 원본 설정을 수정하지 않았다. Node v26.13.0, pnpm 10.32.1, TypeScript 6.0.3이다.

- 현재 설정으로 `pnpm build`: 실패. `src/components/ReadingCodeBlock.dom.test.tsx:129`에서 `Promise.withResolvers`가 `PromiseConstructor`에 없다는 TS2550이 발생했다. `tsc -b` 단계에서 중단되어 Vite는 실행되지 않았다.
- 원인은 프로젝트 `tsconfig.json`의 `lib`가 ES2022인 반면 테스트가 ES2024의 `Promise.withResolvers`를 쓰는 것이다. 테스트 파일이 `include: ["src", ...]` 범위에 있어 제품 빌드의 타입 검사에 포함된다. 로컬 Node는 이 함수를 제공하지만 그 사실은 TypeScript의 lib 설정을 바꾸지 않는다.
- 격리 복사본의 `lib`만 ES2024로 변경하고 `target`은 ES2022로 유지해 `pnpm build`를 재실행했다. TypeScript와 Vite 빌드가 통과했으며 격리 `dist`에 결과가 생성됐다. 이 결과는 원본 설정 또는 실제 Electron 패키지의 통과를 뜻하지 않는다.
- ES2024 lib 변경은 전체 프로젝트에 그 API가 존재한다는 타입 가정을 추가하며 런타임에 polyfill을 설치하지 않는다. 대안으로 테스트의 해당 호출을 기존 Promise 생성자 패턴으로 변경할 수 있다. 어느 방법도 원본에는 적용하지 않았다.
- 공급사 요청과 실제 사용자 데이터 접근, Electron 실행, 패키징 및 릴리스는 수행하지 않았다. 이번에 실제로 검증한 것은 프런트엔드 빌드와 격리 설정 실험이다.
