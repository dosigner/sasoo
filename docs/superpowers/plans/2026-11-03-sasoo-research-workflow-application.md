# Sasoo Research Workflow Application Implementation Plan

> 실행자를 위한 안내: 이 문서는 개발 적용 계획이다. 이번 요청의 산출물은 계획서와 조사 자료이며 구현, 유료 평가, 배포 승인을 뜻하지 않는다. 구현 시 기존 변경을 보존하고 아래 체크박스 단위로 진행한다. 사용하지 못하는 실행 스킬이나 별도 에이전트를 필수 의존성으로 두지 않는다.

**Goal:** 논문 한 편에서 이해, 근거 확인, 읽기 재개, 재현 조건 정리가 이어지는 Sasoo 워크플로우를 개선한다.

**Architecture:** 기존 Library → Workbench 구조와 분석 단계/설명 깊이를 유지한다. PDF, 분석, 근거의 상태를 명시적으로 연결하고 기존 검증기와 실행기를 재사용한다. 대규모 에이전트 프레임워크 이식 대신 검증된 설계 원칙을 필요한 경계에 적용한다.

**Tech Stack:** Electron, React/TypeScript, Vite, FastAPI, SQLite/aiosqlite, PDF.js. 신규 라이브러리 추가 없이 시작한다.

**Spec:** 이 대화의 Top 20 제안, 사용자의 논문 비교 제외 지시, 10월 이후 agentic research 조사 요청. 조사 근거는 [별도 보고서](../../validation/2026-11-03-agentic-research-methods.md), 현재 제품 결정은 [product-decisions.md](../../product-decisions.md)를 함께 읽는다.

작성일: 2026-11-03. 상태: 적용 제안, 구현 전. 원래 Top 20 번호를 유지해 추적한다.

## 1. 범위와 지켜야 할 조건

- 논문 간 비교(#6)는 제외한다. 비교 화면, 비교 API, 비교 테이블, 비교용 선행 작업을 만들지 않는다.
- 복수 논문 질의(#16)도 이번 적용에서 보류한다. 비교 기능을 우회해 추가하지 않는다.
- 단일 논문의 기존 용어 비교, 원문과 해설 동시 보기, 기존 검증 도구의 동작은 유지한다.
- 분석 항목, 모델/effort, 설명 깊이, 기존 분석 단계의 선후 관계를 임의로 바꾸지 않는다.
- `docs/product-decisions.md`의 Library → Workbench 유지와 Zotero 보류 결정을 존중한다. 컬렉션, 외부 연동, 실험 자동화는 후속 후보이며 이번 출시의 의존성이 아니다.
- 현재 미커밋 변경, 원문, 유료 응답, 원장, 검증 자료를 보존한다. reset/stash/clean, 일괄 덮어쓰기, 기존 요청 재실행을 하지 않는다.
- 문서에 제시한 신규 타입/API/파일은 설계안이다. 현재 구현된 인터페이스로 오인하지 않는다.
- 사용자 표시는 한국어, 코드 주석은 짧은 영어로 작성한다. 이 문서의 용어를 제품에서 불필요하게 노출하지 않는다.
- 기존 중립색과 보라색 강조, 공통 UI 컴포넌트, 키보드 동작, reduced motion 설정을 유지한다.
- 추가 모델 호출은 별도 비용을 수반한다. 오프라인 작업과 유료 평가를 분리한다.

## 2. 현재 코드에서 확인한 사실과 해석

| 확인한 사실 | 계획에 미치는 영향 |
| --- | --- |
| `AnalysisPanel.tsx`에 summary/synthesis/guide/terminology/figures/tables/recipe 7개 탭이 있다. | 기능 추가보다 접근 구조와 설명을 정리한다. 탭 key는 보존한다. |
| `PdfViewer.tsx`는 `pagechanging`, `scalechanging`, `pagesinit` 이벤트를 사용한다. | 별도 PDF 뷰어 없이 읽기 상태 저장을 연결한다. 초기 page-width 적용과 복원 순서를 조정해야 한다. |
| `useWorkbenchLayout()`은 20~80% 분할, 기본 50%, 기존 프리셋과 스프링 동작을 제공한다. | 저장된 값을 기존 제어기로 복원한다. 새 레이아웃 엔진을 만들지 않는다. |
| `Recipe.evidence`, `reproduction_check`, `EvidenceAnchor`와 원문 이동이 존재한다. | 근거 검증을 새로 구현하지 않고 표시 체계부터 통합한다. |
| EvidenceAnchor bbox는 PDF 포인트, 좌하단 원점이다. | DOM 픽셀 좌표와 혼동하지 않고 `pdfHighlight.ts`를 사용한다. |
| 레시피에 모델 신뢰도/재현성 %와 별도 완전성 점검이 표시된다. | 모델의 자체 판단과 결정론적 대조 결과를 같은 수준의 검증으로 표시하지 않는다. |
| 첫 분석 비용은 고정 범위, 이력은 전체 평균/최대를 사용한다. | 가격을 추정 근거와 함께 표시하고 개인별 과거 비용과 이번 예상 비용을 구별한다. |
| 라이브러리 SQL 검색은 제목/저자/태그/notes 대상이다. | 전체 본문 검색은 별도 로컬 색인 작업으로 분리한다. |
| `analysis_runs`는 `paper_id`가 PK인 현재 실행 조율 테이블이다. | 이를 과거 실행 이력으로 사용하지 않는다. |
| `analysis_results`는 단계 결과 행을 누적하지만 실행 전체 묶음은 별도 확인이 필요하다. | 과거 결과를 단순 timestamp로 묶어 완전한 실행 이력인 것처럼 만들지 않는다. 향후 snapshot 식별자를 도입한다. |
| `guideCache.ts`는 IndexedDB 캐시이며 메모리 fallback을 허용한다. | 사용자 연구 노트를 여기에 저장하지 않는다. 영구 저장 실패를 성공으로 숨기지 않는다. |

판단: 읽기 복원과 정보 구조는 비교적 작은 변경으로 개발 가능하다. 실제 예산 제한, 부분 재실행, 과거 실행 복원은 실행기와 데이터 정합성을 다뤄야 하므로 별도 작업으로 나눈다. 이 난이도는 소스 검토에 따른 추정이며 구현 결과가 아니다.

## 3. 최근 방법론 중 채택할 원칙

| 원칙 | 참고 | Sasoo에 적용할 최소 형태 | 이번에 가져오지 않는 부분 |
| --- | --- | --- | --- |
| 단계별 산출물과 검증 기준 | Agentic Scientist | 완료/부분 완료/검증 대기를 구분하고 결과별 필수 자료를 확인 | 자동 실험, 논문 자동 작성 |
| 주장 → 근거 → 입력 버전 연결 | Agent Cockpit, OneSearch-VL | 원문 signature, 결과 ID, 검증 버전을 따라가며 오래된 근거를 표시 | 코드 전체 그래프, 모델 학습 |
| 조사 결과를 재사용하기 전 검증 | PANINI-DR | 인용 구절/페이지/수치 검사부터 수행하고 의미 검토는 별도 상태로 관리 | 무제한 에이전트 토론과 자동 재시도 |
| 지속 상태와 재개 가능한 단계 | MatOS, Épi | 읽기 상태와 실행 상태를 분리하고 저장된 결과를 보존 | 동적 DAG 수정, 자동 스킬 진화 |
| 부족한 근거를 행동 목록으로 반환 | Optimist | 누락 페이지, 단위 충돌, 조건 미확인을 사용자 확인 목록으로 변환 | 웹 전체 자동 확장 검색 |
| 평가 조건 동결 | ResearchBoost-Agent | 같은 원문/설정/완료 기준으로 정확성, 시간, 비용을 따로 검증 | GPU 학습 최적화 |
| 코드로 독립 조회를 묶는 방식 | OpenSaC | 기존 Python 서비스에서 독립적인 근거 조회만 제한 병렬화 | 생성 Python 코드의 임의 실행 |

이 표는 방법론을 Sasoo에 옮긴 설계 판단이다. 타 논문의 성능 수치를 Sasoo 성능 개선률로 환산하지 않는다.

## 4. 단계별 적용 순서

| 단계 | 원래 항목 | 결과물 | 진입 조건 |
| --- | --- | --- | --- |
| A: 읽기 지속성 | #2, #3, #11, #12 | 읽기 재개, 목적별 탭, 이어 읽기 홈, 읽기 밀도 | 현재 동작 기준선 확보 |
| B: 근거와 비용 가시성 | #1, #5 전반 | 근거 상세, 오래된 결과 표시, 정직한 예상 비용 | A 완료와 저장 규칙 검증 |
| C: 실행 제어 | #5 후반, #10, #9 | 요청 전 예산 확보, 결과 snapshot, 안전한 부분 재실행 | B 완료, 입력/결과 식별 확정 |
| D: 단일 논문 생산성 | #14, #13, #20, #18 | PDF 탐색, 자료 고정, 명령 검색, 예제 안내 | A/B와 독립 출시 가능 |
| E: 후속 선택 항목 | #4, #8, #17, #19 | 노트, 전문 검색, 실험 기록, 다중 가져오기 | 별도 범위 확정 후 각각 독립 구현 |
| 보류 | #6, #7, #15, #16 | 비교, 프로젝트 컬렉션, 외부 문헌 연동, 복수 논문 질의 | 이번 계획에서 구현하지 않음 |

첫 개발 묶음은 A와 B의 표시 개선으로 제한하는 것을 권장한다. C까지 한 릴리스에 강제하지 않는다. 날짜/인일은 기존 변경 통합 및 기준선 실행 후 산정한다.

## 5. 파일 책임 지도

경로는 저장소 루트 기준이다. `신규`는 아직 존재하지 않는 제안이다.

| 책임 | 수정 대상 | 신규 대상 |
| --- | --- | --- |
| 읽기 상태 | `sasoo/frontend/src/pages/Workbench.tsx`, `components/PdfViewer.tsx`, `components/AnalysisPanel.tsx`, `hooks/useWorkbenchLayout.ts` | `frontend/src/lib/readingState.ts`, `backend/models/reading_state.py` (각각 sasoo/ 아래) |
| 읽기 저장 API | `sasoo/backend/api/papers.py`, `models/database.py`, `models/schemas.py`, `sasoo/frontend/src/lib/api.ts` | 관련 API/모델 테스트 |
| 탭/홈/밀도 | `sasoo/frontend/src/components/AnalysisPanel.tsx`, `pages/Home.tsx`, `index.css`, `lib/strings.ts`, `pages/Settings.tsx` | 필요한 작은 DOM 테스트 |
| 근거 | `sasoo/frontend/src/lib/evidence.ts`, `components/RecipeCard.tsx`, `lib/pdfHighlight.ts`, `sasoo/backend/services/evidence_verifier.py`, `models/evidence_anchors.py` | `frontend/src/components/workbench/EvidenceDetails.tsx` |
| 비용 | `sasoo/frontend/src/lib/workbenchSummaries.ts`, `components/CostDashboard.tsx`, `sasoo/backend/api/settings.py`, `services/pricing.py`, `services/llm/openai_client.py`, `services/llm/gemini_client.py` | `backend/services/request_budget.py` (C에서만) |
| 이력/재실행 | `sasoo/backend/services/analysis_execution.py`, `services/analysis_supervisor.py`, `models/analysis_runs.py`, `api/analysis_routes.py`, `sasoo/frontend/src/hooks/useAnalysis.ts` | `backend/models/analysis_snapshots.py`, 관련 모델/API 테스트 |

표의 frontend/backend 축약 경로는 모두 `sasoo/` 하위다. 기존 거대 컴포넌트 전체 재작성이나 무관한 정리는 하지 않는다.

## 6. A 단계 상세 작업

### A1. 기준선과 데이터 보존

- [ ] 수정/미추적 파일 목록과 작업 대상 해시를 기록한다. 사용자 실험 결과를 복사하거나 정리하지 않는다.
- [ ] 구현은 선택한 현재 변경을 보존하는 분리 브랜치/작업 공간에서 진행한다. 무조건 HEAD 기반으로 시작해 현재 로컬 기능을 잃지 않도록 대상 파일을 대조한다.
- [ ] 같은 저장 결과로 1440×900, Electron 최소 1024×680, 밝은/어두운 테마의 홈/Workbench/레시피를 캡처한다.
- [ ] 모델 요청을 차단한 fixture와 실제 앱 관찰을 구분한다. 현재 실패하는 테스트는 기준선으로 기록한다.

완료 기준: 사용자 변경이 그대로 유지되고, 변경 전 화면과 동작을 같은 데이터로 재현할 수 있다.

### A2. 읽기 위치 저장과 복원 (#2)

선택: 사용자 재방문 정보는 SQLite에 저장한다. 브라우저 캐시와 분리해 앱 재실행과 저장소 오류를 다룬다.

제안 계약:

```ts
type AnalysisTab = 'summary' | 'synthesis' | 'guide' | 'terminology' | 'figures' | 'tables' | 'recipe';
type ReadingState = {
  schemaVersion: 1;
  pdfSignature: string;
  page: number;
  zoom: 'page-width' | 'page-fit' | number;
  activeTab: AnalysisTab;
  analysisScroll: Partial<Record<AnalysisTab, number>>;
  splitPercent: number;
  pdfCollapsed: boolean;
  lastOpenedAt: string;
};
```

`page`는 사용자에게 보이는 1부터 시작하는 PDF 페이지 번호, 숫자 zoom은 PDF.js 배율(1=100%), scroll은 CSS px, splitPercent는 PDF 영역의 백분율이다. lastOpenedAt은 서버 UTC 시각을 사용한다.

- 신규 `GET /api/papers/{id}/reading-state`: 저장값 또는 null. 존재하지 않는 논문은 404.
- 신규 `PUT /api/papers/{id}/reading-state`: 검증된 전체 상태를 원자적으로 저장. 서버가 갱신 시각 부여.
- DB는 논문 FK, PDF signature, schema version, JSON 상태, 열람 시각을 보관한다. `pdfSignature`는 기존 서명 생성 방식을 재사용하고 신뢰하지 않는 클라이언트 값은 서버 원문과 대조한다.
- `PdfViewer`에 `initialView`와 `onViewChange`를 추가하되 기존 props를 호환 유지한다. PDF 준비 후 페이지 수로 보정하고 저장된 배율을 적용한다.
- `AnalysisPanel`에 초기 탭/탭별 스크롤과 변경 콜백을 추가한다. 내부 인용 이동은 기존 동작을 우선한다.
- `useWorkbenchLayout(initialLayout?)`로 유효한 저장 분할을 초기화한다. 기존 20~80% 범위와 프리셋을 유지한다.

작업:

- [ ] `readingState.test.ts`에 손상 JSON, NaN, 알 수 없는 탭, 범위 밖 split, schema version 불일치 정규화 테스트를 작성하고 실패를 확인한다.
- [ ] `test_reading_state.py`에 논문 간 격리, signature 불일치 거부, 반복 저장, 앱 재연결 시 조회 테스트를 추가한다.
- [ ] 모델/마이그레이션/API를 구현하고 migration 두 번 실행 시 데이터가 유지됨을 검사한다.
- [ ] 뷰어 이벤트를 500ms debounce해 저장한다. 경로 전환 전 최신 상태를 기존 paperId로 flush하고 뒤늦은 A 응답이 B를 덮어쓰지 못하게 한다.
- [ ] 초기 복원이 끝나기 전에 기본값을 저장하지 않는다. DB 오류는 `읽기 위치를 저장하지 못했어요`로 알리고 논문 읽기는 계속 가능하게 한다.
- [ ] 동일 signature에서 PDF 12페이지, 125%, 레시피 탭, 67% 분할을 저장하고 앱을 종료/재실행해 복원한다. signature가 바뀌면 위치를 초기화하고 원문 변경을 알린다.

검증: 신규 테스트, 기존 AnalysisPanel 읽기 테스트와 PDF 하이라이트 테스트를 실행한다. 페이지 범위, 배율, PDF 숨김, 키보드 리사이즈가 유지되는지 실제 GUI로 확인한다.

### A3. 탭 구조 정리 (#3)

기존 tab key를 유지한다. 새 1차 그룹은 `이해`(summary/synthesis/guide/terminology), `원문 자료`(figures/tables), `재현`(recipe)이다. 기본 상세 탭은 각각 summary/figures/recipe이며 사용한 상세 탭은 기억한다. 상위 그룹은 하위 탭에서 계산해 중복 상태를 만들지 않는다.

- [ ] `AnalysisPanel.reading.dom.test.tsx`에 7개 기존 기능 접근, 그룹별 상세 탭, 인용 클릭 시 그룹 자동 변경, 읽던 곳 복귀 테스트를 추가한다.
- [ ] 요약은 `단계별 분석`, 종합은 `핵심 내용 연결`이라는 보조 설명으로 역할을 구분한다. 기존 결과 본문과 프롬프트는 변경하지 않는다.
- [ ] 기존 버튼 패턴을 유지하며 키보드로 모든 항목에 접근하게 한다. ARIA tab 패턴으로 바꾸면 화살표/Home/End와 roving focus까지 함께 구현한다.
- [ ] 1024px 창, 200% 확대, 긴 제목에서 클릭 가능한 탭이 가려지지 않는지 확인한다.

완료 기준: 기존 기능 7개가 모두 접근 가능하고 요약/종합의 용도를 화면에서 이해할 수 있다. 기존 인용 이동과 복귀 테스트가 통과한다.

### A4. 이어 읽기 홈과 읽기 설정 (#11, #12)

- [ ] A2 서버 상태를 기준으로 최근 열람 5편을 조회하는 목록 옵션을 `papers.py`와 `getPapers` 타입에 추가한다. 업로드/분석 시각과 혼용하지 않는다.
- [ ] 저장된 열람이 있으면 홈 상단에 제목, 마지막 페이지, 이어 읽기 버튼을 배치한다. 없으면 기존 업로드 동선을 유지한다.
- [ ] 삭제/원문 변경된 항목, 로딩, 조회 오류를 테스트한다. 조회 오류를 신규 사용자 상태로 표시하지 않는다.
- [ ] 전역 읽기 설정은 본문 14/16/18px, 밀도 `compact/comfortable` 두 값으로 제한한다. 기본 16px, 기존 테마 저장 패턴을 재사용한다.
- [ ] 본문/표/코드가 넘치지 않는지 검사한다. 글자 확대를 이유로 원문 PDF 전체 색상이나 과학 그림 색상을 변형하지 않는다.

완료 기준: 재방문자는 홈에서 한 번의 논문 열기로 저장된 화면을 재개하고, 설정은 앱 재실행 후 유지된다.

## 7. B 단계 상세 작업

### B1. 근거 상태와 원문 상세 통합 (#1)

데이터는 기존 `Recipe.evidence`, `reproduction_check`, `EvidenceAnchor`를 그대로 사용한다. `EvidenceDetails`는 새 검증기가 아니라 표시 컴포넌트다.

- [ ] `EvidenceDetails` 입력은 `{ anchor: EvidenceAnchor; onJump: (anchor: EvidenceAnchor) => void }`로 제한한다.
- [ ] 검증기가 확인한 `matched_quote/matched_page`와 모델이 제안한 `claimed_quote/claimed_page`를 구분한다. 실패 시 모델 페이지를 검증된 위치로 승격하지 않는다.
- [ ] 기존 display_status를 설명 문구에 매핑한다. 알 수 없는 상태는 `확인 기록을 해석하지 못했어요`로 처리한다.
- [ ] 인용문 일치, 수치/단위 일치, 페이지 확인과 의미상 뒷받침을 별도로 표시한다. 모델의 신뢰도 %는 정확도처럼 쓰지 않고 `모델 자체 추정`으로 설명한다.
- [ ] bbox가 있으면 기존 변환기로 강조하고, 없으면 페이지 이동만 제공한다. 단위/부호/범위가 다른 수치는 자동 통과시키지 않는다.
- [ ] 원문 signature 또는 결과 버전이 다르면 `원문/분석 변경 후 다시 확인 필요`로 표시한다. 사용자 확인 기록은 해당 버전에만 귀속한다.
- [ ] 테스트: 정상 앵커, null evidence, 미일치, claimed만 존재, bbox 없음, 변경된 원문, 기존 recipe의 과거 스키마.

완료 기준: 레시피 주요 파라미터에서 근거 구절과 확인 범위를 볼 수 있고, 검증되지 않은 항목에 성공 표시가 나오지 않는다. 요약의 일반 문장은 기존 인용 링크를 유지하며 문장별 신규 검증을 완료했다고 주장하지 않는다.

### B2. 비용 안내의 근거 표시 (#5 전반)

- [ ] `buildAnalysisConfirmCopy`에서 고정 첫 분석 범위를 검증된 현재 가격인 것처럼 표시하지 않는다. 공급사/모델/예정 작업을 설명하고 산정 자료가 없으면 `예상 비용 산정 전`으로 표시한다.
- [ ] 추정값을 제공할 때 입력 토큰 추정, 출력 상한, 이미지 작업 포함 여부, 가격표 버전과 산정 범위를 함께 보관한다. 가격 정보는 구현 시 공식 공급사 자료로 갱신 확인한다.
- [ ] 이미지/수리/검증처럼 별도 요청인 항목을 예상 합계에 포함하거나 미포함임을 명시한다. 전체 이력 평균/최대는 참고값으로 분리한다.
- [ ] usage 누락은 `미확정`으로 유지한다. 서버 조회 실패나 null을 0달러로 바꾸지 않는다.
- [ ] `workbenchSummaries.test.ts`, `CostDashboard.dom.test.tsx`에서 추정 없음/기록 없음/비용 미확정/조회 실패를 검증한다.

완료 기준: 사용자가 이번 실행의 추정과 과거 비용, 확정 비용과 미확정 비용을 구별할 수 있다. 이 단계만으로 실제 강제 예산 한도가 생긴 것은 아니다.

## 8. C 단계 상세 작업

### C1. 요청 전 예산 확보 (#5 후반)

선택: `services/request_budget.py`에 실행별 예산 상태를 보관하고 실제 공급사 요청 직전 통과시킨다. 비용 대시보드의 사후 합산을 예산 제한으로 사용하지 않는다.

- 제안 상태: `limit_usd`, `settled_usd`, `reserved_usd`, `unknown_usd_count`, `run_id`.
- 제안 함수: `reserve_request(run_id, request_id, upper_bound_usd)`, `settle_request(request_id, usage)`, `mark_request_unknown(request_id, reason)`.
- 예약은 SQLite transaction으로 원자화하고 request_id에 UNIQUE 제약을 둔다. 병렬 요청이 같은 잔액을 중복 사용하지 못하게 한다.
- 상한을 산정할 수 없으면 `엄격한 요청 한도` 모드에서 발행하지 않는다. 공급사 과금이 이미 발생한 호출의 환불/취소를 보장하지 않는다.
- 이미지/채팅/그림 해설은 적용 범위를 명시한다. 1차는 분석 실행으로 제한하고 다른 기능까지 한도가 적용된 것처럼 표시하지 않는다.

- [ ] 순수 fixture로 동시 예약 경쟁, 실패 정산, 중복 정산, usage 누락, 취소 직후 응답, 재시작 복구를 테스트한다.
- [ ] OpenAI/Gemini 실제 호출 경계를 확인해 네트워크 전 예약한다. 내부 재시도도 각각 발행 여부를 추적한다.
- [ ] 초과/미확정일 때 새 발행을 중단하고 기존 완료 결과를 유지한다.
- [ ] 프로바이더 호출을 차단한 통합 테스트에서 실제 발행 횟수와 원장 예약/정산 수가 맞는지 확인한다.

완료 기준: 병렬 실행에서도 예약 가능한 잔액을 초과한 새 요청이 시작되지 않는다. 표시만 멈추는 구현은 불합격이다.

### C2. 새 실행의 결과 snapshot (#10)

중요: `analysis_runs`의 현재 상태 행을 과거 이력으로 재사용하지 않는다. 기존 결과에서 완전한 과거 실행을 임의 복원하지 않는다.

- [ ] 신규 snapshot 식별자를 실행 시작에 부여하고 원문 signature, 모델/설정 fingerprint, 부모 snapshot, 단계별 result ID, 산출물 manifest/hash를 연결한다.
- [ ] 생성 이미지/HTML/표 파일도 내용별 불변 경로로 보존한다. DB JSON만 남기고 같은 파일명을 덮어쓰는 방식은 허용하지 않는다.
- [ ] 중단/실패 snapshot도 상태와 함께 보관하고 완료된 버전처럼 보여주지 않는다.
- [ ] 과거 레거시 결과는 `실행 묶음 정보 없음`으로 표시한다. 유료 재분석으로 자동 보충하지 않는다.
- [ ] Workbench에서 특정 단일 논문의 과거 snapshot을 읽기 전용으로 연다. 버전 간 자동 비교 화면은 이번 범위에서 제외한다.
- [ ] 테스트: 새 실행 실패 후 이전 완료 결과 열기, 산출물 hash 보존, 누락 파일, 레거시 행, 모델 변경.

완료 기준: 재분석으로 이전에 열 수 있던 결과/파일이 소실되지 않으며 표시한 버전에 맞는 원문과 결과를 조회한다.

### C3. 의존 관계를 보존한 부분 재실행 (#9)

- [ ] 실행기의 실제 입력 소비 관계를 기준으로 무효화 범위를 도출한다. 기존 prompt/전달 문맥을 읽고 테스트로 고정한다.
- [ ] `POST /api/analysis/{id}/retry-plan`(제안)은 요청 단계와 부모 snapshot으로 재사용/재실행 단계 및 예상 요청 목록을 산출하며 모델을 호출하지 않는다.
- [ ] 확인된 계획 hash로 실행을 시작한다. 원문/설정/부모 snapshot이 바뀌면 409와 새 계획 필요 안내를 반환한다.
- [ ] 재사용 결과는 signature/config/의존 산출물 hash가 모두 맞을 때만 채택한다. downstream 결과는 오래된 상태를 유지하지 않는다.
- [ ] 새 실행은 C2의 새 snapshot으로 만들고 예산은 C1을 통과한다. 부분 실패가 전체 완료 알림을 만들지 못하게 한다.
- [ ] 테스트: recipe 갱신의 downstream, 독립 단계 재사용, 이중 실행 409, 취소, 원문 변경, 요청 미발행, 기존 완료 결과 유지.

완료 기준: 실패한 단계 복구 때문에 무관한 유료 결과를 다시 생성하지 않고, 의존하는 결과는 빠짐없이 갱신하거나 stale로 표시한다.

## 9. D 단계: 독립적으로 출시할 화면 개선

| 작업 | 파일과 구현 범위 | 완료/검증 기준 |
| --- | --- | --- |
| PDF 목차/썸네일 (#14) | `PdfViewer.tsx`의 기존 document 객체에서 outline 조회. PDF 내부 destination만 기존 linkService로 처리. 썸네일은 보이는 페이지 주변만 렌더 | 목차 없음, 잘못된 destination, 수백 페이지, 확대 상태에서 페이지 번호가 맞는다. 외부 URL을 페이지 이동으로 처리하지 않는다. |
| 그림/표 고정 (#13) | `Workbench.tsx`, `FigureGallery.tsx`, `TableGallery.tsx`에 단일 논문 내 1개 자료 고정. ID만 상태로 저장하고 기존 데이터를 참조 | 자료 삭제/재생성 시 고정 해제. 1024px에서는 접이식, Esc와 원래 포커스 복귀. 다른 논문과의 비교 기능 없음 |
| 명령 검색 (#20) | 기존 Modal/입력 컴포넌트로 Workbench 명령 목록 구성. ⌘K/Ctrl+K, Esc, 키보드 선택 | 입력창 단축키 충돌 없음. 분석/유료 작업은 기존 확인 동선을 그대로 사용. 키보드로 원문 검색/자료 열기/내보내기에 도달 |
| 예제 안내 (#18) | Home/Settings에 3단계 안내. 재배포 가능한 라이선스의 PDF/저장 결과 또는 자체 fixture 사용 | 외부 API 호출 0회, 예제 표시가 실제 분석 실행과 구분됨, 설정 완료 이후에도 도움말에서 재접근 가능 |

## 10. E 단계와 보류 항목의 경계

### 연구 노트 (#4): 후속 독립 작업

기존 `papers.notes`는 논문 전체 메모로 유지하고, 영구 하이라이트는 `paper_annotations` 같은 별도 SQLite 테이블로 확장한다. 기존 필드를 하이라이트 배열로 바꾸지 않는다. 원문 signature, 페이지, 구절, 사용자 본문, 수정 시각, PDF 좌표를 저장한다. 현재 `PdfTextSelection.rect`는 DOMRect이므로 영구 좌표로 저장하지 않는다. 화면 좌표를 PDF 좌표로 변환하고 여러 페이지 선택은 페이지별 anchor로 분리한다. AI가 작성한 설명은 사용자 메모를 덮어쓰지 않는다.

작업/검증: 페이지별 anchor round-trip, 100%/150%/회전 시 위치, 저장 실패 표시, 재분석 후 보존, JSON/Markdown 내보내기. API는 논문별 GET/POST와 개별 PATCH로 제한하고 삭제는 기존 사용자 삭제 규칙을 따른다. 완료 기준은 앱 재실행 후 원문 위치와 메모가 함께 복원됨이다.

### 전체 본문 검색 (#8): 후속 독립 작업

`document_context.py`의 기존 로컬 텍스트에서 페이지별 색인을 만든다. SQLite FTS5 가용성을 Python 3.12 배포 런타임에서 확인하고 `paper_text_index(paper_id, pdf_signature, page, text)` 저장 구조를 설계한다. 검색어를 파라미터로 전달하고 FTS 문법을 검증한다. HTML snippet을 그대로 삽입하지 않는다. 페이지 매핑이 없는 문서는 `페이지 정보 없음`으로 표시한다. 원문 변경 시 해당 문서만 색인 갱신하고 삭제 시 검색 결과에서도 제거한다. 검색 실패가 무결과가 되지 않게 한다.

완료 기준: 논문 제목에 없는 본문 표현을 검색해 정확한 문서와 페이지로 이동한다. OCR이 없는 스캔 PDF는 검색 불가 이유를 표시한다. 임베딩, 벡터 DB, 복수 논문 합성 답변은 추가하지 않는다.

### 내 실험 계획 기록 (#17): 후속 독립 작업

`RecipeCard.tsx`, `ExperimentPlanTab.tsx`, `experiment_plans`를 재사용한다. 먼저 기존 컴포넌트의 실제 진입 경로를 확인한다. 원문 값/단위와 내 설정/단위, 변경 이유, 실행 결과를 별도 필드에 보관한다. 논문 조건을 수정하는 형태로 저장하지 않는다. 계획/실행함/결과 첨부/원문과 대조 상태를 구분한다. 숫자와 문자열 모두 허용하되 숫자형 값은 finite 검사하고 유효 범위는 출처가 있을 때만 적용한다.

완료 기준: 원문 recipe는 그대로 보존되고 사용자 계획이 앱 재실행 후 유지되며 CSV로 내보내진다. 실제 장비 제어, 자동 코드 실행, 재현 성공 판정은 포함하지 않는다.

### 다중 PDF 가져오기 (#19): 후속 독립 작업

`UploadPanel.tsx`, `api/papers.py`의 단일 업로드 검증을 재사용하고 먼저 순차 업로드 목록만 추가한다. 파일 hash가 같으면 기존 논문 열기 선택지를 제공하고, DOI만 같은 경우는 판본 차이 가능성이 있으므로 중복 후보로만 표시한다. 파일별 대기/저장/실패 상태를 제공하고 자동 분석은 시작하지 않는다. 업로드 과정의 naming/extraction이 외부 API를 쓰는지 구현 전에 감사해 무료 작업으로 단정하지 않는다.

완료 기준: 일부 파일이 실패해도 성공 파일이 보존되고 실패 파일만 다시 처리된다. 파일 hash 중복은 서버에서도 검사한다. 기존 파일 삭제/자동 교체와 자동 유료 재시도는 없다.

### 보류표

| 항목 | 현재 결정 | 다시 논의할 조건 |
| --- | --- | --- |
| #6 논문 비교 | 명시적으로 제외 | 사용자가 비교 개발을 다시 요청할 때 |
| #16 복수 논문 질의 | 이번에 제외 | 단일 논문 근거 검증이 안정화되고 별도 요청이 있을 때 |
| #7 프로젝트 컬렉션 | 현재 Library 구조 유지, 후보로 보류 | 실제 분류 불편과 필요 흐름 확인 후 |
| #15 Zotero/BibTeX/RIS | DEC-004에 따라 보류 | 외부 연동 범위를 별도 결정할 때 |

## 11. 검증과 측정

### Review Focus

1. A에서 B로 논문을 바꾸는 중 저장/조회가 늦게 끝날 때 서로의 상태를 덮어쓰지 않는가? A2의 격리 테스트와 GUI 경로 전환으로 검증한다.
2. 페이지 수/원문이 바뀌었을 때 잘못된 위치를 기존 근거처럼 보이지 않는가? A2 signature 및 B1 stale 테스트가 담당한다.
3. 저장 실패와 공급사 usage 누락이 성공/0원으로 표시되지 않는가? A2 오류 표시와 B2/C1 미확정 테스트가 담당한다.
4. 부분 결과, 과거 버전, 재실행 실패가 완료 배지로 승격되지 않는가? C2/C3의 실패 snapshot과 GUI 알림 테스트가 담당한다.
5. 1024px, 200% 확대, 키보드만 사용하는 경우 핵심 제어가 가려지거나 포커스가 유실되지 않는가? A3/D 단계 DOM 및 실제 창 검사가 담당한다.

### 실행할 검증 명령

구현한 작업의 관련 테스트부터 실행하고 성공 후 전체 회귀를 수행한다. 문서 작성만 하는 현재 작업에서 아래 명령을 실행했다고 주장하지 않는다.

```bash
# cwd: sasoo/frontend
pnpm exec vitest run src/components/AnalysisPanel.reading.dom.test.tsx src/lib/workbenchSummaries.test.ts src/lib/pdfHighlight.test.ts src/lib/evidence.test.ts
pnpm tsc --noEmit
pnpm lint
pnpm build

# cwd: sasoo/backend
./.venv/bin/python -m py_compile main.py
./.venv/bin/python -m pytest services api models

# cwd: repository root
git diff --check
```

신규 테스트는 해당 작업에서 생성한 실제 파일 경로를 위 관련 테스트 명령에 추가한다. 시험 이름만 문서에 있는 상태는 구현 완료가 아니다.

GUI 검증은 같은 원문/저장 결과로 밝은/어두운 테마, 1440×900/1024×680, 200% 확대에서 실행한다. loading/error/empty/partial/completed, 긴 제목, 키보드, 콘솔 오류를 함께 확인한다. 웹 fixture 성공과 실제 Electron 앱 성공을 분리해 보고한다.

### 성공 기준

- A: 재실행 후 저장된 페이지/배율/탭/분할 복원, 다른 논문으로의 상태 누출 0건.
- B: 미확인 근거/비용을 검증 완료/0원으로 표시하는 사례 0건.
- C: 한도를 넘긴 새 요청 발행 0건, 이전 완료 결과와 파일 소실 0건, 동일 요청 중복 정산 0건.
- 체감 효과: 고정된 시나리오에서 읽기 재개 시간, 근거 도달 시간과 조작 수를 기록한다. 기준선 측정 전 개선률을 약속하지 않는다.
- 과학 품질: 검증기가 통과한 것과 주장이 원문 의미에 맞는 것은 별도다. 원문 수치/단위/조건을 사람이 독립 대조한 표본 결과를 기록한다.

## 12. 비용, 롤백, 전달

오프라인 개발은 저장된 결과와 가짜 공급사로 수행한다. 새 유료 평가가 필요하면 논문/원문 hash, 설정/프롬프트 hash, 요청 최대 수, 예산 예약, 완료 기준, 중단 조건을 먼저 고정한다. 이미 발행한 유료 요청은 비교를 위해 재실행하지 않는다. 미확정 과금, 잘린 응답, 입력 불일치가 발생하면 새 발행을 중단한다.

마이그레이션은 additive/idempotent로 작성하고 테스트 DB에서 두 번 실행한다. UI 되돌림은 신규 컬럼/테이블 삭제 없이 가능해야 한다. 라이브 사용자 DB는 일관된 backup 절차를 확인한 뒤에만 마이그레이션한다. 파일 정리와 과거 snapshot 삭제 정책은 이번 범위가 아니다.

각 독립 작업은 관련 테스트 결과와 GUI 근거를 묶어 검토 가능한 변경으로 전달한다. 커밋/릴리스/배포는 실제 요청 범위에서 수행하며 사용자 변경을 broad staging하지 않는다. 개발 빌드 성공을 패키지 성공으로 보고하지 않는다. 실제 출시 시 프로젝트의 macOS release/ZIP 검증 절차를 별도로 수행한다.

학습 포인트: 읽기 상태는 편의 기능이고 실행 checkpoint는 계산의 정합성이다. 둘을 같은 상태로 취급하면 화면을 복원하면서 유료 작업까지 재시작할 수 있다. 데이터 식별자와 수명, 실패 시 의미를 먼저 고정하고 그 위에 UI를 연결한다.
