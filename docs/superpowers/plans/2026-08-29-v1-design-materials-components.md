# sasoo v1.0.0 디자인 확정안 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-08-29 디자인 인터뷰(메모리 `sasoo-v1-design-direction`)로 확정한 v1.0.0 스타일을 PR 2개로 구현한다 — ① macOS 재질 PR: 사이드바·타이틀바 vibrancy + 앱 테마→`nativeTheme` 동기화 + reduce-transparency 폴백, ② 컴포넌트 공통 PR: 카드 호버 배경 전환, 워크벤치 밖 상태 칩 아웃라인화, 라벨 로딩 shimmer, 보관함 테이블 40px, 설정·프로필 명도 블록, 죽은 CSS 정리.

**Architecture:** 재질은 플랫폼 분기(신규 `platform-darwin`/`platform-win32` 루트 클래스), 컴포넌트는 양 플랫폼 공통. macOS 창은 OS vibrancy가 블러를 담당하므로 CSS는 알파 틴트만 얹는다(darwin에서 body·app-shell 배경을 투명화하고 콘텐츠 영역만 불투명 `bg-bg`를 유지). 플로팅 표면(모달·플로팅 채팅·토스트)은 기존 CSS `backdrop-blur`(앱 내용 블러)를 유지하고 알파만 낮춘다. Windows는 창 배경 불투명 그대로(변경 없음).

**Tech Stack:** Electron(vibrancy, nativeTheme, IPC), React 19, Tailwind 4(`@utility` 토큰 체계, `frontend/src/index.css`), vitest(순수 함수만), pnpm.

**시각 기준(목업 아티팩트):** macOS 글래스 https://claude.ai/code/artifact/ef8ccb1a-5bfd-41b4-9fa7-36f0a9d6b48a (B 변형) / 디테일 프로브 https://claude.ai/code/artifact/1f45a8fa-4df5-41a0-b34b-76ebcd45be04 (확정: 1-A, 2-B, 3-A, 4-B, 5-B, 6-B, 7-A, 8-B)

## Global Constraints

- **워크벤치 무수정**: `chip-tint`/`chip-soft` 3종 어휘·굵기(PR #43 계약 6개), 워크벤치 상태부 진행 레일(`AnalysisPanel.tsx:1111` 부근), `components/ui/Badge.tsx`와 그 소비처(RecipeCard, FigureGallery), 워크벤치 우측 패널 밀도는 건드리지 않는다.
- **프로필 기능 계약 5개 무수정**(메모리 `sasoo-researcher-profile`): 기본값 지시문 바이트 동일, 설명수준 마지막, 화이트리스트 치환, 값 4쌍 일치, LevelSlider 삭제 금지. 프로필 페이지는 스타일만 바꾼다.
- **accent 불변**: 라이트 `104 61 204`, 다크 `124 90 232`.
- 모션 어휘 불변: 신규 애니메이션은 기존 `--ease-out-strong`, 0.15~0.2s 범위. `prefers-reduced-motion`에서 shimmer는 정적 텍스트로 폴백.
- `prefers-reduced-transparency`: CSS 폴백(기존)에 더해 OS vibrancy도 꺼져야 한다(PR 1 Task 3).
- 사용자 문구는 `frontend/src/lib/strings.ts`의 `S` 객체 경유(기존 관례). 신규 문구 없음이 목표.
- 커밋은 각 feature 브랜치에서. main 직접 커밋 금지. v1.0.0 버전 bump는 이 계획 범위 밖(릴리스 절차 `scripts/sync-version.js`에서 별도).
- 현재 작업 트리에 `chore/major-upgrades` 브랜치의 미커밋 변경이 있다. 이 계획의 브랜치는 그 위가 아니라 **origin/main 기준**으로 딴다(충돌 시 사용자에게 보고).

---

# PR 1 — macOS 재질 (브랜치 `feat/v1-macos-vibrancy`)

### Task 0: 브랜치 + Electron API 사실 확인

- [ ] **Step 1: 브랜치 생성** — `git fetch origin && git checkout -b feat/v1-macos-vibrancy origin/main`
- [ ] **Step 2: Electron 버전과 API 확인** — `sasoo/package.json`의 electron 버전에서 다음 두 API의 존재를 공식 문서로 확인: `nativeTheme.prefersReducedTransparency`(있으면 Task 3에서 사용, 없으면 `systemPreferences.getUserDefault('AppleReduceTransparency', 'boolean')` + `subscribeNotification` 대체), `BrowserWindow` 옵션 `vibrancy: 'sidebar'` + `visualEffectState: 'followWindow'`. 확인 결과를 Task 3 구현 방식에 반영.

### Task 1: 창 옵션 + 테마 IPC (main·preload)

**Files:**
- Modify: `sasoo/electron/main.ts`
- Modify: `sasoo/electron/preload.ts`

- [ ] **Step 1: BrowserWindow darwin 분기 확장** — `main.ts:49`의 darwin 스프레드에 `vibrancy: 'sidebar'`, `visualEffectState: 'followWindow'` 추가. darwin에서는 `backgroundColor`를 `'#00000000'`으로(비-darwin은 기존 `'#0a0a0b'` 유지). 주석으로 "vibrancy가 블러 담당, CSS는 틴트만" 제약 명시.
- [ ] **Step 2: 테마 IPC** — `ipcMain.handle('theme:set', ...)`: sender가 mainWindow인지 확인(기존 `isMainWindowSender` 패턴) 후 `'dark' | 'light'`만 허용해 `nativeTheme.themeSource`에 대입. `preload.ts`의 `ElectronAPI` 인터페이스와 객체에 `setNativeTheme(theme)` 추가(`invoke('theme:set', theme)`).
- [ ] **Step 3: 빌드 확인** — `cd sasoo && pnpm build:electron`(스크립트명은 package.json 확인) 통과.
- [ ] **Step 4: Commit** — `feat(electron): macOS vibrancy 창 옵션과 theme:set IPC`

### Task 2: 렌더러 테마 적용 경로 일원화 + 플랫폼 클래스

**Files:**
- Create: `sasoo/frontend/src/lib/theme.ts`
- Modify: `sasoo/frontend/src/App.tsx`, `components/layout/AppSidebar.tsx`, `pages/Settings.tsx`, `components/Titlebar.tsx`, `components/UpdateBanner.tsx`

- [ ] **Step 1: `lib/theme.ts` 작성** — `isMac`(navigator.platform 판정, Titlebar·UpdateBanner의 중복 구현을 이관), `applyTheme(theme)`: documentElement `.dark`/`.light` 토글 + `localStorage['sasoo-theme']` 저장 + `window.electronAPI?.setNativeTheme?.(theme)` 호출(웹 환경에서는 no-op).
- [ ] **Step 2: 소비처 교체** — App.tsx:53-76, AppSidebar.tsx:47-59, Settings.tsx:216-223의 자체 구현을 `applyTheme` 호출로 치환(백엔드 `updateSettings({theme})` 동기화는 기존 위치 유지). Titlebar.tsx:36, UpdateBanner.tsx:12는 `isMac` import로 교체.
- [ ] **Step 3: 플랫폼 클래스** — App.tsx 마운트 시 documentElement에 `platform-darwin` 또는 `platform-win32`(그 외 `platform-linux`) 클래스 부착.
- [ ] **Step 4: 테스트·빌드** — `cd sasoo/frontend && pnpm test && pnpm build` 통과.
- [ ] **Step 5: Commit** — `refactor(frontend): 테마 적용 경로를 lib/theme.ts로 일원화, 플랫폼 루트 클래스 추가`

### Task 3: reduce-transparency 시 vibrancy 해제

**Files:**
- Modify: `sasoo/electron/main.ts`

- [ ] **Step 1:** Task 0 확인 결과에 따라 main 프로세스에서 투명도 감소 설정을 감지(`nativeTheme.on('updated')` 권장)해, 감소 시 `mainWindow.setVibrancy(null)`, 해제 시 `setVibrancy('sidebar')` 복원. 초기 창 생성 직후에도 1회 평가.
- [ ] **Step 2: Commit** — `feat(electron): reduce-transparency에서 vibrancy 해제`

### Task 4: darwin CSS 틴트

**Files:**
- Modify: `sasoo/frontend/src/index.css`, `components/Titlebar.tsx`

- [ ] **Step 1: 배경 투명화 체인** — `.platform-darwin` 한정: `body`와 `app-shell` 배경을 `transparent`로, 페이지 콘텐츠 영역(`page-scaffold` 계열)은 불투명 `bg-bg` 유지. 사이드바(`app-sidebar`)와 타이틀바는 `rgb(var(--surface) / 0.66)`(다크 0.58) 틴트로, CSS `backdrop-filter`는 붙이지 않는다(OS가 블러 담당).
- [ ] **Step 2: 플로팅 알파** — `.platform-darwin` 한정으로 모달(`figure-modal-inspector` 등), 플로팅 채팅(`chat-floating-card`, `chat-launcher`), 토스트(`toast-surface`), 저장바(`settings-savebar`)의 배경 알파를 0.72(다크 0.66) 수준으로 하향(기존 0.9~0.95). 기존 `backdrop-blur-*`는 유지.
- [ ] **Step 3: 접근성 회귀 확인** — `prefers-reduced-transparency` 블록이 위 신규 틴트 표면들도 불투명 `--surface`로 되돌리는지 확인·보강.
- [ ] **Step 4: Commit** — `feat(frontend): darwin 전용 vibrancy 틴트 레이어`

### Task 5: PR 1 실기 검증 (macOS)

- [ ] 라이트/다크 토글 시 사이드바 vibrancy 외관이 즉시 따라오는가(어긋남 없음)
- [ ] 데스크톱 월페이퍼가 사이드바·타이틀바에 비치고, 콘텐츠 영역은 불투명한가(목업 B 변형과 대조)
- [ ] 시스템 설정 "투명도 감소" 켜면 사이드바가 불투명 surface로 폴백하는가
- [ ] 전체화면·최대화·사이드바 접힘에서 렌더 깨짐 없는가
- [ ] `pnpm test`·`pnpm build`·eslint 통과, 스크린샷 첨부 후 PR 생성(병합은 사용자)

---

# PR 2 — 컴포넌트 공통 (브랜치 `feat/v1-component-refresh`, PR 1과 독립·병행 가능)

### Task 6: 카드 호버 배경 전환 (프로브 2-B)

**Files:**
- Modify: `sasoo/frontend/src/index.css`

- [ ] **Step 1:** `library-soft-card`(index.css:783-793) hover의 `-translate-y-0.5`·`shadow-lg`를 제거하고 `bg-surface-hover` 계열 배경 전환으로 교체. 쉬는 상태 `shadow-xs`는 유지(3라운드 결정). focus-visible ring은 유지하되 translate 제거. `chat-launcher`(1410행)의 `hover:-translate-y-0.5`도 배경 전환으로 교체.
- [ ] **Step 2:** reduced-motion 블록(1711행 부근)에서 이제 불필요해진 hover-lift 무효화 규칙 정리.
- [ ] **Step 3: Commit** — `feat(frontend): 카드 호버를 리프트에서 배경 전환으로`

### Task 7: 워크벤치 밖 상태 칩 아웃라인화 (프로브 5-B, 의미색 유지)

**Files:**
- Modify: `sasoo/frontend/src/index.css`, `components/home/RecentPaperRow.tsx`

- [ ] **Step 1:** `archive-inline-status`와 `-success`/`-error` 변형(index.css:295-313)을 제자리 재스타일: 배경 틴트 제거(`background: transparent`), `1px` 보더를 의미색 `/0.4`로, 글자색 의미색 유지. 소비처(Library 374·377·380·589, Settings 390-413, Profile 246·255, UploadPanel 299·466·491)는 클래스 그대로라 무수정.
- [ ] **Step 2:** `RecentPaperRow.tsx:29-40`의 수제 `paperStatusClass()`(`bg-*/10` 틴트)를 같은 아웃라인 조합(`border-*/40 text-*`, 배경 없음)으로 수정. Library 테이블의 `statusTone` 도트+텍스트는 이미 배경 없는 표기이므로 무수정.
- [ ] **Step 3: 죽은 CSS 삭제** — tsx 소비처 0건 확인된 `badge-primary/success/warning/error`(`badge` 베이스는 워크벤치가 쓰므로 유지), `library-status-badge`, `library-shelf-row--*` 4종, `card-hover`(+ reduced-motion 블록의 `.card-hover` 참조)를 index.css에서 제거. 삭제 후 `grep`으로 잔여 참조 0건 확인.
- [ ] **Step 4: Commit** — `feat(frontend): 워크벤치 밖 상태 칩 아웃라인화, 죽은 배지 CSS 정리`

### Task 8: 라벨 로딩 shimmer (프로브 4-B, 아는 구간만 바)

**Files:**
- Modify: `sasoo/frontend/src/index.css`, `components/ui/ContentState.tsx`, `components/home/UploadPanel.tsx`, `pages/Library.tsx`, `pages/Settings.tsx`, `pages/Profile.tsx`

- [ ] **Step 1:** `.shimmer-label` 유틸리티 추가 — 텍스트 밝기 스윕(`background-clip: text`, `--fg-muted`↔`--fg` 그라디언트, 약 2s linear 반복). `prefers-reduced-motion`에서는 애니메이션 없는 `text-fg-muted` 정적 텍스트.
- [ ] **Step 2: 라벨 동반 로딩만 교체** — ContentState 로딩 variant(65행, 공용 진입점), UploadPanel `stage==='parsing'`(286행의 가짜 100% 바를 제거하고 shimmer 라벨로 — 실제 진행률을 아는 업로드 구간의 바+%는 유지), Library 598·814, Settings 370·648, Profile 224 중 **텍스트 라벨이 함께 있는 곳만** spinner를 shimmer로 교체. 버튼 안 아이콘 스피너(SaveBar 39 등)와 UpdateBanner 결정형 바는 무수정.
- [ ] **Step 3: Commit** — `feat(frontend): 라벨 로딩 상태를 shimmer로 통일`

### Task 9: 보관함 테이블 40px (프로브 7-A)

**Files:**
- Modify: `sasoo/frontend/src/index.css`

- [ ] **Step 1:** `library-table tbody td`(756-759행) `py-3`→`py-2.5`(text-sm 줄높이 1.25rem + 상하 0.625rem = 40px). 제목 2줄 clamp 행의 시각 확인 필수. thead·그리드 뷰·홈 최근 목록은 무수정(3라운드 결정).
- [ ] **Step 2: Commit** — `feat(frontend): 보관함 테이블 행 40px 컴팩트`

### Task 10: 설정·프로필 명도 블록 (프로브 8-B, 두 페이지 통일)

**Files:**
- Modify: `sasoo/frontend/src/index.css`, `pages/Settings.tsx`, `pages/Profile.tsx`

- [ ] **Step 1:** `.settings-row-block` 유틸리티 추가 — 행별 `bg-surface-hover`(라이트에서 옅은 블록), `border-radius: var(--radius-control)`, 프로브 B 변형 기준 padding.
- [ ] **Step 2:** Settings.tsx `SettingSection`(38행)의 `divide-y divide-border`를 `flex flex-col gap-1` + 각 `SettingRow`에 블록 클래스로 교체. Profile.tsx의 수동 `border-t`(318행)를 제거하고 같은 블록 패턴으로 항목 행을 통일(그룹 간 여백 `space-y-8`은 유지, 기능 계약 5개 무수정 — 마크업 구조와 값 흐름 불변, 클래스만 변경).
- [ ] **Step 3: Commit** — `feat(frontend): 설정·프로필 항목 구분을 명도 블록으로 통일`

### Task 11: PR 2 검증

- [ ] `cd sasoo/frontend && pnpm test && pnpm build`, eslint 통과 (워크벤치 테스트 `workbenchSummaries.test.ts` 회귀 없음 확인)
- [ ] macOS 실기: 홈·보관함(테이블/그리드)·설정·프로필·업로드 흐름 스크린샷, 라이트/다크 각 1회, reduced-motion에서 shimmer 정적 폴백 확인
- [ ] Windows 실기(사용자 확인 가능): 같은 화면 체크리스트로 확인 — 특히 아웃라인 칩 대비, 40px 행, shimmer 렌더
- [ ] 워크벤치 화면 열어 칩·밀도·진행 레일이 변경 전과 동일함을 눈으로 확인(계약 검증)
- [ ] PR 생성(병합은 사용자)
