# 분석 단계 안 목차(ToC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 각 단계(Phase)를 펼치면 본문 위에 그 단계의 헤딩 목차가 뜨고, 항목을 누르면 해당 헤딩으로 스크롤한다.

**Architecture:** 이미 있는 순수 유틸 `extractOutline`(마크다운 → 헤딩 목록)과 `Markdown`의 `headingAnchors`(헤딩에 slug id 부여)를 연결한다. 신규는 목차를 그리는 프레젠테이션 컴포넌트 `SectionOutline` 하나. slug 규칙이 양쪽 동일(`mdOutline.slugify`)하므로 목차 링크와 헤딩 id가 정확히 매칭된다.

**Tech Stack:** React 19 + TypeScript, Tailwind, react-markdown/rehype, vitest(순수 함수 전용)

## Global Constraints

- **컴포넌트 렌더 테스트 인프라가 없다**(`@testing-library/*`·jsdom 미설치, `*.test.tsx` 0개). 순수 함수만 vitest로 테스트하고, 컴포넌트는 `pnpm build`(tsc+vite) + 수동 검증으로 확인한다. 테스트 인프라를 새로 추가하지 말 것.
- `OutlineItem` 필드는 `{ level: number; text: string; slug: string }` — `depth` 아님.
- **slug 계약:** `rehypeHeadingIds`와 `extractOutline`은 반드시 같은 slug를 만들어야 한다(둘 다 `mdOutline.slugify` 사용). 깨지면 목차 점프가 조용히 실패한다.
- 목차는 헤딩이 **2개 이상**인 단계에만 표시한다.
- import 스타일: `lib`은 `@/lib/...`, 같은 폴더 컴포넌트는 상대경로(`./SectionOutline`, default export).
- 스타일은 기존 토큰만 재사용: `border`, `surface`, `accent`, `fg-muted`, `text-xs`.
- 모든 명령은 `sasoo/frontend`에서 실행한다. 테스트 `pnpm test`(= `vitest run`), 빌드 `pnpm build`(= `tsc -b && vite build`), 린트 `pnpm lint`(`--max-warnings 0`).

---

## File Structure

| 파일 | 역할 |
|---|---|
| `sasoo/frontend/src/lib/rehypeHeadingIds.ts` (신규) | 헤딩에 slug id를 붙이는 rehype 플러그인. 순수 hast 변환이라 단독 테스트 가능 |
| `sasoo/frontend/src/lib/rehypeHeadingIds.test.ts` (신규) | 위 플러그인 테스트 + extractOutline과의 slug 일치 계약 검증 |
| `sasoo/frontend/src/components/Markdown.tsx` (수정) | 인라인 플러그인을 lib import로 교체 |
| `sasoo/frontend/src/components/SectionOutline.tsx` (신규) | 목차 렌더 + 클릭 시 스크롤. 상태 없는 프레젠테이션 컴포넌트 |
| `sasoo/frontend/src/components/AnalysisPanel.tsx` (수정) | `PhaseSection`에서 outline 계산 → 조건부 목차 + `headingAnchors` 연결 |
| `sasoo/frontend/src/lib/mdOutline.ts` | 변경 없음(재사용) |

---

### Task 1: rehypeHeadingIds를 lib으로 분리하고 테스트한다

현재 이 플러그인은 `Markdown.tsx` 안에 인라인으로 있어 테스트할 수 없다. lib으로 빼면 순수 함수라 vitest로 검증할 수 있고, slug 계약(목차 링크 ↔ 헤딩 id)을 테스트로 못 박을 수 있다.

**Files:**
- Create: `sasoo/frontend/src/lib/rehypeHeadingIds.ts`
- Create: `sasoo/frontend/src/lib/rehypeHeadingIds.test.ts`
- Modify: `sasoo/frontend/src/components/Markdown.tsx` (15–54행의 `HastNode`/`hastText`/`rehypeHeadingIds` 제거 후 import)

**Interfaces:**
- Consumes: `slugify`, `extractOutline` (`@/lib/mdOutline`)
- Produces:
  - `export interface HastNode { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: HastNode[] }`
  - `export function hastText(node: HastNode): string`
  - `export function rehypeHeadingIds(): (tree: HastNode) => void`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

Create `sasoo/frontend/src/lib/rehypeHeadingIds.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { extractOutline } from './mdOutline';
import { rehypeHeadingIds, type HastNode } from './rehypeHeadingIds';

function h(tagName: string, text: string): HastNode {
  return { type: 'element', tagName, children: [{ type: 'text', value: text }] };
}

function run(tree: HastNode): void {
  rehypeHeadingIds()(tree);
}

describe('rehypeHeadingIds', () => {
  it('adds a slug id to headings', () => {
    const node = h('h2', '실험 방법');
    run({ type: 'root', children: [node] });
    expect(node.properties?.id).toBe('실험-방법');
  });

  it('suffixes duplicate slugs with -2', () => {
    const first = h('h2', '개요');
    const second = h('h3', '개요');
    run({ type: 'root', children: [first, second] });
    expect(first.properties?.id).toBe('개요');
    expect(second.properties?.id).toBe('개요-2');
  });

  it('keeps an id that is already set', () => {
    const node = h('h2', '개요');
    node.properties = { id: 'custom' };
    run({ type: 'root', children: [node] });
    expect(node.properties?.id).toBe('custom');
  });

  it('leaves non-heading elements alone', () => {
    const node = h('p', '본문');
    run({ type: 'root', children: [node] });
    expect(node.properties?.id).toBeUndefined();
  });

  it('produces the same slugs as extractOutline (ToC 링크 계약)', () => {
    const md = '## 개요\n본문\n### 세부\n## 개요';
    const outline = extractOutline(md);
    const nodes = [h('h2', '개요'), h('h3', '세부'), h('h2', '개요')];
    run({ type: 'root', children: nodes });
    expect(nodes.map((n) => n.properties?.id)).toEqual(outline.map((i) => i.slug));
  });
});
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd sasoo/frontend && pnpm test rehypeHeadingIds`
Expected: FAIL — `Failed to resolve import "./rehypeHeadingIds"` (모듈이 아직 없음)

- [ ] **Step 3: 플러그인을 lib으로 옮긴다**

Create `sasoo/frontend/src/lib/rehypeHeadingIds.ts` (내용은 현재 `Markdown.tsx` 15–52행에서 그대로 이관하되 export를 붙인다):

```ts
// 헤딩(h1~h6)에 slug id를 부여하는 rehype 플러그인. slug 규칙은 mdOutline.slugify와
// 동일해서 extractOutline이 만든 목차 링크가 여기 붙는 id와 정확히 매칭된다(ToC 점프용).

import { slugify } from './mdOutline';

/** 최소 hast 노드 형태(explicit any 회피). */
export interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

export function hastText(node: HastNode): string {
  if (node.type === 'text') return node.value ?? '';
  return (node.children ?? []).map(hastText).join('');
}

export function rehypeHeadingIds() {
  return (tree: HastNode) => {
    const seen = new Map<string, number>();
    const walk = (node: HastNode) => {
      if (
        node.type === 'element' &&
        node.tagName &&
        /^h[1-6]$/.test(node.tagName)
      ) {
        const base = slugify(hastText(node));
        const n = seen.get(base) ?? 0;
        seen.set(base, n + 1);
        node.properties = node.properties ?? {};
        if (!node.properties.id) {
          node.properties.id = n > 0 ? `${base}-${n + 1}` : base;
        }
      }
      (node.children ?? []).forEach(walk);
    };
    walk(tree);
  };
}
```

- [ ] **Step 4: Markdown.tsx가 lib을 쓰도록 바꾼다**

`sasoo/frontend/src/components/Markdown.tsx`에서 15–52행(`// 최소 hast 노드 형태…` 주석부터 `rehypeHeadingIds` 함수 끝까지)을 삭제하고, import를 교체한다. `slugify` import도 더 이상 필요 없으므로 지운다.

변경 후 파일 상단은 이렇게 된다:

```tsx
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

import { normalizeMathDelimiters } from '@/lib/mathDelimiters';
import { rehypeHeadingIds } from '@/lib/rehypeHeadingIds';

// 앱 전체의 유일한 마크다운/수식 렌더 경로. figure 해석·보고서 분석·표·
// 질문도우미가 모두 이 컴포넌트를 쓰므로 수식 렌더 설정이 한 곳에 모인다.
const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

const REHYPE_PLUGINS_WITH_IDS = [rehypeKatex, rehypeHeadingIds];
```

`MarkdownProps`와 `Markdown` 함수 본문(56–81행)은 그대로 둔다.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `cd sasoo/frontend && pnpm test rehypeHeadingIds`
Expected: PASS — 5 tests passed

- [ ] **Step 6: 타입체크·빌드·린트를 확인한다**

Run: `cd sasoo/frontend && pnpm build && pnpm lint`
Expected: 빌드 성공, 린트 에러 0

- [ ] **Step 7: 커밋한다**

```bash
git add sasoo/frontend/src/lib/rehypeHeadingIds.ts \
        sasoo/frontend/src/lib/rehypeHeadingIds.test.ts \
        sasoo/frontend/src/components/Markdown.tsx
git commit -m "refactor(md): rehypeHeadingIds를 lib으로 분리하고 slug 계약 테스트 추가"
```

---

### Task 2: SectionOutline 컴포넌트를 만든다

목차를 그리는 상태 없는 컴포넌트. 표시 여부(헤딩 2개 이상)는 이 컴포넌트가 아니라 호출부가 판단한다 — 그래야 이 컴포넌트는 "주어진 목차를 그린다"는 한 가지 일만 한다.

**Files:**
- Create: `sasoo/frontend/src/components/SectionOutline.tsx`

**Interfaces:**
- Consumes: `OutlineItem` (`@/lib/mdOutline`), Task 1이 보장한 헤딩 id
- Produces: `export default function SectionOutline({ outline }: { outline: OutlineItem[] })`

**테스트 없음:** Global Constraints대로 컴포넌트 렌더 테스트 인프라가 없다. 빌드·린트와 Task 3의 수동 검증으로 확인한다.

- [ ] **Step 1: 컴포넌트를 작성한다**

Create `sasoo/frontend/src/components/SectionOutline.tsx`:

```tsx
import type { OutlineItem } from '@/lib/mdOutline';

// 분석 단계 본문 위에 뜨는 섹션 목차. 항목을 누르면 Markdown이 headingAnchors로
// 붙인 slug id로 스크롤한다. 표시 여부(헤딩 개수)는 호출부가 정한다.

/** h2를 기준(0)으로 헤딩 레벨 한 단계당 12px 들여쓴다. */
function indentStyle(level: number): { paddingLeft: string } {
  return { paddingLeft: `${Math.max(0, level - 2) * 12}px` };
}

interface SectionOutlineProps {
  outline: OutlineItem[];
}

export default function SectionOutline({ outline }: SectionOutlineProps) {
  const jump = (slug: string) => {
    document
      .getElementById(slug)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <nav
      aria-label="섹션 목차"
      className="mb-3 rounded-lg border border-border bg-surface px-3 py-2"
    >
      <ul className="space-y-0.5">
        {outline.map((item) => (
          <li key={item.slug} style={indentStyle(item.level)}>
            <button
              type="button"
              onClick={() => jump(item.slug)}
              className="w-full truncate text-left text-xs text-fg-muted transition-colors hover:text-accent"
            >
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 2: 빌드·린트를 확인한다**

Run: `cd sasoo/frontend && pnpm build && pnpm lint`
Expected: 빌드 성공, 린트 에러 0

- [ ] **Step 3: 커밋한다**

```bash
git add sasoo/frontend/src/components/SectionOutline.tsx
git commit -m "feat(analysis): 섹션 목차 컴포넌트 SectionOutline 추가"
```

---

### Task 3: AnalysisPanel의 각 단계에 목차를 연결한다

**Files:**
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx` (1행 React import, 상단 import 블록, `PhaseSection`의 335–339행)

**Interfaces:**
- Consumes: `extractOutline` (`@/lib/mdOutline`), `SectionOutline` (Task 2), `Markdown`의 `headingAnchors` prop (Task 1)
- Produces: 없음(최종 연결 지점)

- [ ] **Step 1: import를 추가한다**

`AnalysisPanel.tsx` 1행의 React import에 `useMemo`를 추가한다:

```tsx
import { useState, useCallback, useEffect, useMemo, lazy, Suspense } from 'react';
```

그리고 기존 import 블록(35–39행 근처, 다른 컴포넌트 import 옆)에 두 줄을 추가한다:

```tsx
import { extractOutline } from '@/lib/mdOutline';
import SectionOutline from './SectionOutline';
```

- [ ] **Step 2: PhaseSection에서 outline을 계산한다**

`PhaseSection` 함수 컴포넌트 본문 최상단(다른 훅들과 같은 위치)에 추가한다. `content`는 이미 이 컴포넌트의 prop이다:

```tsx
const outline = useMemo(() => (content ? extractOutline(content) : []), [content]);
```

- [ ] **Step 3: 본문 위에 목차를 조건부로 렌더한다**

335–339행의 content 블록을 다음으로 교체한다:

```tsx
          {content && (
            <div className="analysis-content mt-2 fade-in-up">
              {outline.length >= 2 && <SectionOutline outline={outline} />}
              <Markdown headingAnchors>{content}</Markdown>
            </div>
          )}
```

바뀐 점은 두 가지다: 목차를 헤딩 2개 이상일 때만 앞에 넣고, `Markdown`에 `headingAnchors`를 켠다.

- [ ] **Step 4: 기존 테스트·빌드·린트를 확인한다**

Run: `cd sasoo/frontend && pnpm test && pnpm build && pnpm lint`
Expected: 기존 테스트 전부 통과(Task 1의 5개 포함), 빌드 성공, 린트 에러 0

- [ ] **Step 5: 수동으로 검증한다**

Run: `cd sasoo/frontend && pnpm dev` 후 분석 결과가 있는 화면을 연다.

확인 항목:
1. 헤딩이 2개 이상인 단계를 펼치면 본문 위에 목차 박스가 보인다.
2. 목차 항목을 누르면 해당 헤딩 위치로 부드럽게 스크롤된다.
3. 헤딩이 0~1개인 단계에는 목차가 나타나지 않는다.
4. 한글 헤딩도 정상 점프한다(slug가 한글 보존).
5. 같은 이름 헤딩이 두 번 나와도 각각 제 위치로 점프한다(`-2` 접미사).

- [ ] **Step 6: 커밋한다**

```bash
git add sasoo/frontend/src/components/AnalysisPanel.tsx
git commit -m "feat(analysis): 각 분석 단계에 섹션 목차 연결"
```

---

## 완료 기준

- `pnpm test` 통과(기존 3개 파일 + `rehypeHeadingIds.test.ts`)
- `pnpm build`·`pnpm lint` 통과
- Task 3 Step 5의 수동 확인 5항목 모두 통과
