# v0.7.1 LaTeX 렌더링 통합 설계

- 날짜: 2026-07-16
- 대상 버전: v0.7.1
- 범위: `sasoo/frontend` — 마크다운/수식 렌더링

## 배경 / 문제

논문 사수의 LLM 응답에는 수식이 자주 포함된다. KaTeX 스택(`katex 0.16.38`, `remark-math 6`, `rehype-katex 7`)은 이미 `sasoo/frontend/package.json`에 설치돼 있고 `vite.config.ts`에서 별도 청크로 분리까지 돼 있으나, 실제 연결은 컴포넌트마다 제각각이다.

| 컴포넌트 | 기능 | 현재 플러그인 | 수식 렌더 |
|---|---|---|---|
| `ChatPanel.tsx:474` | 질문 도우미 | `remarkGfm` + `remarkMath` + `rehypeKatex` | O (단, 스트리밍 중엔 raw) |
| `AnalysisPanel.tsx:337` | 보고서 분석(5-phase) | `remarkGfm`만 | X (항상 raw) |
| `FigureGallery.tsx:435` | figure 해석 | `remarkGfm`만 | X (항상 raw) |
| `TableGallery.tsx:239` | 표 해석 | `remarkGfm`만 | X (항상 raw) |

즉 **figure 해석·보고서 분석 결과에서 수식이 `$...$` 원문 그대로 노출**된다. 근본 원인은 컴포넌트별 플러그인 연결 누락이다.

추가로 두 가지 취약점:

1. **델리미터**: `remark-math` 기본 설정은 `$`/`$$`만 인식한다. LLM이 자주 쓰는 `\(...\)`·`\[...\]`는 ChatPanel에서조차 렌더되지 않는다.
2. **스트리밍 중 raw 노출**: ChatPanel은 `isStreaming` 동안 `ReactMarkdown`을 타지 않고 `whitespace-pre-wrap` 순수 텍스트로 그린다.

## 목표

- figure 해석·보고서 분석·표 해석·질문 도우미 **4곳 모두에서 수식이 동일하게 렌더**된다.
- `$...$`, `$$...$$`, `\(...\)`, `\[...\]` 네 형태 모두 렌더된다.
- ChatPanel 스트리밍 중에도 수식/마크다운이 렌더된다.
- 4곳의 렌더링 설정이 하나의 공용 컴포넌트로 통합돼 다시 벌어지지 않는다.

## 설계

### A. 공용 컴포넌트 `<Markdown>` — 신규 `sasoo/frontend/src/components/Markdown.tsx`

4곳의 제각각 설정을 하나로 통합한다. 유일한 마크다운 렌더 경로.

```tsx
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { normalizeMathDelimiters } from '@/lib/mathDelimiters';

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

interface MarkdownProps {
  children: string;         // 마크다운 원문
  className?: string;       // ChatPanel의 "chat-markdown" 등 (react-markdown 9.1.0에서 지원 확인)
  components?: Components;   // ChatPanel의 인용 클릭 래핑용 (선택)
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

- `katex/dist/katex.min.css` 는 이 파일 한 곳에서만 import한다(번들러가 중복 dedupe).
- `rehypeKatex` 옵션은 기본값을 사용한다. 기본적으로 KaTeX 파싱 에러를 던지지 않고 인라인(빨간색)으로 표시하므로, 스트리밍 중 미완성 수식이 앱을 죽이지 않는다.
- react-markdown 9.1.0의 `className` prop 지원은 설치된 `node_modules/react-markdown/lib/index.d.ts:107`에서 확인됨. ChatPanel의 `chat-markdown` 스타일이 그대로 유지된다.

### B. 델리미터 정규화 유틸 — 신규 `sasoo/frontend/src/lib/mathDelimiters.ts`

```ts
export function normalizeMathDelimiters(md: string): string
```

동작:

1. 코드 영역을 먼저 보호한다 — 코드펜스(```` ``` ... ``` ````)와 인라인 코드(`` `...` ``)를 토큰화해 원문 그대로 유지.
2. 코드가 아닌 나머지 텍스트에서만 변환:
   - `\[ ... \]` → `$$ ... $$` (display)
   - `\( ... \)` → `$ ... $` (inline)
   - display를 inline보다 먼저 처리한다.
3. `$...$`/`$$...$$`는 이미 remark-math가 처리하므로 손대지 않는다.

**왜 문자열 단계(파싱 전)에서 처리하나:** CommonMark는 ASCII 구두점의 백슬래시 이스케이프를 허용한다. `(`, `)`, `[`, `]` 는 구두점이라 `\(`·`\)`·`\[`·`\]` 가 파싱 과정에서 `(`·`)`·`[`·`]` 로 소비된다. 따라서 mdast(파싱 후) 단계의 remark 변환 플러그인으로는 델리미터를 잡을 수 없다. 파싱 전 원문 문자열에서 `$`/`$$`로 바꿔 remark-math에 넘겨야 한다.

구현 메모:

- 코드 보호는 정규식 `/(```[\s\S]*?```|`[^`\n]*`)/g` 로 토큰 분리 후, 코드 토큰은 건너뛰고 비코드 토큰에만 치환을 적용해 재조립한다.
- 치환 정규식: display `/\\\[([\s\S]+?)\\\]/g`, inline `/\\\(([\s\S]+?)\\\)/g`. non-greedy로 짝이 맞는 델리미터 사이만 매칭.
- JS `replace` 문자열에서 `$$`는 리터럴 `$` 를 뜻하므로, 치환은 문자열 리터럴이 아니라 **함수 형태**(`(_, inner) => `$$${inner}$$`` 등)로 작성해 `$` 개수 오류를 피한다.

### C. 4개 호출부 교체 (유지+추가 — 감싸는 div·className·스타일 전부 보존)

- `AnalysisPanel.tsx:337` — 보고서 분석: `<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>` → `<Markdown>{content}</Markdown>`. 상단 `ReactMarkdown`/`remarkGfm` import 제거, `Markdown` import 추가.
- `FigureGallery.tsx:435` — figure 해석: 동일 교체.
- `TableGallery.tsx:239` — 표 해석: 동일 교체.
- `ChatPanel.tsx:470–478` — 질문 도우미:
  - 스트리밍/완료 이중 분기(`isStreaming ? <span whitespace-pre-wrap> : <ReactMarkdown>`)를 제거하고, 두 경우 모두 `<Markdown className="chat-markdown" components={markdownComponents}>{msg.content}</Markdown>` 로 렌더.
  - 스트리밍 커서(`animate-pulse` 막대)와 `msg.status === 'error'` 표시는 그대로 유지.
  - 로컬 상수 `REMARK_PLUGINS`/`REHYPE_PLUGINS`, `remarkMath`/`rehypeKatex`/`ReactMarkdown`/`katex CSS` import 제거(공용 컴포넌트로 이관). `markdownComponents`(인용 래핑)와 `Components` 타입 사용은 유지.

### D. 스트리밍 처리

- 스트리밍 중에도 공용 `<Markdown>`으로 렌더한다. 토큰은 이미 `createTokenBuffer`로 배치되므로 배치 단위로만 재파싱된다(토큰마다 X).
- 미완성 `$$`(닫힘 전)는 remark-math가 수식으로 인식하지 않아 닫히기 전까지 원문으로 잠깐 보이다가 닫히면 렌더된다. 전체 메시지가 스트리밍 내내 raw로 남던 기존 동작보다 개선이며 허용 가능한 트레이드오프.
- 성능 이슈가 관측되면(긴 응답에서 프레임 드랍) 후속으로 재렌더 throttle을 검토한다. 초기 구현엔 넣지 않는다(YAGNI).

### E. 검증

- `sasoo/vitest.config.ts`는 `environment: 'node'`이며 "DOM/Electron import 금지, 순수 로직만" 규약이다. 따라서:
  - `sasoo/frontend/src/lib/mathDelimiters.test.ts` — 순수 함수 단위 테스트 추가(`tokenBuffer.test.ts` 스타일). 케이스:
    - `\(x^2\)` → `$x^2$`
    - `\[E=mc^2\]` → `$$E=mc^2$$`
    - 코드펜스 내부 `\(...\)` 미변환
    - 인라인 코드 내부 `\(...\)` 미변환
    - 기존 `$...$`/`$$...$$` 원본 보존
    - 델리미터 없는 평문 원본 보존
  - `<Markdown>` 컴포넌트 렌더는 node 환경 규약상 단위테스트 불가 → **앱 재시작 후 실제 화면 검증**: 보고서 분석·figure 해석 결과에 수식이 포함된 논문으로 KaTeX 렌더 스크린샷 확인(CLAUDE.md 증거 기반 완료 원칙).
- `pnpm test`(또는 프로젝트 테스트 명령)로 단위 테스트 통과, `tsc`/`vite build` 타입·빌드 통과 확인.

## 안 하는 것 (YAGNI)

- `rehype-highlight` 도입(현재 4곳 어디서도 미사용).
- 백엔드 분석/해석 프롬프트의 델리미터 강제 수정 — 프론트 정규화로 흡수하므로 불필요. (원하면 별도 후속 과제)
- 수식 전체화면·모달·복사 버튼 등 부가 UI.

## 영향 범위 / 리스크

- 신규 파일 2개(`Markdown.tsx`, `mathDelimiters.ts`), 신규 테스트 1개, 수정 파일 4개(Chat/Analysis/Figure/Table Panel·Gallery).
- 리스크: 델리미터 정규화가 코드 블록을 침범하면 코드 예제가 깨질 수 있음 → 코드 보호 로직과 단위 테스트로 방어.
- 리스크: 프로세스 분리 아키텍처 계약(사이드카·fence 등)과 무관한 프론트 전용 변경이라 백엔드 계약에 영향 없음.

## 후속 검토: `$` 통화/텍스트 오인 회귀 (2026-07-16 최종 리뷰 발견, 수용)

remark-math를 3개 갤러리(보고서 분석·figure 해석·표)에 적용하면서 생기는 알려진 이면. remark-math 기본값(`singleDollarTextMath: true`)상 **한 줄에 `$`가 2개 있으면 그 사이가 인라인 수식으로 파싱**된다. 예: "비용이 $5M에서 $10M로" → `$5M에서 $`가 수식으로 렌더되고 나머지가 깨진다. 이전(remarkGfm만)에는 `$`가 리터럴이었으므로 행동 회귀다. 통화·가격이 든 표나 경제/재무 계열 산문에서 재현 가능(유효 LaTeX가 아니면 KaTeX가 빨간 에러 span으로 표시).

**결정: 수용(문서화).** 근거 — (1) 이 기능의 목적 자체가 `$...$` 인라인 수식 렌더이며, single-dollar를 끄면 우리 정규화 `\(...\)`→`$...$`까지 무력화되어 인라인 수식 전체가 안 된다. (2) 이 앱 도메인은 물리·광학·ML 논문 분석이라 통화 `$` 표기가 드물고 인라인 수식이 핵심이다.

**완화 경로(필요 시 후속):** 백엔드 분석/figure 프롬프트에 "통화 금액은 `\$`로 이스케이프" 가이드를 추가하면 근본 해소. 이번 프론트 범위 밖(스펙 YAGNI)이며, 대상 논문에 통화 표기가 잦다는 근거가 생기면 착수.
