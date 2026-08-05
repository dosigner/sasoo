# 워크벤치 우측 패널 Quiet Minimal 재정비 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 워크벤치 우측 패널(상태부·탭·요약 메타·그림/표 카드)을 기존 토큰만으로 Quiet Minimal 스타일로 재정비한다.

**Architecture:** 스펙 `docs/superpowers/specs/2026-08-04-workbench-right-panel-design.md`와 목업 `.superpowers/brainstorm/20735-1785848734/content/final-design-v2.html`이 기준. 기능·API·데이터 계약 무수정, 렌더 계층(JSX+클래스)만 변경. 상태 요약 로직은 `workbenchSummaries.ts`(순수 함수, 유닛테스트 가능)에 두고 컴포넌트는 표현만 담당.

**Tech Stack:** React + Tailwind(+ index.css 커스텀 유틸), vitest(순수 로직만, 컴포넌트 테스트 인프라 없음 — 신규 도입 금지), pnpm. 작업 디렉터리 `sasoo/frontend`.

## Global Constraints

- 토큰 외 신규 값 금지: radius 6/12/pill, 굵기 400/500/650, 액센트 `--accent` 1색 + `--success`/`--warning` 색점.
- 내부 용어(`resolver-v1`, `classifier_model` 값, `heuristic`, `Composite`)는 `import.meta.env.DEV`에서만 렌더(프로덕션 빌드 완전 제거).
- UI 문구: 해요체, em-dash(—)·화살표 문자(→) 금지, 가운뎃점 라인당 1개 이하.
- `transition: all` 금지(속성 명시), 신규 keyframe 금지, `prefers-reduced-motion` 존중.
- 다크모드는 `.dark` 클래스 + 기존 CSS 변수 방식 그대로(신규 방식 도입 금지).
- 컴포넌트 테스트 프레임워크(@testing-library 등) 추가 금지 — 검증은 typecheck+build+기존 vitest+실행 스크린샷.
- WorkbenchHeader·PdfViewer·ChatPanel·홈은 범위 밖(헤더의 중복 상태칩도 이번엔 무수정).
- 각 태스크 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 트레일러.

---

### Task 1: 상태부 — 칩 나열 → 상태 라인 + 진행 레일

**Files:**
- Modify: `sasoo/frontend/src/lib/workbenchSummaries.ts` (`buildWorkbenchStatusSummary` 부근)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx:1096-1119` (상태바 렌더)
- Test: `sasoo/frontend/src/lib/workbenchSummaries.test.ts` (신규, 순수 함수만)

**Interfaces:**
- Produces: `buildWorkbenchStatusSummary()` 반환에 `stagePathLabel: string` 추가 — 예: `"스크리닝 → 인용 → 시각 → 레시피 → 심층 · 5/5"` 형식이 아니라 **화살표 문자 금지 제약에 따라** `"스크리닝·인용·시각·레시피·심층"`은 가운뎃점 초과이므로, 단계 배열 `stageNames: string[]`과 `progressRatio: number`(0~1)를 반환하고 표현은 컴포넌트가 결정한다. 기존 필드는 전부 유지(유지+추가).

- [ ] **Step 1: 실패 테스트 작성** — `workbenchSummaries.test.ts`에 `buildWorkbenchStatusSummary` 입력(완료 5/5, 진행 3/5, 대기 0/5) 3케이스에 대해 `stageNames.length === 5`, `progressRatio` 값(1, 0.6, 0)을 assert. 기존 반환 필드(`runStateLabel` 등) 불변도 함께 assert.
- [ ] **Step 2: 실행해 실패 확인** — `cd sasoo/frontend && pnpm vitest run src/lib/workbenchSummaries.test.ts` → FAIL(필드 없음).
- [ ] **Step 3: 구현** — `workbenchSummaries.ts`에 `stageNames`(ProgressTracker의 PHASE_META 라벨을 실제 단계명으로 재사용: 스크리닝/인용 분석/시각 자료/레시피/심층 분석 — 정확한 명칭은 PHASE_META 29-59행에서 가져와 동일하게), `progressRatio` 추가.
- [ ] **Step 4: 테스트 통과 확인** — 같은 명령 PASS.
- [ ] **Step 5: 렌더 교체** — `AnalysisPanel.tsx:1096-1119`의 `status-pill` 칩 나열을 다음 구조로 교체(목업 v2 기준):

```tsx
<div className="flex items-baseline justify-between">
  <span className="text-sm font-[650] text-fg">{workbenchStatus.runStateLabel}</span>
  <span className="text-[11px] text-fg-muted tabular-nums">
    {workbenchStatus.stageNames.join(' · ').length > 0 && `${workbenchStatus.completedCount}/${workbenchStatus.totalCount}`}
  </span>
</div>
<div className="mt-2 h-[3px] rounded-full bg-border">
  <div
    className="h-[3px] rounded-full bg-accent transition-[width] duration-150"
    style={{ width: `${Math.round(workbenchStatus.progressRatio * 100)}%` }}
  />
</div>
```

주의: 가운뎃점 규칙(라인당 1개 이하) 때문에 단계 경로 문자열은 넣지 않는다 — 단계명은 진행 중일 때 `currentPhaseLabel` 하나만 상태 라인 옆에 표시("시각 자료 검토 중" 형태, 해요체 규칙은 명사구 예외).
- [ ] **Step 6: 빌드·기존 테스트** — `pnpm tsc --noEmit 2>/dev/null || pnpm vite build; pnpm vitest run` 모두 통과.
- [ ] **Step 7: Commit** — `git add -A sasoo/frontend/src && git commit -m "ui(workbench): 상태부 칩 나열을 상태 라인+진행 레일로 교체"`

---

### Task 2: Phase 스테퍼 박스 제거

**Files:**
- Modify: `sasoo/frontend/src/components/ProgressTracker.tsx:161-205` (박스+커넥터 렌더), `29-59` (PHASE_META 라벨 확인만)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx:1147-1153` (호출부)

**Interfaces:**
- Consumes: Task 1의 진행 레일(전체 진행률은 상태부가 담당)
- Produces: `ProgressTracker`는 "진행 중일 때만" 렌더되는 단계 리스트로 축소 — props 시그니처 불변(호출부 변경 최소화)

- [ ] **Step 1: 렌더 교체** — 161-205행의 박스 + `h-0.5` 커넥터 div를 제거하고, 세로 리스트로 교체: 각 단계 = 한 줄(완료: `--success` 체크 아이콘 + muted 400 텍스트 / 진행 중: `--accent` 색점 + fg 650 텍스트 / 대기: `--border` 색점 + muted 400). 아이콘은 기존 아이콘 컴포넌트(`@/components/icons/AppIcon`) 재사용, 신규 SVG 금지.
- [ ] **Step 2: 완료 상태에선 스테퍼 숨김** — `AnalysisPanel.tsx:1147-1153` 호출부에서 전체 완료(`completedCount === totalCount`) 시 `ProgressTracker`를 렌더하지 않는다(상태부 한 줄로 충분).
- [ ] **Step 3: 빌드 확인** — `pnpm vite build` 성공, `pnpm vitest run` 통과.
- [ ] **Step 4: Commit** — `git commit -m "ui(workbench): Phase 박스 스테퍼를 슬림 단계 리스트로 교체, 완료 시 숨김"`

---

### Task 3: 탭 한국어 통일 + 스타일

**Files:**
- Modify: `sasoo/frontend/src/lib/strings.ts` (`S.workbench.*Tab` 라벨 — 정확한 라인은 grep으로 확인)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx:1082-1140` (탭 바 클래스)

**Interfaces:**
- Produces: 탭 라벨 `요약 · 그림 · 표 · 레시피 · 실험 계획`(각각 별개 문자열, 가운뎃점은 구분 표기가 아니라 이 문서의 나열 표기). 탭 key(`summary/figures/...`)는 불변 — 라벨만 변경.

- [ ] **Step 1: 라벨 교체** — `strings.ts`에서 `figuresTab: 'Figures'` → `'그림'`, `tablesTab: 'Tables'` → `'표'`, `recipeTab: 'Recipe'` → `'레시피'`, `experimentTab: '실험계획'` → `'실험 계획'` (grep으로 실제 키 이름 확인 후 동일 패턴 적용). 다른 화면에서 같은 문자열 키를 참조하는 곳이 있는지 `grep -rn "figuresTab\|tablesTab\|recipeTab\|experimentTab" src`로 확인하고, 있으면 그 화면에도 자연스러운지 눈으로 확인 후 적용.
- [ ] **Step 2: 탭 스타일** — 활성: `text-fg font-[650]` + 액센트 2px 언더라인(`box-shadow: 0 2px 0` 또는 border-bottom, 기존 구현 방식 유지 중 택1), 비활성: `text-fg-muted font-medium`. 탭 아이콘 렌더가 있으면 제거. 전환은 `transition-[color] duration-150`.
- [ ] **Step 3: 빌드·확인·커밋** — build+vitest 통과 후 `git commit -m "ui(workbench): 탭 라벨 한국어 통일(그림·표·레시피) 및 스타일 정리"`

---

### Task 4: 요약 메타 — 뱃지·평문 → 메타 그리드

**Files:**
- Modify: `sasoo/frontend/src/lib/workbenchSummaries.ts:84-88` (`expandedMeta` 배열)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx:287-298` (`phase-meta-pill` 렌더), `186-193` (`buildMetaPillStyle` — 미사용화되면 삭제)
- Test: `sasoo/frontend/src/lib/workbenchSummaries.test.ts` (Task 1 파일에 추가)

**Interfaces:**
- Produces: `expandedMeta: string[]` 대신 `metaItems: { label: string; value: string; accent?: boolean }[]` (기존 `expandedMeta`는 소비처가 287-298뿐이면 교체, 다른 소비처가 있으면 유지+추가). 값 한국어화: `experimental` → `실험 논문`, `high` → `높음` 등 매핑은 `workbenchSummaries.ts`에 상수로.

- [ ] **Step 1: 실패 테스트** — `metaItems`가 `[{label:'분야',value:'Optics'},{label:'관련도',value:'95%',accent:true},{label:'방법론',value:'실험 논문'},{label:'복잡도',value:'높음'}]` 형태를 내는지, 원본 값이 결측일 때 항목이 생략되는지 assert. 실행해 FAIL 확인.
- [ ] **Step 2: 구현·통과** — 매핑 상수(`complexity: high→높음/medium→보통/low→낮음`, `methodology: experimental→실험 논문/비실험 논문` — 기존 `expandedMeta` 84-88행의 원본 필드 재사용) 작성, 테스트 PASS.
- [ ] **Step 3: 렌더 교체** — 287-298행 pill 나열을 4열 그리드로:

```tsx
<div className="grid grid-cols-4 gap-3">
  {metaItems.map((m) => (
    <div key={m.label}>
      <div className="text-[10px] font-medium text-fg-muted">{m.label}</div>
      <div className={`text-[13px] font-[650] tabular-nums ${m.accent ? 'text-accent' : 'text-fg'}`}>{m.value}</div>
    </div>
  ))}
</div>
```

`buildMetaPillStyle`(186-193)이 다른 곳에서 안 쓰이면 삭제.
- [ ] **Step 4: 빌드·커밋** — `git commit -m "ui(workbench): 요약 메타를 컬러 뱃지에서 라벨·값 그리드로 교체"`

---

### Task 5: Figure 카드 재구성

**Files:**
- Modify: `sasoo/frontend/src/components/FigureGallery.tsx` — `qualityBadge` 47-62, 신뢰도 600-605, classifier 606-610, resolver 611-615, 이동 버튼 618-630

**Interfaces:**
- Consumes: 기존 figure 데이터(`confidence`, `classifier_model`, `resolver_version`, 페이지 번호, 클릭 시 PDF 이동 콜백 — 콜백 시그니처 불변)
- Produces: 카드 구조 — 풀블리드 썸네일(카드 상단, `overflow-hidden`으로 radius 공유) + 캡션 줄(제목 650 + 시맨틱 색점) + 메타 줄(11px muted tabular-nums)

- [ ] **Step 1: 카드 컨테이너** — 보더 제거, `rounded-[12px] overflow-hidden shadow-[0_1px_2px_rgba(0,0,0,.04),0_2px_8px_rgba(0,0,0,.04)]`, 선택 상태만 `shadow-[0_0_0_1.5px_rgb(var(--accent)),...]` 또는 기존 선택 메커니즘의 보더를 액센트로. 카드 루트를 클릭 영역으로(기존 618-630 버튼의 onClick을 카드 onClick으로 이동, `role="button"`·`tabIndex={0}`·Enter 키 처리 포함), `active:scale-[0.96] transition-transform duration-150`. 다크모드: 그림자 대신 `dark:bg-surface` 톤 차이(기존 `.dark` 변수).
- [ ] **Step 2: 신뢰도 색점** — 600-605행 % 뱃지 삭제 → 캡션 줄 우측 7px 색점(`confidence >= 0.7 ? 'bg-success' : 'bg-warning'` — 임계값은 기존 `qualityBadge` 47-62행이 쓰는 기준을 그대로 재사용, 새 임계값 발명 금지). 카드 `title` 속성으로 "신뢰도 53%, 검토를 권해요"(warning일 때) / "신뢰도 90%"(success일 때).
- [ ] **Step 3: 내부 용어 DEV 게이트** — 606-615행(classifier·resolver)을 `{import.meta.env.DEV && (…기존 뱃지…)}`로 감싼다(삭제 아님 — 개발 빌드 디버깅용 보존).
- [ ] **Step 4: 이동 버튼 삭제** — 618-630 아웃라인 버튼 제거(Step 1에서 카드 클릭으로 대체 완료 확인).
- [ ] **Step 5: 빌드·커밋** — `git commit -m "ui(workbench): Figure 카드 풀블리드·그림자·색점 재구성, 내부 용어 DEV 게이트"`

---

### Task 6: Table 카드 동일 적용 + 뱃지 구현 통일

**Files:**
- Modify: `sasoo/frontend/src/components/TableGallery.tsx` — `buildStatusBadge` 43-55, 신뢰도 184-189, resolver/classifier 190-204, 이동 버튼 247-257

**Interfaces:**
- Consumes: Task 5와 동일한 카드 문법(클래스 문자열·색점 임계 동일하게 — Task 5 결과 코드를 읽고 맞출 것)

- [ ] **Step 1: Task 5와 동일 구조 적용** — 카드 컨테이너·색점·DEV 게이트·버튼 삭제를 TableGallery에 반복. 자체 `buildStatusBadge`(43-55)가 만들던 `status-pill` 조합은 색점+툴팁으로 대체(Figure와 뱃지 구현 불일치 해소).
- [ ] **Step 2: 빌드·커밋** — `git commit -m "ui(workbench): Table 카드 재구성, Figure와 카드 문법 통일"`

---

### Task 7: 문구 전수 점검 + 실행 검증

**Files:**
- 점검: `sasoo/frontend/src/lib/strings.ts`, `workbenchSummaries.ts`, `AnalysisPanel.tsx`, `FigureGallery.tsx`, `TableGallery.tsx`, `ProgressTracker.tsx`
- 기록: 이 플랜 하단 "실측 결과" 절

- [x] **Step 1: 금지 패턴 grep** — `grep -rn "—\|→" src/components/AnalysisPanel.tsx src/components/FigureGallery.tsx src/components/TableGallery.tsx src/components/ProgressTracker.tsx src/lib/strings.ts src/lib/workbenchSummaries.ts` 로 UI 문자열 내 em-dash·화살표 잔존 0건 확인(주석·코드 로직 내 사용은 허용, 사용자 노출 문자열만 금지). `resolver\|heuristic` grep으로 DEV 게이트 밖 노출 0건 확인.
- [x] **Step 2: 전체 검증** — `pnpm vitest run` + `pnpm vite build` 통과.
- [x] **Step 3: 실행 스크린샷** — 앱을 띄워(프로젝트 launch 방법: `launch-sim` 스킬 또는 `pnpm dev` + Electron) 분석 완료 논문 1편의 요약·그림·표 탭 스크린샷을 찍고 목업 v2와 대조. 라이트·다크 모두. 스크린샷 파일 경로를 플랜 하단에 기록.
- [x] **Step 4: 결과 기록·커밋** — 플랜 하단에 검증 결과 추기 후 `git commit -m "docs(plan): 워크벤치 패널 재정비 검증 기록"`

---

## 실측 결과 (Task 7에서 기록)

작업 브랜치 `ui/workbench-right-panel`, 검증일 2026-08-04.

### Step 1: 금지 패턴 grep

`grep -rn "—\|→" src/components/AnalysisPanel.tsx src/components/FigureGallery.tsx src/components/TableGallery.tsx src/components/ProgressTracker.tsx src/lib/strings.ts src/lib/workbenchSummaries.ts` 결과 — 매치 8건, 전부 코드 주석(`AnalysisPanel.tsx:483,504`, `FigureGallery.tsx:78,209,520,521,535,664`). 사용자 노출 문자열 내 em-dash·화살표는 0건.

`grep -rn "resolver\|heuristic\|classifier" ...` 결과 — `FigureGallery.tsx:616-625`와 `TableGallery.tsx:216-225`는 모두 `import.meta.env.DEV && (...)` 게이트 안. `strings.ts:350-351`(`extractionPipelineHelp`, `extractionPipelineResolverV1`)와 `strings.ts:548`(`resolverLabel`)는 정의만 존재하고, 호출부(`S.figures.provenanceLabel`, `S.tables.resolverLabel`, `S.tables.modelLabel`)는 전부 위 DEV 게이트 내부에서만 쓰임. DEV 게이트 밖 노출 0건. 코드 수정 없음(위반 없어 정리할 것 없음).

### Step 2: 전체 검증

- `pnpm vitest run` — 8 test files, 54 tests 전부 통과.
- `pnpm vite build` — 8.28s에 정상 빌드 완료(경고 없음, 청크 사이즈 경고만 기존과 동일 수준).

### Step 3: 실행 스크린샷

- 백엔드: `cd sasoo/backend && .venv/bin/python -m uvicorn main:app --port 8000` (정상 기동, `/` 200 응답).
- 프론트: `cd sasoo/frontend && pnpm dev` (Vite 6.4.3, `http://127.0.0.1:5173`).
- 대상 논문: paper_id 999005 "GR00T N1: An Open Foundation Model for Generalist Humanoid Robots" (그림 14개, 표 7개 보유 — 그림·표 모두 확인 가능한 완료 논문).
- 라우팅은 `HashRouter`이므로 실제 접속 URL은 `http://127.0.0.1:5173/#/workbench/999005` (경로 없는 `/workbench/999005` 직접 접근은 홈으로 렌더링됨 — 앱 정상 동작, 조사 중 확인한 라우팅 특성일 뿐 버그 아님).
- 테마는 `prefers-color-scheme`이 아니라 `localStorage['sasoo-theme']`로만 결정됨(App.tsx:50-79) — Playwright `colorScheme` 컨텍스트 옵션은 무효, `page.addInitScript`로 `localStorage.setItem('sasoo-theme', ...)`를 주입해 라이트/다크를 강제.
- 캡처 도구: Playwright(Chromium) 1.58.0, `/tmp/pw-scratch`에 임시 설치(프로젝트 devDependencies 변경 없음).
- 스크린샷 6장, 요약·그림·표 탭 × 라이트·다크:
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-light-summary.png`
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-dark-summary.png`
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-light-figures.png`
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-dark-figures.png`
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-light-tables.png`
  - `.superpowers/sdd/2026-08-04-workbench-right-panel/screenshots/workbench-dark-tables.png`
- 목업 대비: 스테퍼·탭·메타 그리드·Figure/Table 풀블리드 카드 모두 목업 v2 방향대로 렌더링됨. Figure/Table 카드에 신뢰도 색점, DEV 게이트 badge(`분류 heuristic`, `resolver-v1`, `해결기 resolver-v1`, `복구 gemini-3.6-flash`)가 `pnpm dev` 환경(DEV=true)에서 정상적으로 노출됨(프로덕션 빌드에서는 게이트로 숨겨짐 — Step 1에서 코드 경로 확인, 프로덕션 빌드 화면 자체는 미검증). em-dash·화살표 등 금지 문자는 스크린샷 육안 확인상 없음.
- 검증 후 백엔드(8000)·프론트(5173) 프로세스 모두 종료 확인.

### Step 4: 결론

Task 1~6 결과물이 grep 점검·유닛 테스트·빌드·실행 스크린샷까지 전부 통과. 리뷰 대기.
