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
