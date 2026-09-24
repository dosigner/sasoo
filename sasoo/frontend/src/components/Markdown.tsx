import { Children, useMemo, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import 'katex/dist/katex.min.css';

import { normalizeMathDelimiters } from '@/lib/mathDelimiters';
import { rehypeHeadingIds } from '@/lib/rehypeHeadingIds';
import { detectCitations, type CitationTarget } from '@/lib/citations';
import { withRoJosa } from '@/lib/josa';
import { ReadingCodeBlock } from './ReadingCodeBlock';

// 앱 전체의 유일한 마크다운/수식 렌더 경로. figure 해석·보고서 분석·표·
// 질문도우미가 모두 이 컴포넌트를 쓰므로 수식 렌더 설정이 한 곳에 모인다.
const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

// id는 katex가 헤딩 안 수식을 span 더미로 바꾸기 전에 붙여야 한다. 순서를 뒤집으면
// rehypeHeadingIds가 katex 렌더 결과(mathml 텍스트 등)를 읽어 extractOutline의 slug와
// 어긋난다(ToC 클릭이 조용히 무반응이 됨).
const REHYPE_PLUGINS_WITH_IDS = [rehypeHeadingIds, rehypeKatex];
const READING_HIGHLIGHT = [rehypeHighlight, { detect: false }] satisfies [typeof rehypeHighlight, { detect: boolean }];
const READING_REHYPE_PLUGINS = [...REHYPE_PLUGINS, READING_HIGHLIGHT];
const READING_REHYPE_PLUGINS_WITH_IDS = [...REHYPE_PLUGINS_WITH_IDS, READING_HIGHLIGHT];
const READING_COMPONENTS: Components = {
  pre: ({ node: _node, ...props }) => <ReadingCodeBlock {...props} />,
};

export interface MarkdownCitationOptions {
  onClick: (target: CitationTarget) => void;
  /** false를 돌려주면 그 매치는 칩으로 바꾸지 않고 원문 그대로 남긴다(예: 논문에 없는 Figure 번호). 생략하면 전부 허용. */
  isAllowed?: (target: CitationTarget) => boolean;
}

// 칩 치환 대상 태그. code/a는 넣지 않는다 — 코드 블록과 링크 텍스트 안의 "Fig. 3" 같은
// 문자열이 클릭 가능한 칩으로 바뀌면 안 된다. ChatPanel도 같은 태그 집합에 같은 이유로
// 같은 방식(텍스트 자식만 치환)을 쓰지만, 이 헬퍼는 ChatPanel 소스를 끌어올린 것이 아니라
// Markdown.tsx 전용으로 새로 둔 것이다 — Markdown이 ChatPanel을 import하면 순환 참조가
// 생기고, ChatPanel은 이 작업 범위에서 수정 대상이 아니다. 두 구현이 당분간 중복된다.
type CitationTag = 'p' | 'li' | 'td' | 'th' | 'strong' | 'em' | 'blockquote' | 'h1' | 'h2' | 'h3' | 'h4';

function tokenizeCitationText(text: string, opts: MarkdownCitationOptions): ReactNode {
  const matches = detectCitations(text).filter(
    (m) => !opts.isAllowed || opts.isAllowed({ type: m.type, n: m.n }),
  );
  if (matches.length === 0) return text;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((match, i) => {
    if (match.start > cursor) nodes.push(text.slice(cursor, match.start));
    nodes.push(
      <button
        key={`cite-${i}-${match.start}`}
        type="button"
        className="citation-chip"
        onClick={() => opts.onClick({ type: match.type, n: match.n })}
        title={`${withRoJosa(match.raw)} 이동`}
      >
        {match.raw}
      </button>,
    );
    cursor = match.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function withInlineText(children: ReactNode, opts: MarkdownCitationOptions | undefined, reading: boolean): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child !== 'string') return child;
    const parts = reading
      ? child.split(/(\([^()\r\n]+\)|[가-힣]+[ \t]+수[ \t]+(?:있|없)[가-힣]*[\p{Pe}\p{Pf},.!?;:…"'、，。！？；：]*)/gu)
      : [child];
    return parts.map((part, index) => {
      if (index % 2 === 0) return opts ? tokenizeCitationText(part, opts) : part;
      return part.split(/([,;]\s+)/u).map((group, groupIndex) => {
        if (groupIndex % 2 === 1) return group;
        return <span key={groupIndex} className={part.startsWith('(') ? 'reading-parenthetical' : 'reading-auxiliary'}>
          {opts ? tokenizeCitationText(group, opts) : group}
        </span>;
      });
    });
  });
}

export function ReadingInlineText({ children }: { readonly children: string }) {
  return <span className="reading-inline">{withInlineText(children, undefined, true)}</span>;
}

interface MarkdownProps {
  children: string;
  className?: string;
  components?: Components;
  /** 헤딩에 slug id를 붙인다(분석 본문 목차 점프용). 기본 off. */
  headingAnchors?: boolean;
  /** 있으면 텍스트 노드에서 "Fig. 3" / "표 2" / "p.12" 같은 참조를 채팅과 같은 인용 칩으로 치환한다. */
  citations?: MarkdownCitationOptions;
  codeTools?: boolean;
}

export function Markdown({
  children,
  className,
  components,
  headingAnchors,
  citations,
  codeTools = false,
}: MarkdownProps) {
  const source = normalizeMathDelimiters(children);

  const resolvedComponents = useMemo<Components | undefined>(() => {
    const readingComponents = codeTools ? READING_COMPONENTS : undefined;
    if (!citations && !codeTools) return components;
    const wrap =
      (Tag: CitationTag) =>
      ({ node: _node, children: tagChildren, ...props }: { node?: unknown; children?: ReactNode }) => (
        <Tag {...props}>{withInlineText(tagChildren, citations, codeTools)}</Tag>
      );
    return {
      p: wrap('p'),
      li: wrap('li'),
      td: wrap('td'),
      th: wrap('th'),
      strong: wrap('strong'),
      em: wrap('em'),
      blockquote: wrap('blockquote'),
      h1: wrap('h1'),
      h2: wrap('h2'),
      h3: wrap('h3'),
      h4: wrap('h4'),
      ...readingComponents,
      ...components,
    };
  }, [citations, components, codeTools]);

  const rehypePlugins = codeTools
    ? headingAnchors ? READING_REHYPE_PLUGINS_WITH_IDS : READING_REHYPE_PLUGINS
    : headingAnchors ? REHYPE_PLUGINS_WITH_IDS : REHYPE_PLUGINS;

  const markdown = (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={rehypePlugins}
      components={resolvedComponents}
    >
      {source}
    </ReactMarkdown>
  );
  // react-markdown v10이 className prop을 없앴다. v9는 className이 있을 때만 결과를
  // <div class=...>로 감쌌으므로 같은 조건으로 감싸 DOM 구조를 그대로 유지한다.
  // 무조건 감싸면 className을 안 주는 호출부(표 셀 등)에 없던 블록 요소가 생긴다.
  return className ? <div className={className}>{markdown}</div> : markdown;
}
