# Sasoo 코드 조사와 안전한 리팩토링 실행 계획

**목표:** 현재 제품 계약과 사용자 데이터, 미완료 작업을 보존하면서 좁은 후보별 정리와 책임 분리를 검증한다.

**구조:** 진입점과 실제 호출을 기준으로 정적 조사하고, 삭제는 아래 대상별 승인 뒤 각각 처리한다. 실행 이력과 비용 원장 설계는 별개로 유지한다.

**기술:** FastAPI, SQLite, pytest, Electron, React, TypeScript, Vitest.

**기준 문서:** `2026-11-09-sasoo-refactor-unused-code-inventory.md`, `2026-11-09-execution-provenance-verification-cost.md`, `docs/validation/2026-11-09-provenance-cost-partial-investigation.md`, `docs/validation/2026-11-09-manifest-store-partial-implementation.md`.

## 범위와 제한

- 데이터, 과거 증거, 캐시, 빌드와 미커밋 작업을 보존한다. 삭제, 대체, 공급사 호출, 재발행, 릴리스, 커밋은 별도 승인 없이는 하지 않는다.
- 외부 소비자, 로컬 개인 스크립트, 반사 호출, 완전한 과거 버전 호환과 전체 의존성의 필요성은 확인하지 못했다. 정적 참조 부재는 미사용 증명이 아니다.
- 파이썬 소스 157개를 AST로 읽어 후보의 직접 호출을 찾고, 저장소의 텍스트 참조를 검색했다. 문자열 조립, 별칭, 바이너리, 외부 사용은 이 방식으로 증명할 수 없다. 모든 함수의 도달 가능성을 증명한 전체 감사가 아니다.
- graphify의 `graph.json`은 2026-09-25 생성, 보고서는 같은 날 생성됐다. 질의는 경계 탐색에만 사용했으며 현재 삭제 근거로 사용하지 않았다.
- 현재 추적 파일 50개에 기존 수정이 있다. `analysis_execution.py`, `analysis_routes.py`, `evidence_verifier.py`, `AnalysisPanel.tsx`, `useAnalysis.ts`, `api.ts`에도 기존 수정이 있다. 독립 미추적 manifest 원형과 테스트를 보존한다.

## 진입점과 경계

- FastAPI `backend/main.py`: lifespan에서 bootstrap과 supervisor reconciler 시작, 종료 시 정지와 DB 닫기. CORS와 HTTP middleware, papers/analysis/settings/agents router를 등록한다. 분석 시작은 `api/analysis_routes.py:run_analysis`에서 subprocess supervisor 또는 FastAPI background task로 갈라지고 worker는 `services/analysis_worker.py`에서 `run_full_analysis`를 호출한다. 재개와 중복 실행에 영향을 주므로 단순 파일 이동도 소유권과 취소 회귀가 필요하다.
- `frontend/index.html` → `src/main.tsx` → `App.tsx`의 lazy page → `Workbench.tsx`의 lazy `PdfViewer`, `AnalysisPanel`, `ChatPanel`; `useAnalysis`는 상태와 결과를 polling한다. `FigureGallery.tsx`는 페이지가 아닌 컴포넌트이며 이미지 선택, 포커스와 스크롤, 설명 상태를 가진다.
- Electron `main.ts`는 preload와 IPC 수신기를 등록하고 `preload.ts`는 문자열 채널로 renderer에 API를 노출한다. `backend-process-launcher.ts`는 개발 Python 또는 패키징된 backend를 실행하고 `updater.ts`는 별도 IPC를 제공한다. 문자열 채널과 종료 흐름을 보존한다.
- `sasoo/package.json`, `scripts/build-backend.js`, `backend/sasoo-backend.spec`, `.github/workflows/build-check.yml`과 `release.yml`이 빌드와 패키징 경계다. 마이그레이션, 독립 스크립트, fixture, lockfile과 의존성은 import 부재로 삭제하지 않는다. `services/conftest.py`는 pytest 자동 발견 대상이다. CI와 모든 독립 스크립트의 실행을 검증한 것은 아니다.
- 실제 파서 경로는 `document_context`의 `ensure_text_artifacts`, API와 artifact refresh의 async wrapper 및 `ensure_visual_artifacts`다. `analysis_completion.py`는 stage schema를 `getattr`로 동적 참조하고, quality 비교 도구는 실행 모듈 함수들을 동적으로 patch한다.

## 대상별 판정

표의 코드 경로는 `sasoo/` 기준이다. 복원은 변경 전 해당 조각을 별도 패치로 보존한 뒤 같은 위치에 수동 적용한다. 사용자의 기존 diff를 포함하는 파일에 `git restore`나 전체 파일 교체는 하지 않는다. 모든 삭제는 별도 승인 후다.

| 대상과 정확한 범위 | 역할, 확인된 참조와 미확인 사항 | 분류, 예상 영향, 대체 검증 및 복원 |
| --- | --- | --- |
| `backend/services/odl_parser.py:_resolve_pdf_engine` 함수 전체, 873행 부근 | `_resolve_stage_engine('text', engine)` 호환 별칭. 157개 Python AST 직접 호출과 저장소 검색에 호출 없음. 외부 Python 스크립트, 동적 이름 호출 미확인. | **삭제 제안 A.** 외부 import가 깨질 수 있다. 삭제 전 override, 환경값, 기본값을 `_resolve_stage_engine` 중심으로 고정하고 parser 집중 회귀. 이 함수만 제거, 모듈과 다른 함수 보존. 별도 패치로 함수 복원. |
| `backend/api/settings.py:_set_setting` 함수 전체, 213행 부근 및 `api/test_settings.py`에서 이 이름을 patch하는 항목만 | 제품 저장은 `_set_settings` 413행. 기존 테스트 여러 곳의 구식 patch가 삭제 시 실패하며 읽기 테스트의 비호출 주장은 실제 배치 저장 호출을 막지 못한다. 외부 import 미확인. | **삭제 제안 B.** 기존 `test_update_settings_reports_credential_store_unavailable_without_writing_key`는 실제 배치 함수 비호출을 검사한다. 새 합성 SQLite 테스트는 혼합 변경의 행과 timestamp 불변, 쓰기 SQL 부재도 검사한다. 삭제 전 구식 patch를 `_set_settings`에 대한 의도별 주장 또는 적절한 DB 검증으로 바꾸고 테스트를 단순 삭제하지 않는다. 함수와 각 수정된 테스트 조각을 패치로 복원. |
| `frontend/src/lib/api.ts:getMermaid` export 함수 전체, 802행 부근 및 `requestEfficiency.test.js`의 해당 mock 참조 | 제품 hook에서 호출 검색 결과 없음. 테스트는 빈 결과와 조회 오류에서 호출 0회 확인한다. 외부 renderer import 미확인. 서버 `GET /analysis/{paper_id}/mermaid`는 모델 호출과 비용 기록을 하는 별개의 공개 API다. | **삭제 제안 C, 조건부.** wrapper 삭제 시 테스트 mock이 사라져 기존 검증이 무의미해질 수 있다. 먼저 API 모듈 mock이 아닌 실제 fetch 경계에서 빈 결과/실패 양쪽의 생성 GET 0회와 run POST 0회를 검증한다. 공개 HTTP GET과 repair 경로, Mermaid 타입과 renderer는 보존. wrapper 및 테스트 조각만 패치로 복원. |
| `backend/services/odl_parser.py:paper_artifacts_are_current` | 제품 직접 호출은 찾지 못했으며 `test_odl_parser.py` 네 호출이 텍스트와 시각물의 두 상태 및 누락을 검사한다. 외부 함수 호출 미확인. | **추가 조사.** 두 단계 개별 체크 테스트로 보호할 제품 계약을 먼저 대조하고 외부 사용을 조사한다. 현재 삭제 범위 없음. 분리 시 원 함수와 테스트를 패치로 복원. |
| `backend/services/odl_parser.py:ensure_parsed_artifacts` | text와 visual을 순서대로 준비하는 호환 wrapper. `test_odl_parser.py:609`가 `force=True`로 사용한다. 외부 호출 미확인. | **유지.** 테스트가 force, 파일과 manifest를 보호하므로 독립 단계와 사용자 호출 호환 증명 전 제거하지 않는다. 변경한다면 합성 PDF, 파일/hash/manifest, 오류, force 순서를 고정한 뒤 별도 승인. |
| `backend/services/evidence_verifier.py:build_pdf_index` | 테스트에서 합성 PDF를 열고 `_index_from_doc`을 호출한다. 실제 검증의 문서 열기 경로와 테스트 helper의 의미를 추가 비교해야 한다. 외부 import 미확인. | **추가 조사.** 테스트는 실제 PDF 색인과 인용 판정을 보호한다. 삭제 전 실제 공개 검증 경로로 등가 테스트를 옮기고 좌표, 페이지, 부분 인용과 오류를 비교한다. 현재 삭제 범위 없음. |
| `frontend/src/hooks/useAnalysis.ts:mermaid: null`, `Workbench`, `AnalysisPanel`, `SynthesisView`, `VisualizationGallery:legacyMermaid` | 현재 hook은 null을 전달하고 gallery는 prop을 받아 레거시 분기를 표시한다. 독립 컴포넌트 호출과 과거 데이터, 외부 소비자는 완전 확인하지 못했다. | **추가 조사.** null 도달과 저장된 legacy fixture 및 직접 컴포넌트 사용을 DOM/Electron에서 확인한다. 데이터 호환과 생성 요청 금지를 고정하기 전 삭제하지 않는다. |
| `backend/services/analysis_manifest_store.py`와 `test_analysis_manifest_store.py` 전체 | 미추적, 테스트만 참조하는 독립 트랜잭션 원형. 제품 연결, migration, worker fence, 이미지 및 원장 구현이 아니다. | **유지.** 미완료 작업이며 실행 이력 설계의 별도 결정 전 삭제나 변경 금지. |
| Mermaid HTTP GET과 repair POST, 마이그레이션, scripts, fixture, lockfile, 데이터, 과거 evidence | 서버 라우트와 독립 실행 및 기존 사용자/외부 소비 가능성 존재. | **유지.** wrapper나 제품 import 부재는 삭제 근거가 아니다. |

## 독립 구조 작업 계획

아래 작업은 구조 제안이며 파일의 물리적 크기가 아닌 책임과 호출을 기준으로 한다. 각 작업 전 현재 diff와 hash를 새 기록에 보존하고, 미완료 실행 이력 설계와 충돌하면 중지한다. 외부 경로, 응답, DB, 프롬프트, 모델/effort, 입력 순서, 병렬, 취소 및 캐시 계약을 바꾸지 않는다. 재배치에 수반되는 기존 코드 삭제도 정확한 범위에 대한 별도 승인을 받는다.

1. **시각화 계획 순수 로직:** `services/analysis_execution.py`의 `_viz_plan_shape_error`, `_normalize_viz_plan`, `_gate_viz_items`와 관련 helpers를 후보로 한다. 호출자인 `_plan_visualizations`, 테스트의 기존 patch와 `analysis_routes.py` import, `analysis_completion.py` 동적 schema 조회를 먼저 목록화한다. 기존 입력/출력 스냅샷에 레거시 illustrations 부재, 잘못된 점수, 경계값, 순서와 오류를 추가한다. 순수 함수만 새 모듈로 옮기되 기존 import 호환을 유지하는 방안을 우선 검토한다. 집중 `test_analysis_routes.py`와 관련 viz 테스트, 이후 전체 회귀. manifest/비용 쓰기 경계에 접근하지 않는다. 의미나 결과가 달라지면 중지.
2. **분석 router 경계:** `analysis_routes.py`의 분석 상태, visualization, report, streaming chat 각각의 route method/path, response model, 예외, 응답 순서를 수집한다. FastAPI TestClient/ASGI synthetic DB에서 OpenAPI와 status/body/stream 취소 및 no-provider 계약을 먼저 고정한다. 책임별 `APIRouter` 분리는 기존 등록 순서와 테스트 patch 위치까지 보존 가능할 때 한 그룹씩 제안한다. 결과 저장과 standalone spend는 manifest/ledger 설계와 먼저 정합을 확인한다. 라우트 중복 또는 응답 변경 시 중지.
3. **PDF 엔진 선택:** `odl_parser.py`의 `_resolve_stage_engine`과 `_normalize_engine`의 순수 선택을 후보로 한다. `document_context`, `artifact_status`, async refresh, Java/Gemini 대체 경로 및 환경 override, 캐시 manifest와 결과 파일의 hash를 합성 PDF로 고정한다. 엔진 선정 로직만 별도 모듈로 추출하며 디스패치, 캐시, 파일 쓰기 순서를 유지한다. `test_odl_parser.py`, `test_odl_java_runtime.py`, `test_visual_parse_usage.py` 후 전체 회귀. 저장 또는 생성 요청 차이가 있으면 중지.
4. **AnalysisPanel 표시 계산:** `AnalysisPanel.tsx`의 실제 props, 섹션 선택과 읽기 상태를 `Workbench.tsx` 및 기존 `AnalysisPanel.reading.dom.test.tsx` 기준으로 매핑한다. 순수 표시 계산을 식별한 후 기존 입력/출력과 legacy/malformed 데이터를 고정하고 한 계산만 추출한다. DOM 키보드, 선택, 링크, 스크롤, 상태 및 요청 수를 보존한다. DOM 검사 후 격리 Electron 1024/1440 검사를 필수로 한다. 접근성 또는 표시 상태가 달라지면 중지.
5. **API 타입 경계:** `frontend/src/lib/api.ts`에서 타입 선언을 소비자별로 조사한 후 타입만 작은 모듈로 옮기고 기존 export를 재수출한다. URL, fetch, 인증, 오류, 중복 요청을 건드리지 않는다. `pnpm tsc --noEmit`, API와 hook 테스트, 전체 회귀. 기존 빌드 오류를 먼저 별도로 원인 분류한다. 공개 import가 달라지면 중지.
6. **Workbench/PdfViewer/FigureGallery:** props와 상태 소유권, PDF 선택/페이지 이동, focus trap, 스크롤, 이미지 설명 취소를 기록하고 synthetic fixture로 상호작용을 고정한다. 공유 순수 계산 또는 명확한 한 상태 경계만 개별 추출하며, 유료 설명 호출은 mock한다. 해당 DOM 회귀와 네트워크 차단 Electron 검사, 화면/API 값 대조가 준비되지 않으면 구현하지 않는다.

각 작업은 고정 테스트 → 집중 검사 → 한 책임 변경 → 집중 검사 → 마지막 수정 기준 전체 회귀 순서로 진행한다. 테스트가 실패하면 원인을 기록하고 다른 후보를 섞지 않는다. 필요 시 해당 조각만 수동 복원한다.

## 삭제 승인과 진행 순서

- A, B, C는 각각 독립 승인이다. 각 후보의 사전 테스트를 작성하고 통과한 뒤에만 지정된 함수와 명시된 테스트 참조를 제거한다. 어떤 후보든 외부 사용이나 동적 호출이 발견되면 해당 후보를 중지한다.
- 선택하지 않은 후보, HTTP API, 기존 파일과 미완료 manifest는 유지한다. 승인이 없는 현재 단계에서는 제품 코드 삭제와 구조 이동을 수행하지 않는다.
- 구조 변경마다 범위와 복원 patch를 사전에 별도 제시한다. 기존 diff나 빌드 산출물을 교체하지 않는다.

## 현재 단계 검증과 잔여 위험

- 새 `backend/api/test_settings_storage_guard_refactor.py`: in-memory SQLite에서 credential 실패 503, 실제 `_set_settings` 비호출, 혼합 설정의 기존 행 및 timestamp 불변, 쓰기 SQL 0건을 검증한다. 기존 설정 테스트 포함 28 passed, 2 subtests passed.
- 코드 및 의존성 격리 복사본 `/tmp/sasoo-refactor-review-QSxjbv`에서 외부 네트워크 차단을 적용했다. 직접 소켓 연결이 `PermissionError`로 차단됨을 확인했다. 공급사 키는 테스트 환경에 넘기지 않았다.
- 프런트엔드 테스트 45개 파일, 377 passed. lint 통과. 타입 검사와 빌드는 `ReadingCodeBlock.dom.test.tsx:129`의 `Promise.withResolvers`가 현재 tsconfig의 ES2022 lib에 없어서 실패했다. 제품 변경 전에 원인과 해결 범위를 별도 조사한다.
- 백엔드 전체 회귀는 격리 fixture 누락으로 첫 수집에 실패했다. 두 번째 실행은 production 인증 설정과 Java 런타임 누락으로 4 failed, 1,272 passed, 10 skipped였다. 세 번째는 개발 모드와 격리 복사한 Java 런타임에서 1,279 passed, 7 skipped, 236 subtests passed, 경고 44개였다. `py_compile main.py`는 복사본에서 통과했다. Python은 기존 가상환경의 3.14를 사용했다.
- Electron은 실행하지 않았다. 현재 테스트 보강만 했고 UI와 런타임 동작은 바꾸지 않았다. 실제 사용자 동작, 외부 HTTP 클라이언트와 과거 데이터의 전수 호환은 미검증이다.
