# 승인된 A, B, C 삭제 검증

## 범위

사용자가 A, B, C 전체를 승인했다. `odl_parser.py:_resolve_pdf_engine`, `settings.py:_set_setting`, `frontend/src/lib/api.ts:getMermaid`만 제품 코드에서 삭제했다. `api/test_settings.py`의 이전 함수 patch 여섯 곳을 실제 `_set_settings`로 바꾸고, `requestEfficiency.test.js`의 wrapper mock 세 참조를 제거했다. HTTP Mermaid GET과 repair POST, legacy 표시 분기, manifest 원형과 테스트는 유지했다.

기존 수정이 있던 파일을 포함해 변경 직전 원본과 SHA-256, 이 작업만 되돌리는 역방향 patch와 변경 후 해시를 `docs/validation/assets/refactor-approved-20261109-i9rLjD/`에 별도로 보존했다. 역방향 patch를 적용할 때는 이후 수정분과 충돌하는지 먼저 확인한다. 별도 실행 중인 다른 변경사항을 덮어쓰지 않는다.

## 동작 고정 및 집중 검사

- `services/test_engine_resolution_refactor.py`: 텍스트 엔진에서 명시 override가 환경변수보다 우선하는지 검사했다. 기존 StageEngineResolutionTests와 합쳐 삭제 전 6 passed. 삭제 후 parser, Java runtime, 사용량 테스트 포함 63 passed.
- `api/test_settings_storage_guard_refactor.py`: credential 암호화 오류의 503, `_set_settings` 비호출, 합성 in-memory SQLite의 기존 값과 timestamp 보존, 쓰기 SQL 부재를 검증한다. 관련 설정 및 DB 효율성 테스트 34 passed, 8 subtests passed.
- `src/hooks/useAnalysis.noGeneration.dom.test.tsx`: API 모듈을 mock하지 않고 React hook과 실제 API client가 호출하는 fetch를 가로챈다. 빈 시각화와 HTTP 실패에서 저장된 summary가 읽히고 Mermaid 생성 GET 및 분석 시작 POST가 없음을 각각 검사한다. 삭제 전 2 passed. 삭제 후 기존 hook 테스트와 함께 22 passed. 실제 네트워크는 호출하지 않는다.

## 마지막 수정 기준 회귀

소스, 필요한 fixture와 Java runtime 및 프런트엔드 node_modules를 `/tmp/sasoo-refactor-approved-gYDuQZ`에 복사했다. 기존 가상환경 Python 3.14로 테스트했고, 별도 HOME과 앱 데이터 경로, 공급사 키를 제외한 환경, macOS sandbox 외부 네트워크 차단을 사용했다. 빌드는 격리 복사본에서 실행하여 기존 dist를 덮어쓰지 않았다.

- backend `pytest services api models tools/test_luna_compare.py -q`: 1,280 passed, 7 skipped, 236 subtests passed, 경고 44개.
- backend `py_compile main.py`: 통과, pycache는 격리 경로.
- frontend `pnpm test`: 46개 파일, 379 passed.
- frontend `pnpm lint`: 통과.
- frontend `pnpm tsc --noEmit` 및 `pnpm build`: 실패. `src/components/ReadingCodeBlock.dom.test.tsx:129`의 `Promise.withResolvers`가 현재 ES2022 lib에 없다. 이 오류는 세 함수 삭제 이전 격리 기준선에서도 발생했고 본 승인 범위 밖이어서 수정하지 않았다. 빌드는 TypeScript 단계에서 중단됐다.

## 한계

Electron 및 실제 사용자 데이터는 실행하거나 열지 않았다. UI 호출 경로에서 참조되지 않는 wrapper를 삭제했지만 외부 클라이언트나 개인 Python/TypeScript 스크립트의 직접 import 호환은 증명하지 못했다. 테스트와 모의 fetch 통과는 실제 Electron 동작 전수 확인을 뜻하지 않는다. 공급사 호출, 기존 자료 재생성, 릴리스, 커밋 및 푸시는 하지 않았다. 전체 리팩토링 계획의 다른 구조 분리와 프런트엔드 빌드 오류는 남아 있다.
