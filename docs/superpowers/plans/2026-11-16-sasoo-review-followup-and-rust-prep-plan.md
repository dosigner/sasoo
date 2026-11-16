# Sasoo Review 후속 작업과 Rust 전환 준비 계획

작성일: 2026-11-16. 기준 커밋: main `9d1953d` (PR #137, Review 논문 모드 병합).

## 1. 결론

남은 작업은 네 단계이고, 아래 표는 실행 순서대로 번호를 매겼습니다. Review 화면 정리를 Rust fixture 커밋보다 앞에 둡니다.

Rust fixture(`contract-fixtures/rust-backend-v2/`)에는 원본 파일의 sha256이 들어 있습니다. 대상은 `api.ts`, `analysis_routes.py`, 테스트 파일 등입니다. 1단계와 2단계는 이 원본 파일을 고칩니다. 그래서 두 단계를 먼저 끝내고 3단계에서 fixture를 한 번만 다시 캡처합니다.

프론트엔드 스타일링은 Tailwind CSS v4를 유지합니다(2026-11-15 결정, 근거는 6절). Rust 백엔드 전환은 HTTP와 SSE 계약만 바꿉니다. 그래서 스타일링 결정과 관계없습니다.

| 순서 | 단계 | 유료 API | 선행 조건 |
| --- | --- | --- | --- |
| 1 | 미커밋 7개 파일 커밋 (Rust 계획 사전 작업) | 없음 | 다른 세션의 작업 종료 |
| 2 | Review 화면 정리 2건 | 없음 | 없음 |
| 3 | Rust 포트와 fixture v2 커밋 | 없음 | 1단계와 2단계 병합 |
| 4 | Letter 논문 실제 확인 | 1편당 약 $0.17-0.20 | 사용자가 Letter PDF 제공 |

2절부터 5절까지가 1단계부터 4단계입니다.

## 2. 1단계: 미커밋 7개 파일 커밋

### 현재 상태

이 세션이 고친 파일이 아닙니다. 수정 시각은 2026-11-14 15:00-15:03, 2026-11-15 14:09입니다. 파일 수가 5개에서 7개로 늘었으므로 다른 세션이 아직 작업 중일 수 있습니다.

| 묶음 | 파일 | 내용 | Rust 계획의 근거 |
| --- | --- | --- | --- |
| A. 사용량 미확인 | `backend/services/llm/gemini_client.py`, `test_gemini_client.py`, `frontend/src/lib/api.ts` | 사용량이 없으면 0 대신 `None`을 보내고, 프론트는 0으로 기록하지 않고 오류를 냅니다. pipeline 세마포어는 실제 작업 스레드가 끝날 때 반납합니다 | 2026-11-14 Rust 계획 68행: usage 부재는 unknown으로 두고 완료로 승격하지 않음 |
| B. PDF 하이라이트 | `frontend/src/lib/pdfHighlight.ts`, `pdfHighlight.test.ts` | `convertToViewportRectangle`을 네 모서리 `convertToViewportPoint`로 바꿉니다 | 같은 계획 41행: P01 호환 과제 |
| C. 그림 설명 빈 결과 | `backend/api/figure_service.py`, `test_figure_stream.py` | JSON 추출 뒤 설명이 비면 502와 `_usage`를 돌려줍니다 | 같은 계획 68행과 같은 원칙(추정) |

### 절차

1. 다른 세션(Codex로 추정)이 작업을 마쳤는지 사용자가 확인합니다. 작업 중이면 그 세션이 커밋합니다.
2. 백엔드 전체 테스트를 실행합니다: `./.venv/bin/python -m pytest services api models`.
3. 루트 vitest, frontend vitest, `pnpm tsc --noEmit`, `pnpm lint`, `pnpm build`를 실행합니다.
4. OpenAI 클라이언트가 사용량 부재 때 `None`을 보내는지 확인합니다. 0을 보내면 새 `api.ts` 검사를 통과하므로 비용 $0 기록이 남습니다. 이때는 OpenAI 클라이언트도 묶음 A에 넣어 고칩니다.
5. PR A를 올립니다: 묶음 A와 C. 백엔드와 프론트가 같은 계약을 쓰므로 나누지 않습니다.
6. PR B를 올립니다: 묶음 B. 앱을 띄워 회전 페이지와 CropBox가 있는 PDF에서 하이라이트 위치를 스크린샷으로 확인합니다.

### 완료 조건

두 PR이 병합되고 작업 트리의 추적 파일 변경이 0개입니다.

## 3. 2단계: Review 화면 정리 2건

### 문제

1. Review 논문의 recipe 생략 문구가 "Recipe 단계는 스크리닝 신호가 약해 자동 실행을 건너뛰었습니다"입니다. 논문 51번 실측에서 확인했습니다. Review라서 생략한 것인데 문구는 신호가 약하다고 말합니다.
2. 이번 기능 전에 분석한 Review 논문은 예전 synthesis 행이 DB에 남아 있습니다. 재분석 뒤에도 `/results`가 그 행을 돌려줘서 "종합" 탭이 보입니다.

### 절차

1. `backend/services/analysis_execution.py`의 skip 메시지 분기에서, recipe이고 `_paper_type(payload) == "review"`이면 "Review 논문이라 재현 레시피를 만들지 않았습니다."를 씁니다. 프롬프트와 스키마는 바꾸지 않습니다. 그래서 캐시 키와 과금에 영향이 없습니다.
2. `frontend/src/components/AnalysisPanel.tsx`에서 `isReview`이면 종합 탭을 숨깁니다. DB의 예전 행은 지우지 않습니다.
3. 테스트를 추가합니다.
   - 백엔드: Review의 recipe skip 메시지
   - DOM(`AnalysisPanel.review.dom.test.tsx`): Review에서 종합 탭이 없음
4. 앱에서 논문 51번을 열어 화면을 캡처합니다. 재분석은 하지 않습니다.

### 완료 조건

PR이 병합되고 스크린샷에서 종합 탭이 없고 문구가 바뀐 것을 확인합니다.

## 4. 3단계: Rust 포트와 fixture v2 커밋

### 현재 상태

Python 계약은 main에 있습니다. 바뀐 것은 screening 스키마 해시, `REVIEW_MAP` 스키마, `/results`의 `review_map` 필드입니다. 이 값은 미추적 디렉터리 `contract-fixtures/rust-backend-v2/`에만 반영되어 있습니다. `backend-rust/`의 fixture 경로 11곳과 `test_rust_sse_chat_capture.py`는 v2를 가리킵니다. CI의 백엔드 skipped 7건은 이 파일들이 저장소에 없어서 생깁니다.

### 절차

1. 1단계와 2단계가 병합된 main에서 fixture를 다시 캡처합니다.
   - `scripts/export-rust-contracts.py --output-root contract-fixtures/rust-backend-v2`
   - `scripts/rust-contract-harness.py --mode capture --fixture-root <v2> --app-data-root <v2>/appdata --deny-network`
   - `scripts/rust-sse-contract-capture.py --fixture-root <v2> --deny-network`
   - `backend-rust/resources/openapi-wire.json`을 v2 `http.json`의 openapi 본문으로 바꿉니다.
2. 다음을 확인합니다.
   - `export-rust-contracts.py --verify` 통과, source hash 차이 0
   - `cargo test --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml` 통과 (2026-11-14 기준 87건)
   - 백엔드 테스트의 skipped 7건이 통과로 바뀜
3. `backend-rust/target/`이 `.gitignore`에 있는지 확인합니다.
4. 커밋 범위:
   - `sasoo/backend-rust/`
   - `sasoo/contract-fixtures/rust-backend-v2/`
   - `sasoo/scripts/export-rust-contracts.py`, `rust-contract-harness.py`, `rust-sse-contract-capture.py`, `verify-rust-pdf-resources.js`
   - `sasoo/backend/api/test_rust_contract_capture.py`, `test_rust_sse_chat_capture.py`, `sasoo/backend/services/test_rust_fixture_export.py`
   - Rust 계획 문서 2개 (`2026-11-13`, `2026-11-14`)
5. 2026-11-14 Rust 계획의 F 묶음에 `review_map` 단계를 덧붙입니다. 그 계획은 Review 분기 전에 작성되었습니다. 덧붙일 계약은 다음과 같습니다.
   - deep_dive skip 이유 `review_paper`
   - `STAGE_OUTPUTS` 인덱스 7
   - Review면 synthesis와 시각화 생략
   - `paper_type` 비필수와 `methodology_type` 대체 규칙

### 사용자 결정

1. v1 fixture(`contract-fixtures/rust-backend/`)를 커밋할지 정합니다. v2만 쓰면 넣지 않아도 됩니다.
2. CI(`.github/workflows/build-check.yml`)에 `cargo test`를 추가할지 정합니다. 지금 CI는 Rust를 빌드하지 않습니다.

### 완료 조건

PR이 병합되고, 깨끗한 worktree에서 Rust 계약 테스트가 skip 없이 통과합니다.

## 5. 4단계: Letter 논문 실제 확인

### 문제

라이브러리에 Letter로 판별된 논문이 없어서 Letter 경로를 실측하지 않았습니다. Article이 Review로 잘못 판별되는 비율도 측정하지 않았습니다. Review로 잘못 판별되면 deep_dive가 빠지므로 사용자에게 보이는 차이가 큽니다.

### 절차

1. 사용자가 Letter PDF 1-2편을 줍니다(Optics Letters, Nature Photonics Letter 등).
2. 사용자 라이브러리가 아니라 라이브러리 복사본(`SASOO_APP_DATA_ROOT`)에서 분석합니다.
3. 다음을 기록합니다.
   - `paper_type`이 `letter`인지
   - 요약 탭의 "유형 Letter" 표시
   - deep_dive 실행 여부
   - 단계별 비용
4. 선택: 오판정률을 재려면 기존 논문 10편에 screening만 다시 실행합니다. screening만 돌리는 스크립트가 필요합니다. 비용은 아직 측정하지 않았습니다.

### 완료 조건

Letter 1편 이상이 `letter`로 판별되고 Article 경로로 끝납니다.

## 6. 스타일링 결정: Tailwind CSS v4 유지

2026-11-15에 결정했습니다.

### 현재 사용 규모

- `tailwindcss` 4.3.5와 React 19.3.1을 씁니다(둘 다 2026-11 기준 최신).
- 컴포넌트 64개 중 60개가 `className`을 쓰고, 사용 횟수는 1,616번입니다.
- `index.css`는 2,257줄이고 `@theme`와 `@apply`가 178곳 있습니다.

### State of CSS 2025

| 질문 | 응답자 | 결과 |
| --- | --- | --- |
| CSS 프레임워크 | 3,977명 | Tailwind 2,041, Bootstrap 1,194, 안 씀 1,061, shadcn/ui 766 |
| CSS-in-JS | 3,718명 | 안 씀 2,110, CSS Modules 1,037, styled-components 870, Emotion 382, vanilla-extract 98, Panda 62, StyleX 48 |

전체 응답자 중 CSS-in-JS 라이브러리를 쓰는 비율은 29%입니다. 응답자는 스스로 참여하므로 표본이 치우칩니다.

### npm 주간 다운로드 (2026-11 첫 주, 괄호 안은 1년 전 대비)

| 패키지 | 주간 다운로드 | 1년 전 대비 |
| --- | --- | --- |
| tailwindcss | 1억 7,900만 | 6.6배 |
| class-variance-authority | 8,295만 | 9.1배 |
| styled-components | 1,410만 | 2.0배 |
| @emotion/react | 2,763만 | 2.3배 |
| @stylexjs/stylex | 224만 | 10.5배 |

CI와 자동 생성 프로젝트가 섞여 있으므로 추세로만 읽습니다.

### 판단 근거

1. Sasoo는 이미 가장 많이 쓰이는 방식을 최신 버전으로 씁니다. 다른 방식으로 바꾸면 60개 파일을 다시 쓰고 디자인 계약도 다시 확인해야 합니다.
2. styled-components v7의 장점은 Server Components 지원입니다. v7은 2026-11-10 기준 prerelease입니다. Sasoo는 Electron 안의 Vite SPA라서 Server Components를 쓰지 않습니다.
3. 빌드 시점 CSS-in-JS(StyleX, Panda, vanilla-extract)는 빠르게 늘지만 사용자가 적고 전용 컴파일러에 의존합니다.

후속 선택지가 하나 있습니다. 변형이 많은 컴포넌트(버튼, 칩)에만 `class-variance-authority`를 들이는 방법입니다. 필요한 곳이 있는지는 아직 확인하지 않았습니다.

## 7. 미검증 항목과 위험

- 첫 진입에서 리뷰 지도 탭이 자동으로 열리지 않은 원인은 경합으로 추정했습니다. 재현은 하지 않았습니다.
- 기존 논문을 재분석하면 screening 캐시 키가 바뀌어 deep_dive, synthesis, 시각화도 다시 과금됩니다. 실측으로 Article 1편당 약 $0.17-0.20입니다.
- 리뷰 지도 품질은 OpenAI `gpt-6-luna`로만 확인했습니다. Gemini에서는 확인하지 않았습니다.
- Windows 실행은 확인하지 않았습니다.
- 하지 않기로 한 범위: review_map 단독 재생성 버튼, 채팅 문맥과 보고서 내보내기 반영, 유형 수동 변경.
