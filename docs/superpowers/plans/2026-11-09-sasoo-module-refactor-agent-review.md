# Sasoo 모듈별 리팩토링 조사와 실행 순서

**목표:** 현재 제품과 사용자 데이터 계약을 보존하면서 책임을 독립적으로 검토하고 되돌릴 수 있는 단위로 나눈다.

**방법:** 2026-11-09에 여섯 subagent가 실행 및 worker, API 및 DB, PDF 파서, frontend, Electron 및 빌드, 공급사 및 데이터 경계를 병렬로 읽기 전용 조사했다. 담당자가 주요 호출 경로와 CI, 파일 정리 동작을 재확인했다. 정적 조사이며 이번 조사에서 테스트, 앱, 공급사 또는 마이그레이션을 실행하지 않았다. 기존 graphify 그래프는 9월 산출물이므로 방향 파악에만 사용했다. 사용자 데이터, 미커밋 변경과 미완료 manifest 원형을 보존한다.

**관련 문서:** `docs/superpowers/plans/2026-11-09-sasoo-refactor-evidence-review.md`, `docs/superpowers/plans/2026-11-09-execution-provenance-verification-cost.md`, `docs/validation/2026-11-09-refactor-approved-abc-validation.md`, `docs/validation/2026-11-09-es2022-promise-build-verification.md`. 첫 문서의 삭제 제안 A/B/C 및 빌드 오류는 후속 검증 문서에서 완료 또는 해결된 상태다.

## 의존 관계와 전역 제약

- 작업 0의 동작 기준선 이후, 서로 수정 파일이 겹치지 않는 1A, 1B, 1C, 1D를 개별 변경으로 진행할 수 있다. 단, 공유 파일이나 테스트를 동시에 수정하지 않는다. 조사 병렬화와 코드 병합은 다르다.
- 각 작업은 실제 호출/동적 참조와 기존 diff 확인 → 현재 동작 고정 또는 재현 테스트 → 작은 변경 → 집중 검사 → 해당 단계 마지막 수정 기준 회귀 순으로 수행한다. 대상 조각의 복원 패치와 해시를 새 경로에 남긴다. 개별 삭제와 기존 데이터 교체는 대상별 승인 전 금지.
- API method/path/status/응답, 읽기 전용 요청의 수, 자동 생성 시점, 취소/스트리밍, 프롬프트와 모델/effort, 순서/병렬 구조, 캐시 키, 비용의 unknown/0, DB 및 이전 파일 호환을 보존한다. 공급사에는 호출하지 않는다.
- manifest 및 요청 원장과 파일 불변 버전은 미완료 별도 기능이다. `analysis_manifest_store.py`와 테스트를 미사용으로 분류하지 않는다. 다음 작업을 위해 임의로 연결, 삭제 또는 폐기하지 않는다.
- 기존 빌드/실험물은 격리 복사본에서 보호한다. `build:mac`, `build:win` 등 준비 스크립트는 실제 dist/build/cache 삭제를 수행하므로 원본에서 호출하지 않는다.

## 관찰한 중요 경계

1. `analysis_worker.py:52-57,82-90`은 generation을 heartbeat에 넘기지만 `run_full_analysis(paper_id)`와 `analysis_execution.py:458-496`의 결과 INSERT는 같은 generation fence를 사용하지 않는다. heartbeat 검사가 결과 쓰기까지 원자적으로 보호한다고 주장할 수 없다. manifest 원형은 제품 미연결이다.
2. `analysis_completion.py:83-89`는 schema를 문자열 `getattr`로 가져오고, `analysis_routes.py:88-105`는 실행 모듈의 private 함수들을 직접 import한다. 옮긴 함수를 재수출하더라도 import된 바인딩과 기존 test patch 지점이 달라지면 mock이 더 이상 적용되지 않을 수 있다.
3. `odl_parser.py:1098-1131,1270`은 새 목록이 참조하지 않는 `figures/*.png`를 최종 manifest 저장 전 정리한다. 현행 동작을 관찰한 것이며 사용자의 기존 파일을 삭제해도 된다는 뜻이 아니다. 파일 저장/정리 이동은 합성 파일 및 장애 주입 선행.
4. `FigureGallery.tsx:225-277`은 저장된 그림 설명이 없을 때 자동 생성 요청을 시작한다. cleanup은 결과 반영을 막지만 요청 abort는 아니며 `api.ts:735-793`은 진행 중 요청을 공유한다. 파일 분리 중 요청 횟수나 취소 의미를 바꾸지 않는다.
5. `gemini_client.py:200-207,308-317,350-358`은 사용량 누락을 0으로 대체하는 경로가 있고 `openai_client.py:222-246`은 일부 누락을 None으로 남긴다. 통합 과정에서 unknown을 0으로 바꾸지 않는다. 실제 청구 유무는 이 숫자만으로 증명할 수 없다.
6. 루트 AGENTS.md의 Node 20 설명과 현재 `.github/workflows/build-check.yml:29-35`, `release.yml:105-111`의 Node 24, pnpm 10.34.5 설정이 다르다. 코드가 아니라 문서 정확성 문제로 별도 정정 후보이며 사용자가 제공한 지침을 여기서 수정하지 않는다.

## 작업 0: 경계 고정 및 재현성

- 대상: 기존 `api/test_analysis_routes.py`, `services/test_analysis_parallel.py`, `services/test_analysis_worker.py`, `services/test_viz_partial_retry.py`, `services/test_odl_parser.py`, `frontend/src/hooks/requestEfficiency.test.js`, `frontend/src/hooks/useAnalysis.noGeneration.dom.test.tsx`, Electron unit tests.
- 합성 SQLite, PDF, 모의 공급사, 별도 profile과 외부 네트워크 차단을 사용한다. phase 입력/출력 순서, cache hit/miss, 취소, 요청/DB 쓰기 횟수, SQL transaction 및 API 응답을 각 작업에서 필요한 범위로 고정한다.
- 사용자에게 보이는 화면 흐름을 변경하는 작업은 1024/1440 격리 Electron에서 포커스, 스크롤, 로딩/실패/취소/레거시, console, 화면과 API/DB 값 대조를 수행한다. 테스트 통과는 외부 클라이언트 및 실제 사용자 데이터 호환 증명이 아니다.

## 1차: 한 책임씩 분리할 수 있는 후보

| 작업 | 현재 문제 및 대상 | 보존할 계약과 선행 검증 | 범위와 중단 조건 |
| --- | --- | --- | --- |
| 1A 보고서 | `api/analysis_routes.py:1063-1154`는 조회와 Markdown 조립을 섞고, 개별 단계 서식은 이미 `api/report_service.py`에 있다. | 합성 paper/ordered rows에서 현재 단계 순서, 404, None 비용/토큰, legacy/partial, generated_at을 고정. `test_report_service.py`, `test_analysis_routes.py`의 nullable report 테스트. | I/O 완료 후 조립만 후보. 응답 바이트와 patch 바인딩의 차이가 생기면 중단. |
| 1B UI 포맷 | `frontend/src/components/AnalysisPanel.tsx:388-684`는 `tryParseJson`, `formatValue`, 단계별 Markdown 구성과 렌더링이 결합된다. | fenced JSON, raw/raw_text, 빈/중첩 값, 0/1 점수, Markdown 및 레거시 요약을 고정. `AnalysisPanel.reading.dom.test.tsx`와 격리 Electron에서 인용, 읽기 위치 및 스크롤 확인. | 순수 변환 단위만 이동. 가시 텍스트, 상태나 키보드 동작이 달라지면 중단. |
| 1C PDF 엔진 | `services/odl_parser.py:848-870,913-942`의 순수 엔진 선택과 환경 검증, 실제 dispatch를 구분한다. | 명시 인자 > 전역 > 단계 환경 > 기본, 유효/무효, provider 키, Java 가용성 및 fallback 순서를 유지. `test_engine_resolution_refactor.py`, `test_odl_parser.py`, `test_odl_java_runtime.py`, `test_visual_parse_usage.py`. | 선택 로직만 먼저 분리한다. 파일 생성/삭제, manifest, DB 및 비용 기록은 이동하지 않는다. 선택이나 호출 수 차이 시 중단. |
| 1D 프런트 타입 | `frontend/src/lib/api.ts:13-475`의 도메인 타입과 요청 구현이 혼재한다. | 기존 import 경로와 타입 모양을 호환 재수출, `pnpm tsc --noEmit`, `pnpm test`, `pnpm lint`, `pnpm build`. 요청 URL, 인증, GET 재시도/POST 중복 금지의 기존 검사 유지. | 타입 단위만 한 그룹씩 이동하고 네트워크 함수는 그대로 둔다. 외부 import가 깨지거나 기존 이름 충돌 시 중단. |
| 1E 시각화 계획 | `services/analysis_execution.py:2567-2681`의 점수, 형태 검사, 정규화, 게이트. `analysis_routes.py`와 테스트 patch 참조를 먼저 확인. | legacy 계획, 이미지/Mermaid 수, importance 60 경계, Sunburst 선택과 순서, 유료 요청 수를 fixture로 비교. `test_synthesis.py`, `test_analysis_completion.py`, 관련 `test_analysis_routes.py`. | 순수 계산만 추출. 기존 점수, 항목 및 순서가 달라지면 중단. 시각화 저장/비용 원장은 건드리지 않는다. |

1A와 1B는 각각 독립적이지만 사용자에게 보이는 문구나 출력 계약을 바꿀 수 있으므로 기준 출력부터 고정한다. 1C, 1E도 계산은 순수하더라도 이후 공급사 호출을 결정하므로 요청 횟수 확인이 필요하다.

## 2차: 합성 장애 및 동시성 테스트가 선행되는 후보

| 영역 | 범위 및 실제 결합 | 사전 테스트와 중단 조건 |
| --- | --- | --- |
| API 상태 투영 | `analysis_routes.py:291-418`: DB, live status, completion, subprocess 상태와 비용/stale 모델. | 5 phase와 7 완료 검사, partial/legacy, 99% 상한, cancel 우선, 2초 polling과 SQL 수를 고정. 조회 횟수나 응답이 바뀌면 중지. |
| 문서 context | `document_context.py:261-363`: 파서, PDF signature, sidecar, 인용 갱신과 단계별 프롬프트 입력을 결합. | `test_document_context.py`, `test_quality_preflight.py`로 cache hit, sidecar 갱신, 인용 범위 및 프롬프트 바이트를 고정. 해시, 절단, 순서나 cache 결과가 다르면 중지. |
| 프런트 비동기 | `useAnalysis.ts` 세션 ID/공유 Promise/polling, `Workbench.tsx`, `useWorkbenchAnalysisControls.ts:51-79`. | 지연된 논문 A 응답 후 B 전환, 결과 실패 재시도, 자동 시작, refresh와 완료 polling을 mock으로 검사. `getSettings` 늦은 응답의 잘못된 시작 가능성은 미재현 가설이다. 유료 요청 금지. |
| 그림과 PDF | `FigureGallery.tsx`, `PdfViewer.tsx`: 요청 공유, focus trap, selection, zoom, PDF.js 수명. | 저장 설명 유무, 그림 전환, 요청 공유/횟수, 문서 교체 중 지연 응답, 페이지/검색/선택 및 cleanup을 synthetic fixture와 Electron으로 고정. 요청 취소 의미나 focus/스크롤 변경 시 중지. |
| 설정과 provider | `services/model_registry.py:132-163` 및 execution/supervisor가 `api.settings` 내부 함수를 지연 import. | `test_model_registry.py`, `test_provider_state.py`, settings DB/credential 테스트로 provider 우선순위, key, fallback과 patch 바인딩 고정. 모델/effort, 환경 적용 및 복호화 순서가 바뀌면 중지. |
| IPC와 프로세스 | `electron/main.ts:149-237`, `preload.ts:52-110`, `updater.ts`, `python-manager.ts`: 문자열 IPC, health HMAC, 프로세스 소유권. | 기존 launcher/stopper/quit 테스트에 채널/발신자/인자/응답, sync asset token, 리스너 해제 및 child 교체 이후 지연 이벤트 검증 추가. 타입은 `frontend/vite-env.d.ts`가 preload에서 이미 import하므로 복제하지 않는다. |
| 가격과 어댑터 | `services/pricing.py`, `services/llm/interactions_client.py`, `gemini_client.py`, `openai_client.py`. | 요금 날짜/단위, 기존 rows, cached token, 요청별 unknown/0, schema, stream 및 재시도/취소의 모의 SDK 테스트. 현재 공급사 차이를 단순 중복으로 합치지 않는다. |

## 3차: 실행 이력 및 데이터 계약과 함께 설계할 영역

- **시각화 저장 및 재생성:** `analysis_routes.py:661-726,825-945`, `analysis_execution.py:3097-3248`. 기존 result 문자열 비교 CAS, run ID/token, 최대 5회 재시도, 409/503, 성공 항목과 prior_requests 및 불명 비용을 하나의 계약으로 고정한다. `test_visualization_runs.py`, `test_viz_partial_retry.py`, `test_viz_costs.py`에 동시 writer와 장애 주입을 보강한다. 실행 manifest/fence 및 원장과 순서를 합의하기 전 저장 경계를 이동하지 않는다.
- **파일 및 DB 동기화:** `odl_parser.py:1339-1588,1691-2057`은 기존 중간 파일, 텍스트 승격, figure/table 동기화 및 각각 commit, 사용량을 결합한다. 합성 PDF/SQLite에서 쓰기, 정리, 취소, figure 성공 후 table 실패, DB 오류, 재시작을 주입하고 파일 바이트, 사용자 설명, 행 ID 및 사용량을 비교한다. 파일 원자성과 DB 트랜잭션 개선은 별도 동작 변경이다. 정적 순서상 일부 실패 이후 사용량 기록이 누락될 가능성은 있으나 재현하지 않았다.
- **실행 조율과 provenance:** `analysis_execution.py:3816`의 단계 순서, 조건부 citation/visual 병렬, synthesis/시각화 병렬, 이미지 순차 및 간격, 비용과 취소를 먼저 고정한다. `analysis_worker.py`, `analysis_supervisor.py`, 기존 실행 원형을 고려해 generation/attempt identity와 결과 fence를 같은 transaction으로 설계한다. 순수 리팩토링만으로 이 요구를 완료했다고 말하지 않는다.
- **DB migration:** `models/database.py:383-560`은 기동 schema와 여러 migration을 함께 처리하고 일부가 `except Exception: pass`다. 예외가 숨겨질 가능성은 코드상 관찰이며 데이터 손상은 미재현이다. 합성 구버전 DB, 반복 기동, WAL/FK, 기존 행/NULL, DDL 실패를 고정한 뒤 migration 구조와 오류 정책 변경을 별도 과제로 나눈다.
- **채팅과 SSE:** `analysis_routes.py:1432-1724`의 저장 여부, 스트림 이벤트, 토큰 전 재시도 및 토큰 후 실패, disconnect/cancel의 interrupted 저장을 모의 스트림으로 고정한다. 문구, prompt, effort, 비용과 전송 순서가 바뀌면 중지한다.
- **스크립트와 패키징:** `scripts/prepare-{mac,win}-build.js`, `scripts/build-backend.js`, `backend/sasoo-backend.spec`, `.github/workflows/`의 실제 경로, hidden import 및 정리 대상을 먼저 테스트한다. `backend/scripts/migrate_library.py`는 사용자 파일 복사 및 공급사 호출 가능성이 있으므로 조사 목적으로 실행하지 않는다.

## 확인하지 못한 범위와 다음 단계

외부 HTTP/Python/TypeScript 소비자, 모든 동적 호출, 실제 사용자 DB 및 과거 파일의 전수 호환, Windows/macOS packaged 앱과 실제 공급사 응답은 확인하지 못했다. 이번 조사에서 코드 수정이나 삭제를 수행하지 않았다. 각 1차 작업에 대해 파일, 정확한 삭제/이동 범위, 기존 diff, 전후 테스트를 구체화하고 사용자 승인 범위와 삭제 보호 조건을 확인한 뒤 진행한다.
