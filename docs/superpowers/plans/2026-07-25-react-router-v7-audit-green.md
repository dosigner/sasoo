# react-router v7 메이저 업그레이드 + 의존성 감사 green Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 파괴적 변경(major upgrade)이므로 각 Task 후 검증 게이트를 통과하기 전에는 다음으로 넘어가지 않는다.

**Goal:** `react-router-dom`을 v6 → v7로 올리고, 그 과정에서 막혀 있던 프론트엔드 의존성 감사(`pnpm audit`)를 루트·프론트 양쪽 모두 green(moderate 이상 0건)으로 만든다.

**Architecture:** 이 코드베이스는 react-router의 **선언형 안정 표면만** 쓴다(`HashRouter`, `Routes`, `Route`, `Link`, `NavLink`, `useNavigate`, `useLocation`, `useParams`). 데이터 라우터(`createBrowserRouter`)·제거 API(`json`/`defer`/`Switch`/`useLoaderData`)를 안 쓰므로, v7 마이그레이션은 사실상 (1) 버전 범프 + (2) future flag 확인/무변경 + (3) 감사 override 마무리로 수렴한다. 코드 변경은 최소 diff로 제한한다.

**Tech Stack:** React 18.2 + TypeScript, Vite 6, Vitest 3, pnpm 10.32.1, Node v26.3.1. 감사는 `pnpm audit --audit-level=moderate` (CI `build-check.yml`의 "Audit root dependencies" / "Audit frontend dependencies" 스텝과 동일).

## 배경 (조사 완료된 사실)

- **감사 실패는 PR #29(이미지 1장)와 무관하며 main에 이미 있던 잠복 문제다.** CI는 "Audit root dependencies"가 먼저 exit 1로 죽어 "Audit frontend dependencies"까지 도달하지 못했을 뿐, 뒤에 프론트 실패가 숨어 있었다.
- **main은 브랜치 보호가 없다** → 감사는 병합 필수 체크가 아니다. 이 작업은 "품질 게이트를 실제로 green으로 되돌리는" 위생 작업이다.
- 루트 감사 잔여: `brace-expansion (<=5.0.7)` — `electron-builder > app-builder-lib > @electron/{asar,universal} > minimatch > brace-expansion` 경로. (postcss·tar는 아래 "선행 작업"에서 이미 해결.)
- 프론트 감사 잔여: `brace-expansion (<1.1.16, <=5.0.7)` + `react-router (>=6.0.0 <7.18.0)` + `react-router-dom (>=6.30.2 <=6.30.4)`.
- **`react-router-dom` 6.x는 6.30.4가 마지막이고 패치가 없다.** 취약점 제거의 유일한 경로가 v7(최신 7.18.x)이다.

## 선행 작업 상태 (이어받을 것)

- 로컬 브랜치 `chore/audit-overrides-postcss-tar` (origin/main 기준)에 **미커밋** 변경이 있다:
  - `sasoo/package.json` pnpm.overrides에 3줄 추가: `postcss@8.5.17→8.5.23`, `tar@7.5.20→7.5.22`, `brace-expansion@5.0.7→5.0.8`
  - `sasoo/pnpm-lock.yaml` 재생성됨
  - 검증 결과: 루트 감사에서 **postcss·tar는 해소**, brace-expansion은 아직 잔존(exact-version 키가 electron-builder 경로의 minimatch 하위를 못 잡음).
- 이 브랜치 위에서 이어가거나, 새 브랜치 `chore/react-router-v7-and-audit`로 정리해 시작한다.

## Global Constraints

- **소스 레벨 수정.** 감사 무시(`--force`, `ignoreCves`, audit level 완화) 금지. 취약점은 실제 버전 상향으로만 해결한다.
- **유지+추가.** 기존 `pnpm.overrides` 항목을 삭제하지 않는다. 필요한 것만 추가/조정한다.
- **최소 diff.** 파괴적 변경이므로 react-router 관련 diff는 버전 범프 + (필요 시) future flag 대응에 한정한다. "온 김에" 리팩터링 금지.
- **무관한 변경 금지.** 작업 트리에 이미 존재하는 `M .gitignore`는 건드리지 않는다.
- **정확한 버전은 실측.** override 대상 패치 버전은 `npm view <pkg> versions`로 확인하고 추정하지 않는다.
- **override 키는 실제 lockfile 버전과 일치해야 한다.** exact-version 키(`brace-expansion@5.0.7`)는 그 버전이 트리에 있을 때만 잡힌다. 잔존 시 범위 키(`brace-expansion@<1.1.16` 식, 프론트 기존 관례) 또는 경로 스코프 override로 전환한다.
- **명령 실행 위치:** 루트 작업은 `sasoo/`, 프론트 작업은 `sasoo/frontend/`에서 실행한다.
- **가드레일: 에이전트는 병합·publish 불가.** PR 생성까지만. 병합은 사용자가 `! gh pr merge`로 한다.
- **서브에이전트 fable 금지.** 탐색=sonnet, 무거운 추론=opus를 model로 명시한다.

## File Structure

| 파일 | 역할 |
|---|---|
| `sasoo/frontend/package.json` (수정) | `react-router-dom ^6.30.4 → ^7.18.x`, `pnpm.overrides`에 brace-expansion 잔여 취약 버전 추가 |
| `sasoo/frontend/pnpm-lock.yaml` (재생성) | 위 반영 |
| `sasoo/frontend/src/**` (조건부 수정) | tsc/런타임이 요구할 때만 최소 수정. future flag 경고 대응. 기대: 무변경~극소 |
| `sasoo/package.json` (수정) | 루트 brace-expansion override 마무리 (postcss·tar는 선행 작업에서 완료) |
| `sasoo/pnpm-lock.yaml` (재생성) | 위 반영 |

react-router 임포트 지점 9개 파일(수정 후보, 대부분 무변경 예상):
`src/main.tsx`, `src/App.tsx`, `src/components/ErrorBoundary.tsx`, `src/components/home/UploadPanel.tsx`, `src/components/layout/AppSidebar.tsx`, `src/pages/Home.tsx`, `src/pages/Settings.tsx`, `src/pages/Workbench.tsx`, `src/pages/Library.tsx`

---

### Task 0: 공식 v7 업그레이드 가이드 확보

v6→v7의 실제 breaking change와 future flags 목록을 근거로 확보한다. 이 코드가 쓰는 심볼에 영향 있는 항목만 추린다.

**Steps:**
- [ ] Context7로 react-router v7 문서 조회 (`resolve-library-id` → `query-docs`, 질의: "react-router v6 to v7 upgrade guide, future flags, breaking changes")
- [ ] 사용 심볼 8종(`HashRouter, Routes, Route, Link, NavLink, useNavigate, useLocation, useParams`)에 영향 있는 변경만 목록화
- [ ] future flags(`v7_startTransition`, `v7_relativeSplatPath`, `v7_fetcherPersist`, `v7_normalizeFormMethod`, `v7_partialHydration`, `v7_skipActionErrorRevalidation`) 중 이 구성에 관계있는 것 판별

**Verify:** 영향 목록이 문서로 정리됨(변경 필요/불필요 판정 포함).

---

### Task 1: react-router-dom v7 범프 + 코드 조정

**Files:** `sasoo/frontend/package.json`, `sasoo/frontend/pnpm-lock.yaml`, (조건부) `src/**`

**Steps:**
- [ ] `npm view react-router-dom version`으로 최신 v7 확인 후 `package.json`에서 `"react-router-dom": "^7.x.x"`로 수정
- [ ] `cd sasoo/frontend && pnpm install --lockfile-only`로 lockfile 재생성
- [ ] `pnpm tsc --noEmit` — 타입 오류가 나오면 해당 지점만 최소 수정 (임포트 경로는 유지 우선; 공식 가이드가 `react-router` 경로를 강제할 때만 변경)
- [ ] future flag deprecation 경고가 런타임에 뜨면 가이드에 따라 대응 (이 구성에선 불필요할 가능성 높음)

**Verify:**
- [ ] `pnpm tsc --noEmit` 0 에러
- [ ] react-router diff가 버전 범프(+필요 시 flag)에 한정됨

---

### Task 2: 감사 override 마무리 (프론트 + 루트 brace-expansion)

**Files:** `sasoo/frontend/package.json`, `sasoo/package.json` (+ 각 lockfile)

**Steps:**
- [ ] 프론트: `sasoo/frontend/pnpm-lock.yaml`에서 잔존 brace-expansion 버전 실측 → `pnpm.overrides`에 패치 버전 추가(기존 `brace-expansion@<1.1.13` 관례에 맞춰 범위 키 우선). 각 major 라인 패치: 1.x→1.1.16, 2.x→2.1.2, 5.0.7→5.0.8 (실측 후 확정)
- [ ] 루트: `sasoo/package.json`의 brace-expansion override를 electron-builder 경로까지 잡도록 마무리 (exact-version이 안 잡으면 범위 키/경로 스코프로 전환). postcss·tar override는 유지
- [ ] 각 디렉토리에서 `pnpm install --lockfile-only`
- [ ] 정확한 패치 버전은 `npm view <pkg> versions`로 실측

**Verify:**
- [ ] `cd sasoo && pnpm audit --audit-level=moderate; echo "root exit=$?"` → **exit 0**
- [ ] `cd sasoo/frontend && pnpm audit --audit-level=moderate; echo "fe exit=$?"` → **exit 0**
- [ ] (파이프 없이 exit code 직접 확인 — `| tail`은 tail의 종료코드를 반환하므로 금지)

---

### Task 3: 전체 검증 게이트

빌드·테스트·런타임까지 실제로 통과하는지 확인한다. 하나라도 실패하면 완료 아님.

**Steps:**
- [ ] `cd sasoo/frontend && pnpm build` (`tsc -b && vite build`) 성공
- [ ] `cd sasoo/frontend && pnpm test` (`vitest run`) 통과
- [ ] `cd sasoo/frontend && pnpm lint` (`--max-warnings 0`) 통과
- [ ] `cd sasoo && pnpm build:electron` — react-router 범프가 electron 빌드에 영향 없음 sanity
- [ ] **런타임 스모크:** 앱을 띄워 라우팅 이동(홈 → 워크벤치 → 설정 → 라이브러리, `HashRouter` 기반)이 정상인지 확인. `run` 스킬 또는 프로젝트 launch 절차 사용. GUI 변경이므로 실행 화면(스크린샷)까지 확인
- [ ] 루트·프론트 감사 재확인 (Task 2 Verify 재실행)

**Verify:** 위 6종 전부 통과 + 감사 2종 exit 0.

---

### Task 4: 커밋·PR (병합은 사용자)

**Steps:**
- [ ] 커밋 분리: (1) `feat/build: react-router v7 범프 + 코드 조정`, (2) `chore(security): 의존성 감사 override 마무리(brace-expansion 루트·프론트)`
- [ ] `M .gitignore` 등 무관한 변경은 스테이징에서 제외
- [ ] push 후 PR 생성 (base: main)
- [ ] 사용자용 병합 명령 제시(예: `! gh pr merge <n> --squash --delete-branch`). **직접 병합하지 않는다.**

**Verify:** PR가 생성되고, CI의 windows job(감사 포함)이 green.

---

## 리스크 · 롤백

- **위험도: 낮음.** 사용하는 react-router API가 전부 v6/v7 공통 안정 표면이라, 예상 코드 변경은 무변경~극소. 실제 위험은 future flag 동작 차이 정도이며 런타임 스모크로 잡는다.
- **롤백:** 각 커밋이 독립적이라 `git revert`로 되돌릴 수 있다. lockfile은 `git checkout origin/main -- <lock>`으로 복구.
- **감사 whack-a-mole 주의:** 새 advisory가 언제든 뜰 수 있다. exact-version 키보다 범위 키가 재발에 강하다(프론트 기존 관례 참고).
- **미해결로 남길 수 있는 것:** deprecated **subdependency** 경고(boolean, glob, inflight, rimraf 등)는 moderate 미만이면 감사 게이트와 무관하므로 이번 범위 밖. `log()`로 남기되 손대지 않는다.

## 성공 기준 (측정 가능)

1. `cd sasoo && pnpm audit --audit-level=moderate` → exit 0 (moderate+ 0건)
2. `cd sasoo/frontend && pnpm audit --audit-level=moderate` → exit 0 (moderate+ 0건)
3. `pnpm tsc --noEmit` / `pnpm build` / `pnpm test` / `pnpm lint` / `pnpm build:electron` 전부 통과
4. 앱 라우팅 런타임 스모크 통과(실행 화면 확인)
5. react-router diff가 버전 범프(+필요 시 future flag)에 한정
