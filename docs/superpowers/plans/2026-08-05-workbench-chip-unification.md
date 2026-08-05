# 워크벤치 칩 통일 + 헤더 다이어트 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 워크벤치 화면의 칩을 단일 틴트 스타일로 통일하고 헤더를 다이어트한다.

**Architecture:** 스펙 `docs/superpowers/specs/2026-08-05-workbench-chip-unification-design.md`. 전편 브랜치 `ui/workbench-right-panel`에 이어서 커밋(PR #43 갱신). 기능·API 무수정, 렌더·클래스만 변경.

**Tech Stack:** React+Tailwind(+index.css 유틸), vitest. 작업 디렉터리 `sasoo/frontend`.

## Global Constraints

- 전편 플랜(2026-08-04-workbench-right-panel.md)의 Global Constraints 전부 상속: 굵기 400/500/650, radius 6/12/pill, `--accent`/`--success`/`--warning`, transition 속성 명시, 해요체·em-dash·화살표 금지, `.dark` 변수 방식, 컴포넌트 테스트 프레임워크 신설 금지, 커밋 트레일러.
- 칩 스타일은 딱 하나: 틴트 배경(시맨틱 색 8~12% — 예: `bg-accent/10`), pill, 12px·500, 보더 없음, 텍스트는 시맨틱 색 진한 톤. 다크 모드에서도 틴트 방식 유지(투명도 조정 허용).
- 워크벤치 표면만: `WorkbenchHeader.tsx`, `AnalysisPanel.tsx`, `FigureGallery.tsx`/`TableGallery.tsx`의 헤더부, 질문 도우미 칩. 다른 화면의 `status-pill`/`Badge` 사용처는 무수정.
- raw enum 값 텍스트 변경 금지(범위 밖 — 칩 모양만 바꾼다).

---

### Task 1: 공용 틴트 칩 유틸 + 워크벤치 표면 이관

**Files:**
- Modify: `sasoo/frontend/src/index.css` (칩 유틸 추가 — 기존 `status-pill` 정의 위치 근처)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx` (phase-meta-pill·collapsedMeta·질문 도우미 관련 칩 — grep으로 정위치)
- Modify: `sasoo/frontend/src/components/ChatPanel.tsx` (질문 도우미 "준비됨" 칩이 여기 있으면)

**Interfaces:**
- Produces: `.chip-tint`(기본 accent)·`.chip-tint-success`·`.chip-tint-warning` CSS 유틸(이름은 코드베이스 관례에 맞게 조정 가능하되 리포트에 기록). Task 2·3이 같은 클래스를 사용.

- [ ] **Step 1: 유틸 정의** — index.css에 틴트 칩 유틸 3종 추가: `border-radius: 9999px; padding: 2px 10px; font-size: 12px; font-weight: 500; background: rgb(var(--accent) / 0.10); color: rgb(var(--accent));` 및 success/warning 변형(같은 패턴). `.dark`에서 배경 투명도만 0.16 정도로 조정.
- [ ] **Step 2: 워크벤치 내 잔존 칩 이관** — AnalysisPanel의 `phase-meta-pill`(citation/deep_dive 정보성 필: "주요 인용 N건" 등)과 collapsedMeta pill, 질문 도우미 "준비됨" 칩을 grep으로 찾아 새 유틸로 교체(텍스트 무수정). `buildMetaPillStyle` 인라인 색 계산이 더는 필요 없으면 삭제.
- [ ] **Step 3: 검증·커밋** — `tsc --noEmit`+`pnpm vite build`+`pnpm vitest run` 통과, `git commit -m "ui(workbench): 틴트 칩 유틸 도입 및 우측 패널 칩 이관"`

---

### Task 2: 헤더 다이어트

**Files:**
- Modify: `sasoo/frontend/src/components/workbench/WorkbenchHeader.tsx` (칩 렌더부 — 상태 칩 295-300 부근, 도메인·에이전트 칩은 grep)

**Interfaces:**
- Consumes: Task 1의 칩 유틸, 전편의 `DOMAIN_LABELS`(`workbenchSummaries.ts` export 여부 확인 — 미export면 export 추가), 상태 요약(`trustStateLabel || runStateLabel` 우선순위 — `buildWorkbenchStatusSummary` 재사용)

- [ ] **Step 1: 상태 칩 2→1 축약** — `분석 완료`/`심층 분석 완료` 칩 두 개를 `trustStateLabel || runStateLabel` 하나로 줄이고 Task 1 틴트 칩(완료=success 톤, 진행=accent 톤) 적용.
- [ ] **Step 2: 도메인 칩 한국어화** — `ai_ml` raw 값 → `DOMAIN_LABELS` 매핑 적용(미매핑 값은 원문 폴백), 틴트 칩(accent).
- [ ] **Step 3: 에이전트 선택 스타일** — 칩 모양 제거 → 텍스트+셰브론, `hover:bg-surface-hover` 배경, 선택 로직·드롭다운 무수정.
- [ ] **Step 4: 검증·커밋** — 동일 3종 검증 후 `git commit -m "ui(workbench): 헤더 칩 다이어트 — 상태 1개 축약·도메인 한국어·에이전트 셀렉트화"`

---

### Task 3: 정보성 숫자·완료 표시 칩 해제

**Files:**
- Modify: `sasoo/frontend/src/components/FigureGallery.tsx`·`TableGallery.tsx` (갤러리 헤더 "추출한 그림 N" 뱃지 — grep)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx` (Phase 섹션 "✓ 완료" 배경 뱃지 — grep)

- [ ] **Step 1: 갤러리 카운트 뱃지 해제** — "추출한 그림 `14`" 숫자 뱃지 → 제목 옆 muted 텍스트(12px 400, tabular-nums). Table 갤러리도 동일.
- [ ] **Step 2: Phase 완료 뱃지 해제** — "✓ 완료" 배경 뱃지 → 배경 없는 체크 아이콘(`text-success`, 기존 AppIcon) + muted 텍스트 "완료". 진행 중 뱃지가 있으면 같은 문법(accent 색점+텍스트).
- [ ] **Step 3: 검증·커밋** — 동일 3종 검증 후 `git commit -m "ui(workbench): 정보성 숫자·완료 표시를 칩에서 텍스트로 강등"`

---

### Task 4: 실행 검증

- [ ] **Step 1**: 금지 패턴 grep(변경 파일들의 사용자 노출 문자열에 em-dash·화살표 0건, 새 칩 유틸 외 잔존 status-pill이 워크벤치 표면에 없는지).
- [ ] **Step 2**: `pnpm vitest run`+`pnpm vite build` 통과.
- [ ] **Step 3**: 실행 스크린샷 — 헤더 포함 전폭, 요약 탭, 라이트·다크 각 1장(전편 task-7-report.md의 기동 방법 재사용, 서버 종료 확인). 저장: `.superpowers/sdd/2026-08-05-workbench-chip-unification/screenshots/`
- [ ] **Step 4**: 결과를 이 플랜 하단에 추기 후 커밋.

## 실측 결과 (Task 4에서 기록)

**검증일**: 2026-08-05, 브랜치 `ui/workbench-right-panel`, 대상 커밋 범위 `f9e8306..cff091d`(Task 1~3).

### Step 1: 금지 패턴 grep

- em-dash·화살표: 변경 파일(`AnalysisPanel.tsx`·`ChatPanel.tsx`·`FigureGallery.tsx`·`WorkbenchHeader.tsx`·`workbenchSummaries.ts`) 전체에서 매치된 8건 전부 코드 주석. 사용자 노출 문자열 내 0건.
- `status-pill` 잔존: 워크벤치 4대 표면(WorkbenchHeader·AnalysisPanel·Figure/TableGallery·ChatPanel) 중 AnalysisPanel·ChatPanel은 0건. WorkbenchHeader는 허용된 1건(정적 에이전트 배지, 비드롭다운 폴백 경로)만 잔존. FigureGallery(3건: 서브피겨 배지·classifier_model·resolver_version, 전부 `import.meta.env.DEV` 게이트)·TableGallery(5건: resolver_version·classifier_model·review_required·repair_attempted·repair_confidence)는 카드 본문 메타 필로, 플랜 Global Constraints("워크벤치 표면만... FigureGallery/TableGallery의 **헤더부**"만 대상, index.css 주석도 "이 표면 밖의 status-pill/Badge는 무수정" 명시)와 Task 1~3 브리프 범위(갤러리 카운트 뱃지·Phase 완료 뱃지만 대상) 밖이라 위반 아님으로 판정. 코드 수정 없음.

### Step 2: 빌드·테스트

- `pnpm vitest run`: 8 files / 54 tests 전부 통과.
- `pnpm vite build`: 7.80s 정상 완료, 신규 에러·경고 없음.

### Step 3: 실행 스크린샷

- 백엔드(8000)·프론트 preview(4173) 모두 검증 시작 전부터 기동 중이던 기존 프로세스 재사용(PID 9788/10204, 세션 종료 후에도 그대로 둠). `pnpm vite build` 재빌드 후 `curl`로 preview 응답과 `dist/index.html`을 diff해 이미 최신 빌드를 서빙 중임을 확인(재시작 불필요, sirv가 디스크에서 매 요청 직접 읽음).
- Playwright(Chromium) `/tmp/pw-scratch`(전편 임시 설치 재사용), 대상 `http://127.0.0.1:4173/#/workbench/999005`(paper_id=999005), `localStorage['sasoo-theme']` 주입으로 라이트/다크 강제, 뷰포트 1600×1100 전폭(헤더 포함).
- **디버깅 메모**: 최초 캡처에서 다크 스크린샷의 헤더 바만 흰색으로 찍히는 현상 발견 — `getComputedStyle` 확인 결과 실제 배경은 `rgba(23,23,26,0.95)`(정상 다크)였고 `backdrop-blur` 제거로도 재현되어, headless Chromium이 `BrowserContext`에 `colorScheme`을 명시하지 않으면 `backdrop-filter`가 걸린 반투명 배경을 스크린샷 컴포지팅 시 잘못 칠하는 렌더링 아티팩트로 판명(실제 DOM/CSS는 항상 정상). `newContext({ colorScheme: 'light'|'dark' })`를 추가해 해결 — 실제 앱 버그 아님, Playwright 스크린샷 캡처 환경 이슈.
- 저장 파일: `screenshots/workbench-light-summary.png`, `screenshots/workbench-dark-summary.png`(둘 다 요약 탭, 헤더 포함 전폭). 픽셀 샘플링(`PIL.Image.getpixel`)으로 라이트 배경 `(247,247,248)`, 다크 배경 `(10,10,11)`/헤더 `(23,23,26)` 확인 — 헤더·칩(`도메인`·`상태`·에이전트)·PhaseSection 완료 아이콘 모두 라이트/다크 각각 올바른 색으로 렌더링.

### 결론

Task 1~3 변경분에 금지 패턴 위반 없음, 빌드·테스트 그린, 실행 화면 라이트·다크 모두 정상. 코드 수정 없이 검증만 수행(위반 0건이라 정리 대상 없었음).
