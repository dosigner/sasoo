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

// id는 katex가 헤딩 안 수식을 span 더미로 바꾸기 전에 붙여야 한다. 순서를 뒤집으면
// rehypeHeadingIds가 katex 렌더 결과(mathml 텍스트 등)를 읽어 extractOutline의 slug와
// 어긋난다(ToC 클릭이 조용히 무반응이 됨).
const REHYPE_PLUGINS_WITH_IDS = [rehypeHeadingIds, rehypeKatex];

interface MarkdownProps {
  children: string;
  className?: string;
  components?: Components;
  /** 헤딩에 slug id를 붙인다(분석 본문 목차 점프용). 기본 off. */
  headingAnchors?: boolean;
}

export function Markdown({
  children,
  className,
  components,
  headingAnchors,
}: MarkdownProps) {
  const source = normalizeMathDelimiters(children);
  const markdown = (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={headingAnchors ? REHYPE_PLUGINS_WITH_IDS : REHYPE_PLUGINS}
      components={components}
    >
      {source}
    </ReactMarkdown>
  );
  // react-markdown v10이 className prop을 없앴다. v9는 className이 있을 때만 결과를
  // <div class=...>로 감쌌으므로 같은 조건으로 감싸 DOM 구조를 그대로 유지한다.
  // 무조건 감싸면 className을 안 주는 호출부(표 셀 등)에 없던 블록 요소가 생긴다.
  return className ? <div className={className}>{markdown}</div> : markdown;
}
