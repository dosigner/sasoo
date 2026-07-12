# 디자인 시스템 v2 + 홈/사이드바 리디자인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디자인 시스템 v2(라이트 기본, 퍼플 액센트)를 적용하고, 홈 허브 페이지와 라벨 사이드바를 신설한다.

**Architecture:** 13개 시맨틱 토큰의 값만 교체하고(`:root`=라이트, `.dark`=다크로 블록 스왑) 토큰명·컴포넌트 계약은 유지한다. 아이콘 레일을 접이식 라벨 사이드바(`AppSidebar`)로 교체하고, Upload 페이지를 새 Home 페이지가 흡수한다.

**Tech Stack:** React 18 + TypeScript + Tailwind CSS 3.4 (CSS 변수 시맨틱 토큰) + Electron, react-router-dom 6

**스펙:** `docs/superpowers/specs/2026-07-12-design-system-v2-design.md` (토큰 값·근거), `docs/superpowers/specs/2026-07-11-openai-platform-home-redesign-design.md` (구조)

## Global Constraints

- 시맨틱 토큰은 **13개 고정, 추가 금지** (`--bg --surface --surface-hover --border --fg --fg-secondary --fg-muted --accent --accent-hover --accent-fg --danger --warning --success`)
- 토큰 값은 RGB 채널 형식 (`--bg: 247 247 248;`), Tailwind에서 `rgb(var(--x) / <alpha-value>)`로 소비
- 폰트는 Pretendard Variable 유지. Inter 도입 금지. mono는 기존 JetBrains Mono 스택
- 애니메이션 ≤150ms cap 유지
- 카드·사이드바·리스트는 무그림자(1px 보더). 모달·팝오버·드래그 오버레이의 그림자는 유지
- 각 태스크 종료 시 `cd sasoo/frontend && pnpm build`(= `tsc -b && vite build`)가 통과해야 함 (단위 테스트 인프라 없음 — 빌드 + Task 6 시각 QA로 검증)
- 작업 디렉토리: 저장소 루트는 `/Users/dongj/dev/논문_사수_개발중`, 프론트엔드는 `sasoo/frontend`

---

### Task 1: 토큰 v2 — 테마 블록 스왑 (라이트 기본) + 퍼플 액센트

**Files:**
- Modify: `sasoo/frontend/src/index.css:13-87` (`:root`/`.light` 블록), `:96-102` (body 배경), `:151-156` (`.app-shell` 배경)
- Modify: `sasoo/frontend/src/components/MermaidRenderer.tsx:184,195`

**Interfaces:**
- Produces: `:root` = 라이트 v2 토큰(신규 기본), `.dark` = 다크 토큰. `.light` 클래스는 폐기(빈 no-op도 남기지 않음). 이후 모든 태스크는 이 토큰을 소비.

- [ ] **Step 1: index.css 토큰 블록 스왑**

`index.css`의 `:root` 색상 토큰(13~27행)과 아이콘/에이전트 틴트 변수(38~47행)를 라이트 v2 값으로 교체하고, `.light` 블록(66~87행)을 `.dark` 블록(다크 값)으로 교체한다. 레이아웃·모션·radius·density 변수는 그대로 둔다.

```css
:root {
  /* Semantic color tokens — RGB channels; ref docs/04-design/design-tokens.md §1 */
  /* Light (default) — design system v2 */
  --bg: 247 247 248;
  --surface: 255 255 255;
  --surface-hover: 239 239 241;
  --border: 228 228 231;
  --fg: 24 24 27;
  --fg-secondary: 82 82 91;
  --fg-muted: 112 112 122;
  --accent: 104 61 204;
  --accent-hover: 82 33 182;
  --accent-fg: 255 255 255;
  --danger: 220 38 38;
  --warning: 217 119 6;
  --success: 22 163 74;

  /* Layout */
  --sidebar-width: 13rem;
  --sidebar-collapsed-width: 4.5rem;
  --header-height: 3rem;
  --app-rail-width: 4.5rem;

  /* Motion */
  --transition-speed: 150ms;

  /* Icons */
  --icon-stroke: 1.7;
  --icon-highlight-opacity: 0.24;
  --icon-surface-border: rgba(15, 23, 42, 0.08);
  --icon-surface-tint: rgba(255, 255, 255, 0.78);
  --icon-surface-shadow: none;

  /* Agent tinting (color-mix opacity stops; ref §agent-tinted below) */
  --agent-tint-bg-opacity: 8%;
  --agent-tint-border-opacity: 30%;

  /* Radius */
  --radius-control: 6px;
  --radius-surface: 12px;
  --radius-pill: 9999px;

  /* Density (Comfortable = default) */
  --density-control-py: 0.5rem;
  --density-card-p: 1.25rem;
  --density-row-py: 0.75rem;
}

.density-compact {
  --density-control-py: 0.375rem;
  --density-card-p: 1rem;
  --density-row-py: 0.5rem;
}

.dark {
  --bg: 10 10 11;
  --surface: 23 23 26;
  --surface-hover: 32 32 36;
  --border: 42 42 48;
  --fg: 244 244 245;
  --fg-secondary: 161 161 170;
  --fg-muted: 112 112 122;
  --accent: 124 90 232;
  --accent-hover: 145 121 240;
  --accent-fg: 255 255 255;
  --danger: 239 90 90;
  --warning: 245 158 11;
  --success: 52 199 123;

  --icon-surface-border: rgba(255, 255, 255, 0.08);
  --icon-surface-tint: rgba(255, 255, 255, 0.05);
  --icon-surface-shadow: none;

  --agent-tint-bg-opacity: 14%;
  --agent-tint-border-opacity: 40%;
}
```

주의: 기존 `--sidebar-width: 16rem` → `13rem`, `--sidebar-collapsed-width: 4rem` → `4.5rem`(레일 폭과 통일). `--icon-surface-shadow`는 v2 무그림자 원칙에 따라 양 테마 `none`.

- [ ] **Step 2: body·app-shell의 radial-gradient 장식 제거**

v2 §4 "glow/gradient 장식 금지". `index.css` body(96~102행)와 `.app-shell`(151~156행)의 배경을 플랫하게:

```css
  body {
    @apply bg-bg text-fg font-sans;
    transition: background-color var(--transition-speed) ease-out, color var(--transition-speed) ease-out;
  }
```

```css
  .app-shell {
    @apply flex h-screen flex-col bg-bg text-fg;
  }
```

- [ ] **Step 3: 다크 판정 로직 반전**

`MermaidRenderer.tsx` 184행과 195행:

```ts
// before (2곳)
const isDark = !document.documentElement.classList.contains('light');
// after (2곳)
const isDark = document.documentElement.classList.contains('dark');
```

- [ ] **Step 4: 잔여 `light` 클래스 판정 검색**

```bash
grep -rn "contains('light')\|contains(\"light\")" sasoo/frontend/src/
```
Expected: 0건. 발견 시 같은 방식(`contains('dark')`)으로 반전.

```bash
grep -rn "classList" sasoo/frontend/src/App.tsx
```
Expected: `applyTheme`이 `light`/`dark` 클래스를 모두 add/remove하므로 수정 불필요 — `.light` 클래스가 붙어도 이제 no-op임을 확인만 한다. (`App.tsx:74`의 기본값은 이미 `cached || 'light'`.)

- [ ] **Step 5: 빌드 검증**

```bash
cd sasoo/frontend && pnpm build
```
Expected: 성공 (tsc + vite 모두 에러 0)

- [ ] **Step 6: Commit**

```bash
git add sasoo/frontend/src/index.css sasoo/frontend/src/components/MermaidRenderer.tsx
git commit -m "feat(design): 디자인 시스템 v2 토큰 — 라이트 기본 플립, 퍼플 액센트"
```

---

### Task 2: AppSidebar 신설 — 라벨 사이드바 (접이식)

**Files:**
- Create: `sasoo/frontend/src/components/layout/AppSidebar.tsx`
- Modify: `sasoo/frontend/src/App.tsx` (레일 → AppSidebar, NAV_ITEMS 이동·삭제)
- Modify: `sasoo/frontend/src/index.css` (`.app-desktop-rail` 계열 → `.app-sidebar` 계열 교체, 158~195행)
- Modify: `sasoo/frontend/src/lib/strings.ts` (`app.home` 라벨 추가)

**Interfaces:**
- Consumes: Task 1의 토큰. 기존 `S.app.*` 문자열, `AppIcon`, `NavLink`.
- Produces: `<AppSidebar />` (props 없음, 접힘 상태는 내부에서 localStorage `sasoo-sidebar-collapsed`로 관리). 홈 라우트는 아직 Upload가 담당(라우트 교체는 Task 4).

- [ ] **Step 1: strings.ts에 홈 라벨 추가**

`src/lib/strings.ts`의 `app` 객체에 추가 (기존 키 유지):

```ts
  app: {
    name: 'Sasoo',
    subtitle: 'Research archive',
    home: '홈',
    upload: '아카이브 시작',
    // ... 기존 키 그대로
```

- [ ] **Step 2: AppSidebar 컴포넌트 작성**

`src/components/layout/AppSidebar.tsx`:

```tsx
import { useState, useCallback } from 'react';
import { NavLink } from 'react-router-dom';
import { S } from '@/lib/strings';
import logoImg from '@/assets/logo.png';
import { AppIcon, type AppIconName } from '@/components/icons';

const COLLAPSE_KEY = 'sasoo-sidebar-collapsed';

interface NavItem {
  to: string;
  icon: AppIconName;
  label: string;
  exact: boolean;
}

const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: '작업',
    items: [
      { to: '/', icon: 'upload', label: S.app.home, exact: true },
      { to: '/library', icon: 'library', label: S.app.library, exact: false },
    ],
  },
  {
    title: '관리',
    items: [
      { to: '/agents', icon: 'agents', label: S.app.agents, exact: false },
      { to: '/settings', icon: 'settings', label: S.app.settings, exact: false },
    ],
  },
];

export default function AppSidebar() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === 'true'
  );

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      localStorage.setItem(COLLAPSE_KEY, String(!prev));
      return !prev;
    });
  }, []);

  return (
    <aside
      className={`app-sidebar ${collapsed ? 'app-sidebar-collapsed' : ''}`}
      aria-label={S.app.name}
    >
      <div className="app-sidebar-brand">
        <img src={logoImg} alt="Sasoo" className="h-8 w-8 rounded-xl shrink-0" />
        {!collapsed && <span className="app-sidebar-brand-name">{S.app.name}</span>}
      </div>

      <nav className="app-sidebar-nav" aria-label="기본 내비게이션">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="app-sidebar-section">
            {!collapsed && <div className="app-sidebar-section-title">{section.title}</div>}
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  `app-sidebar-link ${isActive ? 'app-sidebar-link-active' : ''}`
                }
                title={item.label}
                aria-label={item.label}
              >
                <AppIcon name={item.icon} className="h-4 w-4 shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <button
        type="button"
        onClick={toggle}
        className="app-sidebar-collapse-btn"
        title={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
        aria-label={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
      >
        <AppIcon
          name="chevron-left"
          className={`h-4 w-4 transition-transform duration-150 ${collapsed ? 'rotate-180' : ''}`}
        />
      </button>
    </aside>
  );
}
```

주의: `AppIcon`에 `chevron-left`가 없으면 `src/components/icons`의 실제 아이콘 이름을 확인해 좌우 화살표 계열(`arrow-left` 등)로 대체한다.

- [ ] **Step 3: index.css의 레일 CSS를 사이드바 CSS로 교체**

`.app-desktop-rail`, `.app-rail-brand`, `.app-desktop-nav`, `.app-nav-link*` (158~195행)를 삭제하고 아래로 교체. 활성 상태는 gradient 대신 플랫 `accent/10` (v2 §4):

```css
  .app-sidebar {
    width: var(--sidebar-width);
    @apply flex shrink-0 flex-col border-r border-border bg-surface px-3 py-4 transition-[width] duration-150;
  }

  .app-sidebar-collapsed {
    width: var(--sidebar-collapsed-width);
    @apply items-center px-2;
  }

  .app-sidebar-brand {
    @apply flex items-center gap-2.5 px-2 pb-4;
  }

  .app-sidebar-collapsed .app-sidebar-brand {
    @apply justify-center px-0;
  }

  .app-sidebar-brand-name {
    @apply text-sm font-semibold tracking-tight text-fg;
  }

  .app-sidebar-nav {
    @apply flex flex-1 flex-col gap-5 overflow-y-auto;
  }

  .app-sidebar-section {
    @apply flex flex-col gap-0.5;
  }

  .app-sidebar-collapsed .app-sidebar-section {
    @apply items-center;
  }

  .app-sidebar-section-title {
    @apply px-2 pb-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted;
  }

  .app-sidebar-link {
    @apply flex w-full items-center gap-2.5 rounded-control px-2 py-1.5 text-sm text-fg-secondary transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface;
  }

  .app-sidebar-collapsed .app-sidebar-link {
    @apply h-10 w-10 justify-center gap-0 px-0 py-0;
  }

  .app-sidebar-link:hover {
    @apply bg-surface-hover text-fg;
  }

  .app-sidebar-link-active {
    @apply bg-accent/10 text-accent;
  }

  .app-sidebar-collapse-btn {
    @apply mt-2 flex h-8 w-8 items-center justify-center self-end rounded-control text-fg-muted transition-colors duration-150 hover:bg-surface-hover hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface;
  }

  .app-sidebar-collapsed .app-sidebar-collapse-btn {
    @apply self-center;
  }
```

주의: Tailwind config에 `rounded-control`이 없으면 `borderRadius` 매핑(`control: var(--radius-control)`)을 확인하고, 없을 경우 `rounded-[var(--radius-control)]`로 대체.

- [ ] **Step 4: App.tsx에서 레일을 AppSidebar로 교체**

`App.tsx`에서 `NAV_ITEMS` 상수(29~34행)를 삭제하고, aside 블록(121~143행)을 교체:

```tsx
import AppSidebar from '@/components/layout/AppSidebar';
// ...
{!isWorkbench && <AppSidebar />}
```

`AppIcon`/`logoImg` import가 App.tsx의 다른 곳에서 안 쓰이면 함께 제거(`RouteFallback`이 `AppIcon`을 쓰므로 확인 후 판단).

- [ ] **Step 5: 빌드 검증**

```bash
cd sasoo/frontend && pnpm build
```
Expected: 성공. `pnpm lint`도 통과(unused import 없음).

- [ ] **Step 6: Commit**

```bash
git add sasoo/frontend/src/components/layout/AppSidebar.tsx sasoo/frontend/src/App.tsx sasoo/frontend/src/index.css sasoo/frontend/src/lib/strings.ts
git commit -m "feat(ui): 라벨 사이드바 AppSidebar — 섹션 그룹핑, 접이식(localStorage)"
```

---

### Task 3: 업로드 로직 컴포넌트 추출 (Home 준비)

**Files:**
- Create: `sasoo/frontend/src/components/home/UploadPanel.tsx`
- Create: `sasoo/frontend/src/components/home/RecentPaperRow.tsx`
- Modify: `sasoo/frontend/src/pages/Upload.tsx` (추출한 컴포넌트를 소비하도록 축소)

**Interfaces:**
- Consumes: 기존 `@/lib/api`(uploadPaper, updatePaper, getSettings), `@/lib/agents`, `useToast`, `Select`, `AppIcon`
- Produces:
  - `UploadPanel(): JSX.Element` — props 없음. 파일 선택→업로드→분류→워크벤치 이동의 전체 플로우를 자체 상태로 처리 (내부에서 `useNavigate`, `useToast` 사용)
  - `RecentPaperRow({ paper: Paper; metaLabel: string; metaValue: string; onOpen: (id: string) => void }): JSX.Element`
  - 유틸 export: `formatPaperDate(dateStr: string | null): string` (RecentPaperRow.tsx에서 export — Home이 재사용)

- [ ] **Step 1: RecentPaperRow.tsx 추출**

`Upload.tsx`의 `RecentPaperRow`(67~118행)와 그 의존 함수 `formatPaperDate`(30~37행), `paperStatusLabel`(39~51행), `paperStatusClass`(53~65행)를 `src/components/home/RecentPaperRow.tsx`로 **이동**(복사 후 원본 삭제). 코드는 그대로, import만 정리:

```tsx
import type { Paper } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';

export function formatPaperDate(dateStr: string | null): string { /* Upload.tsx 30~37행 그대로 */ }
function paperStatusLabel(status: Paper['status']): string { /* 39~51행 그대로 */ }
function paperStatusClass(status: Paper['status']): string { /* 53~65행 그대로 */ }

export default function RecentPaperRow({ paper, metaLabel, metaValue, onOpen }: {
  paper: Paper;
  metaLabel: string;
  metaValue: string;
  onOpen: (id: string) => void;
}) { /* 80~117행 JSX 그대로 */ }
```

- [ ] **Step 2: UploadPanel.tsx 추출**

`Upload.tsx`의 업로드 상태·핸들러 전부(120~290행: `UploadStage`, `stage/selectedFile/uploadProgress/uploadResult/domainOverride/error/isDragging` 상태, `validateFile/handleFileSelect/handleUpload/handleStartAnalysis/handleDrag*/handleDrop/clearFile` 핸들러)와 왼쪽 드롭존 `<section>` JSX(351~549행), 상수 `MAX_FILE_SIZE/ACCEPTED_TYPES`(21~22행), `formatFileSize`(24~28행)를 `src/components/home/UploadPanel.tsx`로 이동. 컴포넌트 시그니처:

```tsx
export default function UploadPanel() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  // Upload.tsx의 업로드 관련 상태·핸들러 전부 (recentAnalyses/recentLibrary/settingsSnapshot/systemReady 제외)
  return (
    <section /* Upload.tsx 351~549행의 드롭존 섹션 JSX 그대로 */ />
  );
}
```

주의: `recentAnalyses/recentLibrary/settingsSnapshot/systemReady` 상태와 관련 useEffect는 UploadPanel로 옮기지 않는다 (페이지 소유).

- [ ] **Step 3: Upload.tsx를 소비자로 축소**

`Upload.tsx`는 헤더(시스템 상태), `<UploadPanel />`, 우측 최근 목록(`RecentPaperRow` import 사용)만 남긴다. 동작 변화 없음.

- [ ] **Step 4: 빌드 검증**

```bash
cd sasoo/frontend && pnpm build && pnpm lint
```
Expected: 성공

- [ ] **Step 5: Commit**

```bash
git add sasoo/frontend/src/components/home/ sasoo/frontend/src/pages/Upload.tsx
git commit -m "refactor(ui): 업로드 패널·최근 논문 행을 재사용 컴포넌트로 추출"
```

---

### Task 4: Home 페이지 신설, 라우트 교체, Upload 삭제

**Files:**
- Create: `sasoo/frontend/src/pages/Home.tsx`
- Modify: `sasoo/frontend/src/App.tsx` (라우트 `/` → Home)
- Modify: `sasoo/frontend/src/lib/strings.ts` (`home` 섹션 추가)
- Delete: `sasoo/frontend/src/pages/Upload.tsx`

**Interfaces:**
- Consumes: Task 3의 `UploadPanel`, `RecentPaperRow`, `formatPaperDate`; `getPapers`, `getCostSummary` (`@/lib/api`) — `CostSummary.current_month: { month: string; cost_usd: number; ... }`
- Produces: `/` 라우트의 Home 페이지. Upload.tsx 완전 삭제.

- [ ] **Step 1: strings.ts에 home 섹션 추가**

```ts
  home: {
    greeting: '안녕하세요',
    subGreeting: '오늘 분석할 논문을 올려주세요.',
    quickActions: '바로가기',
    actionAgents: '에이전트 편성',
    actionAgentsDesc: '분석 에이전트를 관리합니다',
    actionLibrary: '연구 보관함',
    actionLibraryDesc: '보관된 논문을 둘러봅니다',
    recentAnalyses: '최근 분석',
    recentLibrary: '최근 추가',
    recentEmpty: '아직 논문이 없습니다. 위에서 첫 논문을 올려보세요.',
    costTitle: '이번 달 비용',
    costOpenSettings: '자세히 보기',
  },
```

- [ ] **Step 2: Home.tsx 작성**

```tsx
import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPapers, getCostSummary, type Paper } from '@/lib/api';
import { S } from '@/lib/strings';
import { AppIcon, type AppIconName } from '@/components/icons';
import UploadPanel from '@/components/home/UploadPanel';
import RecentPaperRow, { formatPaperDate } from '@/components/home/RecentPaperRow';

const QUICK_ACTIONS: { to: string; icon: AppIconName; title: string; desc: string }[] = [
  { to: '/agents', icon: 'agents', title: S.home.actionAgents, desc: S.home.actionAgentsDesc },
  { to: '/library', icon: 'library', title: S.home.actionLibrary, desc: S.home.actionLibraryDesc },
];

function todayLabel(): string {
  return new Date().toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
}

export default function Home() {
  const navigate = useNavigate();
  const [recentAnalyses, setRecentAnalyses] = useState<Paper[]>([]);
  const [recentLibrary, setRecentLibrary] = useState<Paper[]>([]);
  const [monthCost, setMonthCost] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      getPapers({ page: 1, page_size: 4, sort_by: 'analyzed_at', sort_order: 'desc' }),
      getPapers({ page: 1, page_size: 4, sort_by: 'created_at', sort_order: 'desc' }),
    ])
      .then(([analysisResponse, libraryResponse]) => {
        if (cancelled) return;
        setRecentAnalyses(analysisResponse.papers.filter((p) => p.analyzed_at).slice(0, 4));
        setRecentLibrary(libraryResponse.papers.slice(0, 4));
      })
      .catch(() => {
        if (cancelled) return;
        setRecentAnalyses([]);
        setRecentLibrary([]);
      });

    getCostSummary()
      .then((data) => {
        if (!cancelled) setMonthCost(data.current_month?.cost_usd ?? 0);
      })
      .catch(() => {
        if (!cancelled) setMonthCost(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleOpenRecent = useCallback(
    (id: string) => navigate(`/workbench/${id}`),
    [navigate]
  );

  return (
    <div className="page-container-compact">
      <section className="mb-6">
        <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
          {todayLabel()}
        </div>
        <h1 className="mt-1.5 text-[1.45rem] font-semibold tracking-[-0.03em] text-fg">
          {S.home.greeting}
        </h1>
        <p className="mt-1 text-sm text-fg-muted">{S.home.subGreeting}</p>
      </section>

      <UploadPanel />

      <section className="mt-6">
        <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
          {S.home.quickActions}
        </div>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {QUICK_ACTIONS.map((action) => (
            <Link key={action.to} to={action.to} className="card-hover flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control border border-border bg-bg">
                <AppIcon name={action.icon} className="h-4 w-4 text-fg-secondary" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-fg">{action.title}</span>
                <span className="mt-0.5 block truncate text-sm text-fg-muted">{action.desc}</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-6 grid gap-4 xl:grid-cols-2">
        <div className="card">
          <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
            {S.home.recentAnalyses}
          </div>
          <div className="mt-3 grid gap-3">
            {recentAnalyses.length > 0 ? (
              recentAnalyses.map((paper) => (
                <RecentPaperRow
                  key={`recent-analysis-${paper.id}`}
                  paper={paper}
                  metaLabel={S.upload.lastAnalyzed}
                  metaValue={formatPaperDate(paper.analyzed_at)}
                  onOpen={handleOpenRecent}
                />
              ))
            ) : (
              <p className="py-4 text-sm leading-6 text-fg-muted">{S.home.recentEmpty}</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
            {S.home.recentLibrary}
          </div>
          <div className="mt-3 grid gap-3">
            {recentLibrary.length > 0 ? (
              recentLibrary.map((paper) => (
                <RecentPaperRow
                  key={`recent-library-${paper.id}`}
                  paper={paper}
                  metaLabel={S.upload.addedLabel}
                  metaValue={formatPaperDate(paper.created_at)}
                  onOpen={handleOpenRecent}
                />
              ))
            ) : (
              <p className="py-4 text-sm leading-6 text-fg-muted">{S.home.recentEmpty}</p>
            )}
          </div>
        </div>
      </section>

      {monthCost !== null && (
        <section className="mt-4 card flex items-center justify-between gap-4">
          <div>
            <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
              {S.home.costTitle}
            </div>
            <div className="mt-1.5 font-mono text-lg text-fg">${monthCost.toFixed(2)}</div>
          </div>
          <Link
            to="/settings"
            className="shrink-0 text-sm text-accent transition-colors hover:text-accent-hover"
          >
            {S.home.costOpenSettings}
          </Link>
        </section>
      )}
    </div>
  );
}
```

주의: `S.upload.lastAnalyzed`/`S.upload.addedLabel`은 기존 키 재사용. `card`/`card-hover`는 기존 index.css 컴포넌트 클래스.

- [ ] **Step 3: App.tsx 라우트 교체 + Upload 삭제**

```tsx
// before
const UploadPage = lazy(() => import('@/pages/Upload'));
// after
const HomePage = lazy(() => import('@/pages/Home'));
```

```tsx
// before
<Route path="/" element={<PageScaffold variant="archive"><UploadPage /></PageScaffold>} />
// after
<Route path="/" element={<PageScaffold variant="archive"><HomePage /></PageScaffold>} />
```

```bash
rm sasoo/frontend/src/pages/Upload.tsx
grep -rn "pages/Upload" sasoo/frontend/src/
```
Expected: grep 0건

- [ ] **Step 4: 빌드 검증**

```bash
cd sasoo/frontend && pnpm build && pnpm lint
```
Expected: 성공

- [ ] **Step 5: Commit**

```bash
git add -A sasoo/frontend/src/
git commit -m "feat(ui): 홈 허브 신설 — 인사말·업로드·퀵액션·최근 논문·비용 스냅숏 (Upload 페이지 흡수)"
```

---

### Task 5: v2 마감 — label-caps 통일, mono 실사용, 잔여 장식 정리

**Files:**
- Modify: `sasoo/frontend/src/index.css` (잔여 gradient/glow 검색·정리)
- Modify: 해당되는 컴포넌트 (검색 결과에 따름)

**Interfaces:**
- Consumes: Task 1~4 결과
- Produces: v2 §4(무그림자·무gradient)·§2(mono 실사용) 마감 상태

- [ ] **Step 1: 잔여 gradient/glow/blur 장식 검색**

```bash
grep -n "radial-gradient\|linear-gradient\|backdrop-blur\|shadow-\[" sasoo/frontend/src/index.css
```

각 히트를 분류: **모달·팝오버·드롭다운·토스트·드래그 오버레이**의 그림자는 유지, **카드·리스트·버튼·배지·레일 잔재**의 gradient/glow/inset-shadow는 플랫(단색 토큰)으로 교체. 판단 기준은 v2 스펙 §4 — "같은 평면 내 구획은 보더, 떠 있는 계층만 그림자".

- [ ] **Step 2: btn-primary를 무채색으로 재정의 (v2 §6)**

`index.css:309-311`의 `.btn-primary`를 액센트에서 무채색으로 교체 (v2 §6: "범용 CTA는 무채색, 액센트는 작업 결과에"):

```css
  .btn-primary {
    @apply btn bg-fg text-bg font-semibold hover:bg-fg/85;
  }
```

라이트에서 검정 버튼 + 흰 텍스트, 다크에서 흰 버튼 + 검정 텍스트가 된다. `bg-accent`를 직접 쓰는 버튼이 남아 있으면 검토: 진행바·활성 상태·Citation Chip의 accent는 유지(그게 accent의 역할), 범용 CTA만 btn-primary로.

- [ ] **Step 3: 논문 ID·DOI·메타데이터에 font-mono 적용**

```bash
grep -rn "doi\|DOI\|paper_id\|paper\.id" sasoo/frontend/src/components/workbench/ sasoo/frontend/src/pages/Library.tsx | grep -i "tsx:" | head -20
```

화면에 논문 ID·DOI·기술 식별자를 렌더링하는 곳에 `font-mono text-xs` 계열 클래스를 적용한다 (본문·제목에는 적용 금지). 히트가 없으면 이 스텝은 변경 없이 통과.

- [ ] **Step 4: 빌드 검증**

```bash
cd sasoo/frontend && pnpm build
```
Expected: 성공

- [ ] **Step 5: Commit**

```bash
git add -A sasoo/frontend/src/
git commit -m "polish(ui): v2 마감 — btn-primary 무채색화, 잔여 gradient 정리, 메타데이터 mono 적용"
```

---

### Task 6: 시각 QA — 2테마 × 5라우트 + compact

**Files:**
- 없음 (검증 전용; 발견된 결함은 이 태스크에서 수정 후 커밋)

**Interfaces:**
- Consumes: Task 1~5 전체

- [ ] **Step 1: 앱 실행**

launch-sim 스킬(프로젝트 실행 스킬)을 사용해 GUI를 올바른 브랜치에서 실행하고 라이브 확인한다. 실패 시 `cd sasoo/frontend && pnpm dev`로 대체.

- [ ] **Step 2: 라이트(기본) 테마 스크린샷 순회**

`/` (홈), `/library`, `/agents`, `/settings`, `/workbench/:id`(기존 논문 하나 열기) 5개 라우트 스크린샷. 체크리스트:
- 홈: 인사말·드롭존·퀵액션 카드·최근 논문·비용 스냅숏 렌더, 카드가 흰색 surface + 1px 보더 + 무그림자
- 사이드바: 라벨 표시, 섹션 헤더(작업/관리), 활성 항목 퍼플 하이라이트, 접기→4.5rem 아이콘 모드→새로고침 후 유지(localStorage)
- 업로드 동선: PDF 드래그앤드롭 → 업로드 → 분류 → 워크벤치 이동
- muted 텍스트가 읽히는지 (fg-muted 4.8:1 수정 확인)
- 입력 필드가 보더만으로 식별되는지 (스펙 §8 미해결 항목 — 문제 시 배경 차이 강화)

- [ ] **Step 3: 다크 테마 순회**

설정에서 다크 전환 후 동일 5개 라우트 확인. 체크리스트:
- 퍼플 액센트 버튼(흰 텍스트) 렌더, Mermaid 다이어그램이 다크 테마로 렌더(MermaidRenderer 반전 검증)
- Workbench: PDF 툴바, resize handle, 채팅 버블, 분석 상태 행 회귀 없음

- [ ] **Step 4: density compact 확인**

설정에서 compact 전환 후 홈·Library 확인 (카드 패딩 축소 정상).

- [ ] **Step 5: 결함 수정 및 커밋**

발견된 결함을 수정하고 스크린샷 재확인 후:

```bash
git add -A sasoo/frontend/src/
git commit -m "fix(ui): v2 시각 QA 수정"
```

- [ ] **Step 6: 토큰 명세 문서 동기화**

`sasoo/docs/04-design/design-tokens.md`의 토큰 값 표를 v2 값(라이트 기본)으로 갱신하고 커밋:

```bash
git add sasoo/docs/04-design/design-tokens.md
git commit -m "docs(design): design-tokens.md를 v2 값으로 동기화"
```
