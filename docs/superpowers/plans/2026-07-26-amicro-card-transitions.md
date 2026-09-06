# Amicro 카드 트랜지션 3종 적용 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amicro(MIT, github.com/Subhan-code/Amicro--Micro-transitions-) 쇼케이스의 카드 트랜지션 3종을 sasoo 프런트엔드에 이식한다 — ① FigureGallery에 CoverFlow 뷰 토글, ② Home 라이브러리 타일에 ARC 카드 팬, ③ RecipeCard 섹션 캐스케이드 등장 애니메이션.

**Architecture:** Amicro 카드 컴포넌트는 CLI 레지스트리에 없어(레지스트리는 로더류 162종뿐) 쇼케이스 소스 `src/components/cards/*.tsx`(MIT)를 수동 이식한다. `frontend/src/components/amicro/` 아래에 sasoo 디자인 토큰(`bg-surface`, `text-fg`, `border-border` 등)으로 재작성해 넣고, 기존 화면은 대체가 아니라 **추가**(뷰 토글·장식 요소·entrance 래퍼)로 통합한다. 애니메이션은 `motion`(구 framer-motion) 스프링 사용, `useReducedMotion`으로 접근성 대응.

**Tech Stack:** React 19.2, Tailwind 3.4, motion(`motion/react`), lucide-react(기설치), vitest(순수 함수만 — 컴포넌트 테스트 인프라 없음, 코드베이스 관례).

## Global Constraints

- 원본 출처 표기: 각 이식 파일 상단에 `// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-` 주석.
- 기존 기능 보존: FigureGallery 그리드·라이트박스·배지, Home 타일 링크, RecipeCard 섹션 내용 일체 무수정. 새 UI는 추가만.
- 색상 하드코딩 금지: zinc/neutral 원본 클래스는 sasoo 토큰(`bg-surface`, `bg-surface-hover`, `text-fg`, `text-fg-muted`, `border-border`, `text-accent`)으로 치환. 다크/라이트 모두 동작해야 함.
- `prefers-reduced-motion` 사용자는 트랜스폼 애니메이션 비활성(즉시 최종 상태).
- 사용자 문구는 `frontend/src/lib/strings.ts`의 `S` 객체 경유(기존 관례).
- 커밋은 feature 브랜치 `feat/amicro-card-transitions`에서. main 직접 커밋 금지.
- pnpm 사용(`sasoo/frontend`에서 `pnpm add motion`). npm/bun 금지.

---

### Task 0: 브랜치 + motion 의존성

**Files:**
- Modify: `sasoo/frontend/package.json` (pnpm이 수정)

- [ ] **Step 1: 브랜치 생성**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git checkout -b feat/amicro-card-transitions
```

- [ ] **Step 2: motion 설치**

```bash
cd sasoo/frontend && pnpm add motion
```

- [ ] **Step 3: 빌드 확인**

Run: `cd sasoo/frontend && pnpm build`
Expected: 성공 (기존 상태 회귀 없음 확인)

- [ ] **Step 4: Commit**

```bash
git add sasoo/frontend/package.json sasoo/pnpm-lock.yaml
git commit -m "chore(frontend): motion 의존성 추가 (Amicro 카드 트랜지션용)"
```

### Task 1: CoverFlow 컴포넌트 + 순수 변환 함수

**Files:**
- Create: `sasoo/frontend/src/lib/coverflow.ts`
- Create: `sasoo/frontend/src/lib/coverflow.test.ts`
- Create: `sasoo/frontend/src/components/amicro/CoverFlow.tsx`

**Interfaces:**
- Produces: `coverFlowTransform(offset: number): { x: number; rotateY: number; z: number; scale: number; opacity: number }`
- Produces: `<CoverFlow items={{src,title}[]} activeIndex={number} onActiveChange={(i)=>void} onOpen={(i)=>void} />` — Task 2가 사용.

- [ ] **Step 1: 실패하는 테스트 작성** (`src/lib/coverflow.test.ts`)

```ts
import { describe, expect, it } from 'vitest';
import { coverFlowTransform } from './coverflow';

describe('coverFlowTransform', () => {
  it('활성 카드(offset 0)는 정면·확대·불투명', () => {
    expect(coverFlowTransform(0)).toEqual({ x: 0, rotateY: 0, z: 50, scale: 1.1, opacity: 1 });
  });
  it('왼쪽 카드(offset -1)는 +38도 회전, 뒤로 밀림', () => {
    const t = coverFlowTransform(-1);
    expect(t.rotateY).toBe(38);
    expect(t.x).toBe(-56);
    expect(t.z).toBe(-50);
    expect(t.scale).toBeCloseTo(0.92);
    expect(t.opacity).toBeCloseTo(0.75);
  });
  it('오른쪽 카드(offset 2)는 -38도 회전, 더 흐림', () => {
    const t = coverFlowTransform(2);
    expect(t.rotateY).toBe(-38);
    expect(t.opacity).toBeCloseTo(0.5);
  });
  it('3칸 이상 떨어지면 투명', () => {
    expect(coverFlowTransform(3).opacity).toBe(0);
    expect(coverFlowTransform(-4).opacity).toBe(0);
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd sasoo/frontend && pnpm test -- coverflow`
Expected: FAIL — `coverflow.ts` 없음

- [ ] **Step 3: 구현** (`src/lib/coverflow.ts`)

```ts
// CoverFlow 카드의 3D 배치 계산. offset = 카드 인덱스 - 활성 인덱스.
// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
export interface CoverFlowTransform {
  x: number;
  rotateY: number;
  z: number;
  scale: number;
  opacity: number;
}

const CARD_GAP_PX = 56;

export function coverFlowTransform(offset: number): CoverFlowTransform {
  const abs = Math.abs(offset);
  if (offset === 0) {
    return { x: 0, rotateY: 0, z: 50, scale: 1.1, opacity: 1 };
  }
  return {
    x: offset * CARD_GAP_PX,
    rotateY: offset < 0 ? 38 : -38,
    z: -abs * 50,
    scale: 1 - abs * 0.08,
    opacity: abs > 2 ? 0 : 1 - abs * 0.25,
  };
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd sasoo/frontend && pnpm test -- coverflow`
Expected: PASS 4건

- [ ] **Step 5: CoverFlow 컴포넌트 작성** (`src/components/amicro/CoverFlow.tsx`)

```tsx
// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardCoverFlow를 sasoo 토큰·제어형 activeIndex로 재작성.
import { motion, useReducedMotion } from 'motion/react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { coverFlowTransform } from '@/lib/coverflow';

export interface CoverFlowItem {
  src: string;
  title: string;
}

interface CoverFlowProps {
  items: CoverFlowItem[];
  activeIndex: number;
  onActiveChange: (index: number) => void;
  // 활성 카드를 다시 클릭했을 때 (라이트박스 열기 등)
  onOpen?: (index: number) => void;
}

export default function CoverFlow({ items, activeIndex, onActiveChange, onOpen }: CoverFlowProps) {
  const reduceMotion = useReducedMotion();

  const toPrev = () => onActiveChange(Math.max(0, activeIndex - 1));
  const toNext = () => onActiveChange(Math.min(items.length - 1, activeIndex + 1));

  return (
    <div
      className="flex w-full select-none flex-col items-center justify-center overflow-hidden rounded-xl border border-border bg-surface py-6"
      style={{ perspective: '1000px' }}
    >
      <div className="relative flex h-[190px] w-full items-center justify-center [transform-style:preserve-3d]">
        {items.map((item, i) => {
          const t = coverFlowTransform(i - activeIndex);
          const isActive = i === activeIndex;
          return (
            <motion.div
              key={`${item.src}-${i}`}
              className="absolute aspect-[4/3] w-[180px] cursor-pointer"
              initial={false}
              animate={{ x: t.x * 2.2, rotateY: t.rotateY, z: t.z, scale: t.scale, opacity: t.opacity }}
              transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 200, damping: 25 }}
              style={{ zIndex: 100 - Math.abs(i - activeIndex) }}
              onClick={() => (isActive ? onOpen?.(i) : onActiveChange(i))}
            >
              <img
                src={item.src}
                alt={item.title}
                className="h-full w-full rounded-lg border border-border bg-surface-raised object-contain shadow-lg"
                draggable={false}
              />
              <motion.div
                className="absolute -bottom-6 left-[-30px] right-[-30px] overflow-hidden text-ellipsis whitespace-nowrap text-center text-2xs font-medium text-fg-muted"
                animate={{ opacity: isActive ? 1 : 0, y: isActive ? 0 : -5 }}
                transition={reduceMotion ? { duration: 0 } : undefined}
              >
                {item.title}
              </motion.div>
            </motion.div>
          );
        })}
      </div>

      <div className="z-20 mt-7 flex w-fit items-center justify-center gap-2 rounded-full border border-border bg-surface-hover/60 px-1.5 py-0.5 shadow-sm backdrop-blur-md">
        <button
          type="button"
          onClick={toPrev}
          disabled={activeIndex === 0}
          className="rounded-full p-1 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <div className="flex items-center justify-center gap-1">
          {items.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onActiveChange(i)}
              className={`h-1 cursor-pointer rounded-full transition-all duration-300 ${
                activeIndex === i ? 'w-4 bg-accent' : 'w-1 bg-fg-muted/40 hover:bg-fg-muted/70'
              }`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={toNext}
          disabled={activeIndex === items.length - 1}
          className="rounded-full p-1 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
```

주의: `bg-surface-raised`가 프로젝트 토큰에 없으면 `bg-surface-hover`로 대체(구현 시 `tailwind.config`/`index.css`에서 실제 토큰 확인).

- [ ] **Step 6: 빌드/린트 확인**

Run: `cd sasoo/frontend && pnpm build && pnpm lint`
Expected: PASS (미사용 export 경고가 나면 Task 2에서 사용 예정이므로 이 시점 커밋은 컴포넌트+lib만)

- [ ] **Step 7: Commit**

```bash
git add sasoo/frontend/src/lib/coverflow.ts sasoo/frontend/src/lib/coverflow.test.ts sasoo/frontend/src/components/amicro/CoverFlow.tsx
git commit -m "feat(frontend): Amicro CoverFlow 컴포넌트 이식 (MIT)"
```

### Task 2: FigureGallery에 CoverFlow 뷰 토글

**Files:**
- Modify: `sasoo/frontend/src/components/FigureGallery.tsx:759-799` (본문 return 블록)
- Modify: `sasoo/frontend/src/lib/strings.ts` (figures 섹션에 뷰 토글 문구)

**Interfaces:**
- Consumes: Task 1의 `CoverFlow`, `CoverFlowItem`.
- 기존 `openLightbox(index)`·`getFigureImageUrl(figure)`·`figureCards` 배열을 그대로 사용.

- [ ] **Step 1: strings.ts에 문구 추가**

`S.figures`에 다음 키 추가(기존 키 형식 그대로):

```ts
viewGrid: '그리드',
viewCoverflow: '커버플로우',
```

- [ ] **Step 2: FigureGallery 통합**

`FigureGallery` 본문(759행 return 앞)에 상태 추가:

```tsx
const [viewMode, setViewMode] = useState<'grid' | 'coverflow'>('grid');
const [coverflowIndex, setCoverflowIndex] = useState(0);
```

헤더 `<h3>` 오른쪽에 토글 버튼(제목 줄을 `flex items-center justify-between`으로 감싸고, 기존 h3 무수정 유지):

```tsx
<div className="mb-3 flex items-center justify-between">
  {/* 기존 h3 (mb-3만 제거) */}
  <div className="flex items-center gap-1 rounded-lg border border-border p-0.5">
    <button
      type="button"
      onClick={() => setViewMode('grid')}
      className={`rounded-md px-2 py-1 text-2xs transition-colors ${viewMode === 'grid' ? 'bg-surface-hover text-fg' : 'text-fg-muted hover:text-fg'}`}
    >
      {S.figures.viewGrid}
    </button>
    <button
      type="button"
      onClick={() => setViewMode('coverflow')}
      className={`rounded-md px-2 py-1 text-2xs transition-colors ${viewMode === 'coverflow' ? 'bg-surface-hover text-fg' : 'text-fg-muted hover:text-fg'}`}
    >
      {S.figures.viewCoverflow}
    </button>
  </div>
</div>
```

그리드 `<div className="grid ...">`를 조건 분기(기존 그리드 코드 무수정 유지):

```tsx
{viewMode === 'coverflow' ? (
  <CoverFlow
    items={figureCards.map(({ figure }) => ({
      src: getFigureImageUrl(figure),
      title: figure.label ?? figure.caption ?? '',
    }))}
    activeIndex={Math.min(coverflowIndex, figureCards.length - 1)}
    onActiveChange={setCoverflowIndex}
    onOpen={(i) => openLightbox(figureCards[i].index)}
  />
) : (
  /* 기존 그리드 div 그대로 */
)}
```

주의: `figure.label`/`figure.caption` 필드명은 구현 시 `lib/api.ts`의 `Figure` 타입에서 실제 이름 확인 후 맞춘다.

- [ ] **Step 3: 빌드/린트/테스트**

Run: `cd sasoo/frontend && pnpm build && pnpm lint && pnpm test`
Expected: 전부 PASS

- [ ] **Step 4: Commit**

```bash
git add sasoo/frontend/src/components/FigureGallery.tsx sasoo/frontend/src/lib/strings.ts
git commit -m "feat(figures): 그림 갤러리 커버플로우 뷰 토글"
```

### Task 3: Home 라이브러리 타일 ARC 카드 팬

**Files:**
- Create: `sasoo/frontend/src/components/amicro/ArcCards.tsx`
- Modify: `sasoo/frontend/src/pages/Home.tsx:164-182` (라이브러리 타일 section)

**Interfaces:**
- Produces: `<ArcCards hovered={boolean} className?={string} />` — 장식용, 데이터 없음.

- [ ] **Step 1: ArcCards 작성** (`src/components/amicro/ArcCards.tsx`)

```tsx
// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardArc5를 sasoo 토큰·장식용 소형 버전으로 재작성. hover 시 5장이 부채꼴로 펼쳐진다.
import { motion, useReducedMotion } from 'motion/react';

interface ArcCardsProps {
  hovered: boolean;
  className?: string;
}

const ANGLE = 30;
const GAP = 44;
const Y_OFFSET = 8;
const CENTER = 2;

export default function ArcCards({ hovered, className = '' }: ArcCardsProps) {
  const reduceMotion = useReducedMotion();
  const active = hovered && !reduceMotion;

  return (
    <div className={`pointer-events-none relative flex h-[4.5rem] w-[3.4rem] items-center justify-center ${className}`}>
      {[0, 1, 2, 3, 4].map((i) => {
        const dist = i - CENTER;
        let y = 0;
        if (active) {
          if (Math.abs(dist) === 2) y = Y_OFFSET;
          else if (Math.abs(dist) === 1) y = -0.2 * Y_OFFSET;
          else y = -Y_OFFSET;
        }
        return (
          <motion.div
            key={i}
            animate={{
              rotate: active ? dist * (ANGLE / CENTER) : 0,
              x: active ? dist * (GAP / CENTER) : 0,
              y,
              scale: active && dist === 0 ? 1.05 : 1,
            }}
            transition={{ type: 'spring', stiffness: 180, damping: 20, mass: 0.8 }}
            style={{ zIndex: 3 - Math.abs(dist), originX: 0.5, originY: 1 }}
            className="absolute inset-0 rounded-lg border border-border bg-surface-hover shadow-[0_4px_10px_-2px_rgba(0,0,0,0.15)]"
          />
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Home 라이브러리 타일에 통합**

`papersTotal !== null` section(164행)에 hover 상태와 ArcCards 추가. 숫자와 카드팬을 한 줄에 배치:

```tsx
// Home() 상단에 상태 추가
const [libraryHovered, setLibraryHovered] = useState(false);
```

```tsx
<section
  className="card"
  onMouseEnter={() => setLibraryHovered(true)}
  onMouseLeave={() => setLibraryHovered(false)}
>
  <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
    {S.home.libraryTitle}
  </div>
  <div className="mt-2 flex items-end justify-between gap-2">
    <div className="text-[1.7rem] font-semibold leading-none tracking-[-0.01em] text-fg tabular-nums">
      {papersTotal}
      <span className="ml-1 text-base font-normal text-fg-muted">{S.home.libraryUnit}</span>
    </div>
    <ArcCards hovered={libraryHovered} />
  </div>
  {/* 기존 Link 그대로 */}
</section>
```

- [ ] **Step 3: 빌드/린트**

Run: `cd sasoo/frontend && pnpm build && pnpm lint`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add sasoo/frontend/src/components/amicro/ArcCards.tsx sasoo/frontend/src/pages/Home.tsx
git commit -m "feat(home): 라이브러리 타일 ARC 카드 팬 hover 연출"
```

### Task 4: RecipeCard 캐스케이드 등장 애니메이션

**Files:**
- Create: `sasoo/frontend/src/components/amicro/CascadeIn.tsx`
- Modify: `sasoo/frontend/src/components/RecipeCard.tsx:178-339` (본문 return 블록)

**Interfaces:**
- Produces: `<CascadeIn index={number}>{children}</CascadeIn>` — index 순서대로 딜레이를 두고 아래에서 스프링 등장.

- [ ] **Step 1: CascadeIn 작성** (`src/components/amicro/CascadeIn.tsx`)

```tsx
// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardCascadeStagger의 스태거 아이디어를 실콘텐츠 entrance 래퍼로 변환.
import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';

interface CascadeInProps {
  index: number;
  children: ReactNode;
}

export default function CascadeIn({ index, children }: CascadeInProps) {
  const reduceMotion = useReducedMotion();
  if (reduceMotion) return <>{children}</>;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 200, damping: 22, mass: 0.9, delay: index * 0.07 }}
    >
      {children}
    </motion.div>
  );
}
```

- [ ] **Step 2: RecipeCard 섹션 래핑**

`RecipeCard`의 return(178행)에서 본문 섹션들을 순서대로 `CascadeIn`으로 감싼다. 헤더(181~203행)는 감싸지 않음(즉시 표시). 섹션 내용은 무수정:

```tsx
{/* Scores */}     → <CascadeIn index={0}>…</CascadeIn>
{/* Objective */}  → <CascadeIn index={1}>…</CascadeIn>
{/* Materials */}  → <CascadeIn index={2}>…</CascadeIn>
{/* Parameters(또는 no-params 경고) */} → <CascadeIn index={3}>…</CascadeIn>
{/* Steps */}      → <CascadeIn index={4}>…</CascadeIn>
{/* Critical Notes */} → <CascadeIn index={5}>…</CascadeIn>
{/* Missing Info */}   → <CascadeIn index={6}>…</CascadeIn>
```

조건부 렌더 블록은 조건은 바깥에 두고 내부만 감싼다: `{materials.length > 0 && (<CascadeIn index={2}>…</CascadeIn>)}`.

- [ ] **Step 3: 빌드/린트/전체 테스트**

Run: `cd sasoo/frontend && pnpm build && pnpm lint && pnpm test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add sasoo/frontend/src/components/amicro/CascadeIn.tsx sasoo/frontend/src/components/RecipeCard.tsx
git commit -m "feat(recipe): 레시피 섹션 캐스케이드 등장 애니메이션"
```

### Task 5: 실행 화면 검증

- [ ] **Step 1: 앱 기동**

Run: `cd sasoo && pnpm dev` (Electron + backend 통합 dev)
Expected: 앱 창 표시

- [ ] **Step 2: 화면별 확인**

1. Home — 라이브러리 타일 hover 시 5장 부채꼴 펼침, 다크/라이트 양쪽.
2. Workbench(분석된 논문) — 그림 갤러리 토글 → 커버플로우 3D 전환, 활성 카드 클릭 → 라이트박스.
3. 레시피 탭 — 섹션 순차 등장.
4. macOS 손쉬운 사용 > 동작 줄이기 켠 상태에서 애니메이션 비활성 확인.

확인 불가 항목은 보고서에 "미검증"으로 명시.

- [ ] **Step 3: 스크린샷 캡처 후 보고**
