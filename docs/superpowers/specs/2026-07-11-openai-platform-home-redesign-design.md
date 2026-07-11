# OpenAI Platform 스타일 홈 + 라벨 사이드바 리디자인 설계

- 날짜: 2026-07-11
- 브랜치: feature/gui-redesign
- 참고 대상: platform.openai.com/home (구조 문법만 차용, 색상 체계는 기존 유지)

## 목표

sasoo에 홈 허브를 신설하고 아이콘 전용 레일을 라벨 사이드바로 교체한다. OpenAI Platform에서
가져오는 것은 구조 문법(홈 허브, 섹션 그룹핑된 사이드바, 카드 그리드, 여백 리듬)이며,
기존 다크 기본 + Linear식 모노크롬 + 인디고 액센트 토큰 체계는 그대로 유지한다.

## 범위에서 제외

- 토큰 재정의(라이트 우선 전환, 색상 변경) — 하지 않음
- Workbench(`/workbench/:id`) 레이아웃 변경 — 지금처럼 사이드바 없는 풀스크린 유지
- Library / Agents / Settings 페이지 내부 리디자인

## 1. 정보 구조 (라우팅)

| 라우트 | 변경 |
|---|---|
| `/` | Upload 페이지 → **Home 페이지 신설** (Upload 기능 흡수) |
| `/library`, `/agents`, `/settings` | 유지 |
| `/workbench/:id` | 유지 (사이드바 없는 풀스크린) |

- `Upload.tsx`는 삭제한다. 업로드 폼/드래그앤드롭 로직은 컴포넌트로 추출해 Home에서 재사용한다.
- 기존 `/` 진입 동선은 홈 상단 드롭존이 이어받으므로 리다이렉트는 불필요하다.

## 2. 사이드바 — `AppSidebar` 신설

`App.tsx`의 `app-desktop-rail`(폭 4.5rem, 아이콘 전용)을 대체한다.

- 펼친 상태: 폭 약 13rem, 아이콘 + 텍스트 라벨.
- 섹션 그룹핑 (작은 섹션 헤더):
  - 상단: 앱 이름/로고
  - **작업**: 홈(`/`), 서재(`/library`)
  - **관리**: 에이전트(`/agents`), 설정(`/settings`)
- 접기 토글: 접으면 현재 4.5rem 아이콘 레일과 동일한 모습 — 기존 레일 스타일을 collapsed
  상태로 재활용한다. 접힘 상태는 localStorage에 저장한다.
- 스타일: 기존 시맨틱 토큰(`surface`, `border`, `fg-secondary`, `accent` 등)만 사용.
  새 토큰 추가 없음. 활성 항목은 기존 레일의 활성 표시 관례를 따른다.

## 3. 홈 페이지 구성 — `Home.tsx` 신설

위에서 아래 순서:

1. **인사말 헤더** — "안녕하세요, 동주님" 수준의 가벼운 한 줄 + 날짜.
2. **업로드 드롭존** — 기존 Upload 페이지의 폼/드래그앤드롭 로직을 추출한 컴포넌트.
3. **퀵액션 카드 2~3장** — "에이전트 실행"(→ `/agents`), "서재 열기"(→ `/library`) 등.
4. **최근 논문** — 기존 `RecentPaperRow` 재사용. 클릭 시 `/workbench/:id` 이동.
5. **이번 달 비용 스냅숏** — Settings의 `CostDashboard` 데이터 소스를 재사용한 축약 위젯.
   클릭 시 설정의 비용 섹션으로 이동.

## 4. 스타일 원칙

- 다크 기본 유지, 토큰 재정의 없음.
- 카드: `surface` 배경 + `border` 1px + radius 12px(기존 `surface` radius), 그림자 없음.
- 섹션 헤더: 작고 옅은 텍스트(`fg-muted`)로 콘텐츠 구획 — OpenAI Platform 문법.
- 애니메이션 150ms cap 규칙 준수 (`docs/04-design/design-tokens.md`).

## 5. 대상 파일

| 파일 | 작업 |
|---|---|
| `sasoo/frontend/src/App.tsx` | 레일 → `AppSidebar`로 교체, 라우트 갱신 |
| `sasoo/frontend/src/components/layout/AppSidebar.tsx` | 신설 |
| `sasoo/frontend/src/pages/Home.tsx` | 신설 |
| `sasoo/frontend/src/pages/Upload.tsx` | 삭제 (업로드 폼 로직은 컴포넌트로 추출) |
| `sasoo/frontend/src/components/layout/PageScaffold.tsx` | 필요시 variant 추가 |

## 6. 검증 기준

- Electron 앱 재시작 후 5개 라우트 전부 실행 화면(스크린샷) 확인 — launch-sim 스킬 활용.
- 사이드바 접기/펼치기 동작 및 localStorage 유지 확인.
- 라이트 테마 전환, density compact 상태에서 홈·사이드바 QA.
- 기존 업로드 동선(드래그앤드롭 → 분석 시작)이 홈에서 동일하게 동작.
