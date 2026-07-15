# v0.7.1 LaTeX 렌더링 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** figure 해석·보고서 분석·표·질문도우미 4곳의 마크다운/수식 렌더링을 하나의 공용 `<Markdown>` 컴포넌트로 통합하고, `\(...\)`·`\[...\]` 델리미터까지 렌더되게 한다.

**Architecture:** 파싱 전 문자열 단계에서 `\(...\)`→`$...$`, `\[...\]`→`$$...$$`로 정규화하는 순수 함수(`normalizeMathDelimiters`)를 만들고, 이를 감싼 공용 `<Markdown>` 컴포넌트(remark-gfm + remark-math + rehype-katex)를 4개 호출부에 적용한다. ChatPanel은 스트리밍 분기를 없애 스트리밍 중에도 같은 컴포넌트로 렌더한다.

**Tech Stack:** React 18, TypeScript, react-markdown 9.1.0, remark-gfm 4, remark-math 6, rehype-katex 7, katex 0.16.38, vitest(node env).

## Global Constraints

- 작업 디렉토리 루트: `/Users/dongj/dev/논문_사수_개발중/sasoo`. 아래 파일 경로는 이 루트 기준이거나 절대경로.
- 패키지 매니저는 **pnpm**. 새 의존성 설치 금지 — 필요한 라이브러리는 이미 `frontend/package.json`에 있음.
- 단위 테스트 환경은 **node**(`sasoo/vitest.config.ts`, `environment: 'node'`). 테스트 파일은 **DOM/Electron/React import 금지**, 순수 로직만. 컴포넌트 렌더 테스트를 작성하지 말 것.
- 단위 테스트 실행: `sasoo` 루트에서 `pnpm test:unit` (= `vitest run`).
- 프론트 타입체크/빌드: `sasoo` 루트에서 `pnpm build:frontend`.
- `@/` 는 `sasoo/frontend/src/` 로 매핑(`frontend/tsconfig.json`, `frontend/vite.config.ts`).
- 기존 감싸는 `div`·className·스타일은 보존(유지+추가). ReactMarkdown 태그만 교체.
- 커밋 메시지 말미에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` 포함.

---

## File Structure

- Create: `sasoo/frontend/src/lib/mathDelimiters.ts` — 델리미터 정규화 순수 함수.
- Create: `sasoo/frontend/src/lib/mathDelimiters.test.ts` — 위 함수 단위 테스트.
- Create: `sasoo/frontend/src/components/Markdown.tsx` — 공용 마크다운/수식 렌더 컴포넌트(유일한 렌더 경로).
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx` — 보고서 분석 렌더를 `<Markdown>`으로.
- Modify: `sasoo/frontend/src/components/FigureGallery.tsx` — figure 해석 렌더를 `<Markdown>`으로.
- Modify: `sasoo/frontend/src/components/TableGallery.tsx` — 표 미리보기 렌더를 `<Markdown>`으로.
- Modify: `sasoo/frontend/src/components/ChatPanel.tsx` — 질문도우미 렌더를 `<Markdown>`으로 + 스트리밍 분기 제거.

---

## Task 1: 델리미터 정규화 순수 함수 (TDD)

**Files:**
- Create: `sasoo/frontend/src/lib/mathDelimiters.ts`
- Test: `sasoo/frontend/src/lib/mathDelimiters.test.ts`

**Interfaces:**
- Consumes: 없음.
- Produces: `export function normalizeMathDelimiters(md: string): string` — `\(...\)`→`$...$`, `\[...\]`→`$$...$$`로 바꾼 문자열 반환. 코드펜스(```` ``` ````)·인라인 코드(`` ` ``) 내부는 변환하지 않음. 기존 `$`/`$$`는 그대로.

- [ ] **Step 1: 실패하는 테스트 작성**

`sasoo/frontend/src/lib/mathDelimiters.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { normalizeMathDelimiters } from './mathDelimiters';

describe('normalizeMathDelimiters', () => {
  it('converts inline \\(...\\) to $...$', () => {
    expect(normalizeMathDelimiters('값은 \\(x^2\\) 이다')).toBe('값은 $x^2$ 이다');
  });

  it('converts display \\[...\\] to $$...$$', () => {
    expect(normalizeMathDelimiters('식: \\[E=mc^2\\]')).toBe('식: $$E=mc^2$$');
  });

  it('handles multiple math spans in one string', () => {
    expect(normalizeMathDelimiters('\\(a\\)와 \\(b\\)')).toBe('$a$와 $b$');
  });

  it('leaves existing $ and $$ delimiters untouched', () => {
    expect(normalizeMathDelimiters('$x$ 그리고 $$y$$')).toBe('$x$ 그리고 $$y$$');
  });

  it('leaves plain text without delimiters untouched', () => {
    expect(normalizeMathDelimiters('수식 없는 평범한 문장')).toBe('수식 없는 평범한 문장');
  });

  it('does NOT convert inside a fenced code block', () => {
    const src = '```\n\\(not math\\)\n```';
    expect(normalizeMathDelimiters(src)).toBe(src);
  });

  it('does NOT convert inside inline code', () => {
    const src = '코드 `\\(a\\)` 예시';
    expect(normalizeMathDelimiters(src)).toBe(src);
  });

  it('converts math outside code while preserving code inside the same string', () => {
    const src = '앞 \\(x\\) `\\(keep\\)` 뒤 \\[y\\]';
    expect(normalizeMathDelimiters(src)).toBe('앞 $x$ `\\(keep\\)` 뒤 $$y$$');
  });

  it('handles multiline display math', () => {
    expect(normalizeMathDelimiters('\\[\na+b\n\\]')).toBe('$$\na+b\n$$');
  });
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run (`sasoo` 루트에서): `pnpm test:unit`
Expected: FAIL — `mathDelimiters.ts` 모듈을 찾지 못함(또는 `normalizeMathDelimiters is not a function`).

- [ ] **Step 3: 최소 구현 작성**

`sasoo/frontend/src/lib/mathDelimiters.ts`:

```ts
// LLM 응답의 \(...\)·\[...\] 델리미터를 remark-math가 인식하는 $...$·$$...$$로
// 바꾼다. CommonMark가 파싱 과정에서 \(·\[ 백슬래시 이스케이프를 소비하므로,
// mdast 변환 플러그인이 아니라 파싱 전 원문 문자열에서 처리해야 한다.
// 코드펜스·인라인 코드 내부는 코드 예제가 깨지지 않도록 보호한다.

// 코드펜스(``` ... ```)와 인라인 코드(` ... `)를 토큰으로 분리한다.
// 캡처 그룹을 쓰므로 split 결과에 구분자(코드)가 그대로 포함된다.
const CODE_SPLIT = /(```[\s\S]*?```|`[^`\n]*`)/g;

// 짝이 맞는 델리미터 사이를 non-greedy로 매칭.
const DISPLAY = /\\\[([\s\S]+?)\\\]/g;
const INLINE = /\\\(([\s\S]+?)\\\)/g;

function convertSegment(text: string): string {
  // display를 먼저 처리(더 긴 델리미터 우선).
  // 치환은 함수 형태로 작성한다 — replace 문자열에서 $$는 리터럴 $ 로 해석되어
  // 개수 오류를 내기 때문.
  return text
    .replace(DISPLAY, (_match, inner) => `$$${inner}$$`)
    .replace(INLINE, (_match, inner) => `$${inner}$`);
}

export function normalizeMathDelimiters(md: string): string {
  return md
    .split(CODE_SPLIT)
    .map((part) => {
      // 코드 토큰(```...``` 또는 `...`)은 그대로 둔다.
      if (part.startsWith('```') || (part.startsWith('`') && part.endsWith('`'))) {
        return part;
      }
      return convertSegment(part);
    })
    .join('');
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pnpm test:unit`
Expected: PASS — `normalizeMathDelimiters` 9개 케이스 모두 통과.

- [ ] **Step 5: 커밋**

```bash
git add sasoo/frontend/src/lib/mathDelimiters.ts sasoo/frontend/src/lib/mathDelimiters.test.ts
git commit -m "feat(math): \\(...\\)/\\[...\\] 델리미터 정규화 유틸 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 공용 `<Markdown>` 컴포넌트

**Files:**
- Create: `sasoo/frontend/src/components/Markdown.tsx`

**Interfaces:**
- Consumes: `normalizeMathDelimiters` (Task 1) — `import { normalizeMathDelimiters } from '@/lib/mathDelimiters'`.
- Produces: `export function Markdown(props: MarkdownProps)` where
  `interface MarkdownProps { children: string; className?: string; components?: Components }`.
  `Components` 는 `react-markdown`의 타입. remark-gfm + remark-math + rehype-katex 체인과 katex CSS를 내부에서 처리한다.

> node 환경 규약상 컴포넌트 렌더 단위 테스트는 작성하지 않는다. 검증은 타입체크/빌드(Task 5)와 앱 화면(Task 5)에서 한다.

- [ ] **Step 1: 컴포넌트 작성**

`sasoo/frontend/src/components/Markdown.tsx`:

```tsx
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

import { normalizeMathDelimiters } from '@/lib/mathDelimiters';

// 앱 전체의 유일한 마크다운/수식 렌더 경로. figure 해석·보고서 분석·표·
// 질문도우미가 모두 이 컴포넌트를 쓰므로 수식 렌더 설정이 한 곳에 모인다.
const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

interface MarkdownProps {
  children: string;
  className?: string;
  components?: Components;
}

export function Markdown({ children, className, components }: MarkdownProps) {
  const source = normalizeMathDelimiters(children);
  return (
    <ReactMarkdown
      className={className}
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={REHYPE_PLUGINS}
      components={components}
    >
      {source}
    </ReactMarkdown>
  );
}
```

- [ ] **Step 2: 타입체크 통과 확인**

Run (`sasoo` 루트에서): `pnpm build:frontend`
Expected: 타입 에러 없이 빌드 성공(경고는 무방). `Markdown.tsx` 관련 TS 에러가 없어야 함.

- [ ] **Step 3: 커밋**

```bash
git add sasoo/frontend/src/components/Markdown.tsx
git commit -m "feat(md): 공용 Markdown 컴포넌트 추가(gfm+math+katex 통합)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 3개 갤러리 호출부 교체 (보고서 분석·figure 해석·표)

**Files:**
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx:2-3, 337`
- Modify: `sasoo/frontend/src/components/FigureGallery.tsx:2-3, 435`
- Modify: `sasoo/frontend/src/components/TableGallery.tsx:1-2, 239`

**Interfaces:**
- Consumes: `Markdown` (Task 2) — `import { Markdown } from '@/components/Markdown'`.
- Produces: 없음(내부 렌더 변경).

- [ ] **Step 1: AnalysisPanel.tsx 수정**

상단 import 두 줄
```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
```
을 다음 한 줄로 교체:
```tsx
import { Markdown } from '@/components/Markdown';
```

렌더부(`337` 부근)
```tsx
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
```
을 다음으로 교체:
```tsx
              <Markdown>{content}</Markdown>
```

- [ ] **Step 2: FigureGallery.tsx 수정**

상단 import 두 줄
```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
```
을 다음 한 줄로 교체:
```tsx
import { Markdown } from '@/components/Markdown';
```

렌더부(`435` 부근)
```tsx
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {cached.explanation}
                  </ReactMarkdown>
```
을 다음으로 교체:
```tsx
                  <Markdown>{cached.explanation}</Markdown>
```

- [ ] **Step 3: TableGallery.tsx 수정**

상단 import 두 줄
```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
```
을 다음 한 줄로 교체:
```tsx
import { Markdown } from '@/components/Markdown';
```

렌더부(`239` 부근)
```tsx
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {table.markdown_text}
                    </ReactMarkdown>
```
을 다음으로 교체:
```tsx
                    <Markdown>{table.markdown_text}</Markdown>
```

- [ ] **Step 4: 타입체크/빌드 통과 확인**

Run (`sasoo` 루트에서): `pnpm build:frontend`
Expected: 빌드 성공. 세 파일에서 `ReactMarkdown`/`remarkGfm` 미사용 경고나 에러가 남지 않아야 함(import를 지웠으므로).

- [ ] **Step 5: 커밋**

```bash
git add sasoo/frontend/src/components/AnalysisPanel.tsx sasoo/frontend/src/components/FigureGallery.tsx sasoo/frontend/src/components/TableGallery.tsx
git commit -m "feat(md): 보고서 분석·figure 해석·표 렌더를 공용 Markdown으로 통합

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: ChatPanel 호출부 교체 + 스트리밍 분기 제거

**Files:**
- Modify: `sasoo/frontend/src/components/ChatPanel.tsx:12-23`(imports/상수), `:467-480`(렌더부)

**Interfaces:**
- Consumes: `Markdown` (Task 2).
- Produces: 없음.

배경(현재 코드):
- import: `import ReactMarkdown, { type Components } from 'react-markdown';` / `import remarkGfm from 'remark-gfm';` / `import remarkMath from 'remark-math';` / `import rehypeKatex from 'rehype-katex';` / `import 'katex/dist/katex.min.css';`
- 상수: `const REMARK_PLUGINS = [remarkGfm, remarkMath];` / `const REHYPE_PLUGINS = [rehypeKatex];`
- `markdownComponents`(인용 클릭 래핑)는 `useMemo<Components | undefined>`로 정의됨 — **유지**. `Components` 타입은 계속 필요.

- [ ] **Step 1: import·상수 정리**

`react-markdown`에서는 **타입만** 남긴다. 아래 import 라인들을
```tsx
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
```
다음으로 교체:
```tsx
import { type Components } from 'react-markdown';
import { Markdown } from '@/components/Markdown';
```

그리고 아래 두 상수 라인을 삭제:
```tsx
const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];
```

- [ ] **Step 2: 렌더부 교체(스트리밍 분기 제거)**

현재(`467-480` 부근):
```tsx
                                  {isStreaming ? (
                                    <span className="whitespace-pre-wrap">{msg.content}</span>
                                  ) : (
                                    <ReactMarkdown
                                      className="chat-markdown"
                                      remarkPlugins={REMARK_PLUGINS}
                                      rehypePlugins={REHYPE_PLUGINS}
                                      components={markdownComponents}
                                    >
                                      {msg.content}
                                    </ReactMarkdown>
                                  )}
```
을 다음으로 교체(스트리밍 여부와 무관하게 `<Markdown>` 사용):
```tsx
                                  <Markdown className="chat-markdown" components={markdownComponents}>
                                    {msg.content}
                                  </Markdown>
```

`isStreaming` 커서 표시(바로 아래 `{isStreaming && (<span ... animate-pulse ... />)}`)와 `msg.status === 'error'` 표시는 **그대로 유지**한다.

- [ ] **Step 3: 타입체크/빌드 통과 확인**

Run (`sasoo` 루트에서): `pnpm build:frontend`
Expected: 빌드 성공. `ReactMarkdown`/`remarkGfm`/`remarkMath`/`rehypeKatex`/`REMARK_PLUGINS`/`REHYPE_PLUGINS` 미사용 에러가 남지 않아야 함(전부 제거·이관됨). `markdownComponents`/`Components`는 계속 사용되므로 에러 없어야 함.

- [ ] **Step 4: 커밋**

```bash
git add sasoo/frontend/src/components/ChatPanel.tsx
git commit -m "feat(md): 질문도우미를 공용 Markdown으로 통합, 스트리밍 중에도 수식 렌더

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 전체 검증 (단위 테스트 + 빌드 + 실제 화면)

**Files:** 없음(검증 전용).

- [ ] **Step 1: 전체 단위 테스트**

Run (`sasoo` 루트에서): `pnpm test:unit`
Expected: PASS — `mathDelimiters` 포함 기존 테스트 전부 통과.

- [ ] **Step 2: 전체 프론트 빌드/타입체크**

Run (`sasoo` 루트에서): `pnpm build:frontend`
Expected: 빌드 성공, 타입 에러 0.

- [ ] **Step 3: 잔여 참조 확인(공용화 누락 방지)**

Run:
```bash
cd sasoo/frontend/src/components && grep -rn "ReactMarkdown\|remarkPlugins\|rehypeKatex" . | grep -v "Markdown.tsx"
```
Expected: 출력 없음 — `Markdown.tsx` 외에는 ReactMarkdown 직접 사용처가 남아있지 않아야 함.

- [ ] **Step 4: 실제 앱 화면 검증(수동)**

앱을 재시작(`sasoo` 루트에서 `pnpm dev`)하고, 수식이 포함된 논문으로 다음을 육안 확인:
1. **보고서 분석**(AnalysisPanel, Phase 1 심층 분석) 결과에서 `$...$`/`\(...\)`/`\[...\]` 수식이 KaTeX로 렌더됨.
2. **figure 해석**(그림 클릭 → Lightbox) 결과에서 수식 렌더됨.
3. **질문 도우미**(ChatPanel)에서 스트리밍 중/완료 후 모두 수식 렌더됨.
4. 코드 블록 안의 `\(`·`\[`는 수식으로 바뀌지 않고 코드 그대로 보임.

각 화면 스크린샷을 남긴다. (node 단위테스트 환경에서 컴포넌트 렌더를 검증할 수 없으므로 이 수동 확인이 렌더 검증의 근거다 — CLAUDE.md 증거 기반 완료 원칙.)

- [ ] **Step 5: (선택) 버전 문자열 갱신**

v0.7.1 릴리스로 확정되면 `sasoo/package.json`·`sasoo/VERSION`의 버전을 갱신한다. 릴리스 절차는 별도(메모리 `sasoo-v070-release` 참고). 이 플랜 범위는 렌더링 기능까지이며 릴리스는 사용자 결정으로 진행.

---

## Self-Review 결과

- **Spec 커버리지:** 스펙 A(공용 컴포넌트)=Task 2, B(정규화 유틸)=Task 1, C(4곳 교체)=Task 3+4, D(스트리밍)=Task 4, E(검증)=Task 1 테스트+Task 5. 누락 없음.
- **Placeholder 스캔:** TBD/TODO/"적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함.
- **타입 일관성:** `normalizeMathDelimiters(md: string): string`(Task 1 정의)가 Task 2에서 동일 시그니처로 소비됨. `MarkdownProps { children, className?, components? }`(Task 2 정의)가 Task 3(children만)·Task 4(className+components)에서 정의대로 사용됨. `Components` 타입은 ChatPanel에서 계속 유지.
