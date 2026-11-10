# Sasoo 리팩토링 및 미사용 코드 조사 계획

**목표:** 제품 동작과 사용자 자료를 보존하면서 사용하지 않는 코드의 근거를 확인하고, 결합이 큰 영역을 검증 가능한 단위로 정리한다.

**구조:** FastAPI 라우트, 백엔드 서비스와 워커, Electron main/preload, React 진입점과 동적 import, 빌드와 스크립트, 테스트를 각각 호출 경계로 조사한다. 삭제 후보와 구조 분리 후보를 별도로 관리한다.

**기술:** Python AST와 문자열 검색, TypeScript import 검색, pytest, Vitest, TypeScript, ESLint, 격리 Electron.

**연관 계획:** `docs/superpowers/plans/2026-11-09-execution-provenance-verification-cost.md`. 실행 이력 및 비용 작업은 미완료이며 관련 실험 코드를 무조건 삭제하지 않는다.

## 전역 조건

- 현 checkout의 미커밋 및 미추적 작업, 논문, DB, 응답, 이미지, 원장, 실험 자료, 캐시와 체크포인트를 보존한다. reset, stash, clean, 광범위한 staging, 자료 덮어쓰기와 삭제를 하지 않는다.
- 이 문서는 조사와 계획이다. 각 코드 삭제는 구체적 대상에 대한 별도 승인 후 진행한다. 유료 호출, 재생성, 배포, 릴리스는 하지 않는다.
- 각 작업은 합성 DB와 모의 공급사로 먼저 검증하고 기존 API, 모델과 effort, 캐시, 병렬 처리 및 동작 계약을 유지한다.
- 저장소의 자료 스냅샷, 이력 및 실험 스크립트는 제품 import 유무로 삭제 판정하지 않는다.

## 이번 조사 범위와 한계

- `sasoo/backend`의 api, models, services와 관련 테스트, `sasoo/frontend/src`, `sasoo/electron`, 패키지 스크립트 및 주요 FastAPI 라우트를 읽었다. Python은 최상위 함수 이름 및 AST import, 프런트엔드는 `.ts/.tsx` 파일 import와 export 텍스트를 이용한 1차 정적 스캔 후 후보를 `rg`로 수동 확인했다. 독립 실행 스크립트, 상대 import, 리플렉션, 문자열 간접 참조, 외부 API 소비자는 완전하게 파악하지 못했다. 이것은 전체 도달 가능성 증명이 아니다.
- 스캔에는 Python/TypeScript 소스와 테스트 321개 파일, 80,855줄이 포함됐다. 줄 수에는 테스트가 포함된다. 외부 의존성, 빌드 결과, 라이브러리 데이터와 문서는 규모 합계에서 제외했다.
- 기존 graphify 결과는 9월 기준이므로 방향 파악에만 사용했고, 최신성 때문에 삭제 근거로 사용하지 않았다. 그래프 재생성은 하지 않았다.
- 프런트엔드 파일 단위 스캔은 비테스트 import가 없는 `main.tsx`만 찾았지만 `index.html`에서 실행되는 진입점이다. 백엔드의 `conftest.py`는 pytest가 자동 발견한다. 둘 다 보존한다. 1차 스캔이 `.js` 테스트를 빠뜨릴 수 있어 후보마다 추가 검색했다.

## 후보 목록: 삭제 보류 및 추가 확인

| 대상 | 현재 확인한 사실 | 분류 및 삭제 전 확인 |
| --- | --- | --- |
| `backend/services/odl_parser.py:_resolve_pdf_engine` | 정의 외 현재 소스 참조를 찾지 못함. 본문은 `_resolve_stage_engine("text", engine)`의 하위 호환 별칭 | 가장 좁은 검토 후보. 외부 스크립트나 동적 호출과 호환 필요성을 확인한 후 PDF 엔진 선택 회귀 테스트 |
| `backend/api/settings.py:_set_setting` | 제품 호출은 찾지 못했고 `_set_settings`가 실제 설정 저장에 사용됨. `api/test_settings.py`가 기존 이름을 여러 번 patch하고 한 테스트는 호출되지 않았음을 검증 | 테스트 의도가 현재 저장 경로를 실제로 보호하는지 먼저 검토. 교체할 테스트는 credential store 오류 시 `_set_settings` 호출이 없는지와 DB 값 불변을 검증해야 함. 기존 테스트를 단순 삭제하지 않음 |
| `backend/services/odl_parser.py:paper_artifacts_are_current` | 제품 호출은 찾지 못했고 파서 테스트에서 참조. 텍스트와 시각 결과의 현재 상태를 함께 검사 | 테스트 전용 API 또는 외부 호출 가능성 확인. 각 단계의 현재 상태 검사가 유지되는지 확인 |
| `backend/services/odl_parser.py:ensure_parsed_artifacts` | 제품 호출은 찾지 못했고 테스트에서 사용. 텍스트와 시각 결과를 모두 준비하는 호환 wrapper | 외부 스크립트 및 과거 API 사용 여부를 확인. 강제 실행, 파일 저장 및 합성 PDF 테스트의 목적을 유지 |
| `backend/services/evidence_verifier.py:build_pdf_index` | 제품 호출은 찾지 못했고 `test_evidence_verifier.py`에서 사용. PDF 파일을 열어 인덱스를 만드는 함수 | 테스트 지원 함수인지 공개 진입점인지 판정하고 증거 검증 회귀를 유지 |
| `frontend/src/lib/api.ts:getMermaid` | 제품 호출은 찾지 못했고 `requestEfficiency.test.js`의 생성 호출 방지 검증에서 mock 사용. 해당 백엔드 GET은 실제 생성 요청과 비용을 유발할 수 있음 | 프런트엔드 wrapper와 백엔드 공개 HTTP 경로를 별개로 검토. 경로 삭제를 추론하지 말 것. 자동 유료 생성 금지 테스트를 유지 |
| `backend/services/analysis_manifest_store.py` 및 테스트 | 현재 테스트에서만 참조. 직전 작업에서 작성한 미연결 트랜잭션 실험으로 실행 이력 계획과 연관 | **진행 중 작업으로 보존**. 완성, 대체, 폐기 중 별도 결정 필요. 현재 제품의 fence 보장이 아님 |
| `frontend/src/hooks/useAnalysis.ts`의 `mermaid: null`과 `VisualizationGallery.tsx`의 `legacyMermaid` 경로 | 현재 hook은 null을 반환하고 갤러리에는 legacy 분기가 있음 | 데이터 흐름을 모든 호출자와 레거시 fixture로 추적. 과거 사용자 데이터 호환과 실제 경로를 증명하기 전 보존 |

위 목록은 1차 후보이며 안전한 삭제 목록이 아니다. 데이터와 증거 산출물은 후보가 아니다.

## 검토 우선순위: 크고 실제로 사용되는 영역

1. `backend/services/analysis_execution.py` 4,214줄: 캐시, 단계 실행, 시각화 계획 및 저장, synthesis와 실행 조율이 함께 있다. `run_full_analysis`와 worker, API가 실제 사용한다. 실행 identity 및 비용 원장 작업과 충돌하지 않도록 해당 미완료 계획을 먼저 기준선으로 삼고 동작을 고정한 뒤, 순수 시각화 계획/검증 또는 캐시 키 같은 독립 책임부터 소규모 추출한다. 프롬프트와 단계 순서를 바꾸지 않는다.
2. `backend/api/analysis_routes.py` 1,773줄: 분석 상태, 시각화, 채팅, 보고서가 함께 있다. 라우트 등록과 경로, response model, 예외, streaming을 먼저 목록화하고 책임별 router 분리를 검토한다. 공개 HTTP 경로는 유지한다.
3. `backend/services/odl_parser.py` 2,148줄: 텍스트와 시각 추출, 캐시와 manifest, 엔진 선택이 결합돼 있다. 파일 생성 및 기존 산출물 승격이 있으므로 합성 PDF에서 파일/해시/상태 전후를 비교한 뒤 엔진 선택 같은 순수 로직부터 분리한다.
4. `frontend/src/components/AnalysisPanel.tsx` 1,220줄과 `frontend/src/lib/api.ts` 1,170줄: 화면과 표시 로직, 네트워크 모델이 크다. 우선 JSON 표시 및 표시 상태 계산과 API 타입 경계를 추출하되 네트워크 요청 횟수, 접근성, 키보드 동작을 유지한다.
5. `frontend/src/pages/Workbench.tsx`, `PdfViewer.tsx`, `FigureGallery.tsx`: 실제 사용자 작업 흐름이므로 파일 크기만으로 분리하거나 기능을 삭제하지 않는다. 상태 소유권과 스크롤, 선택, polling, 요청 취소의 경계를 먼저 기록한다.

## 실행 단계와 수용 기준

### 0. 기준선과 실제 진입점

- [ ] 기존 변경과 조사할 파일의 상태 및 해시를 별도 새 경로에 기록한다. 실제 사용자 DB와 유료 증거는 복사하거나 수정하지 않는다.
- [ ] FastAPI `include_router`, Electron main/preload와 IPC, React `main.tsx`, lazy import, 스크립트, 테스트 자동 발견, 빌드 설정을 진입점으로 목록화한다.
- [ ] 기존 계약 테스트를 격리 환경에서 실행하고 실패와 미검증을 기록한다. 기존 빌드 산출물은 별도 복사본에서 검증한다.

### 1. 후보별 삭제 가능성 증명

- [ ] 각 후보에 대해 정의와 모든 정적 참조, 동적 import 및 문자열 호출, 테스트만의 참조, 외부 스크립트/공개 API, git 상태를 기록한다.
- [ ] 테스트만 참조하는 코드라도 해당 테스트가 보호하는 실제 행위를 확인하고 대체 테스트를 먼저 준비한다. 사용하지 않는 것으로 보이는 공개 경로는 외부 소비를 확인할 수 없으면 보존한다.
- [ ] 후보마다 `유지`, `추가 조사`, `삭제 제안`과 정확한 코드 범위, 근거, 회귀 테스트, 복원 방법을 표로 작성한다. 구체적 대상에 대한 별도 결정 전에는 삭제하지 않는다.

### 2. 좁은 코드 정리

- [ ] 별도 결정된 한 후보만 변경하고 해당 모듈의 집중 테스트를 실행한다. `_set_setting`은 patch 제거 전에 credential 오류의 실제 `_set_settings` 비호출과 데이터 불변을 증명한다.
- [ ] `getMermaid` 검토 시 hook의 시각화 없음과 조회 실패에서 네트워크 생성 0회 검증을 유지하고 백엔드 HTTP 계약은 별도로 판정한다.
- [ ] PDF 호환 함수는 유효/무효 캐시, 누락 파일, force와 두 단계 상태, 외부 진입점 검토가 끝나기 전 제거하지 않는다.

### 3. 큰 모듈의 책임별 분리

- [ ] 먼저 기존 입력과 출력, 오류 및 동시성 동작을 고정하는 테스트를 추가한다. 새 추상화는 하나의 실질적 책임만 옮기고 각 이동 후 관련 테스트를 실행한다.
- [ ] 실행 파이프라인은 screening, citation, visual, recipe, deep dive, synthesis, visualization의 데이터 전달과 캐시 재사용, 취소, fence 요구를 추적해 기존 동작을 보존한다. 진행 중인 실행 이력 설계는 완료 여부를 따로 관리한다.
- [ ] API 라우트 분리 시 경로, 메서드, 스키마 및 오류와 SSE 출력을 비교하고 이전 데이터 fixture로 회귀한다.
- [ ] 프런트엔드 분리는 같은 API 호출과 로딩/오류/취소 상태를 DOM 테스트로 비교하고 1024/1440 화면과 키보드를 격리 Electron에서 확인한다.

### 4. 최종 검증

- [ ] 변경한 기능의 집중 pytest/Vitest, 백엔드 전체 `./.venv/bin/python -m pytest services api models tools/test_luna_compare.py`, `python -m py_compile main.py`, 프런트엔드 `pnpm test`, `pnpm tsc --noEmit`, `pnpm lint`, `pnpm build`를 마지막 코드 수정 이후 실행한다.
- [ ] Electron 변경 시 `pnpm build:electron`을 추가한다. 화면 또는 API 흐름을 바꾼 경우 합성 DB, 별도 profile, 외부 네트워크 및 생성 요청 차단 하에 Electron GUI, 콘솔, 포커스, 스크롤을 확인한다.
- [ ] 실패, 미실행, 호환성 한계, 삭제 범위와 남은 위험을 기록한다. 모의 테스트는 공급사 청구나 실제 논문 결과의 과학적 검증이 아니다.

## 주요 위험

- 전역 검색에서 참조가 없어도 FastAPI decorator, pytest 자동 로딩, Electron preload, 동적 import, 외부 HTTP 클라이언트는 실제 진입점일 수 있다.
- 테스트 전용 helper 삭제는 현재 실제 동작을 검증하는 테스트의 약화를 숨길 수 있다.
- 거대한 파일을 한 번에 분리하면 캐시 키, 실패 처리, 결과 저장과 실행 순서가 변할 수 있다.
- 과거 시각화와 실행 데이터의 호환 경로는 새 화면에서 안 쓰인다는 이유만으로 삭제할 수 없다.
- 미완료 manifest, 검증 증거와 비용 원장 작업의 경계를 리팩토링과 혼동하지 않는다.
