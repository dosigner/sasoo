// rehypeHeadingIds.test.ts는 손으로 만든 hast 트리로 slug 계약을 검증하지만, 그건
// 실제 remark→rehype 파이프라인을 우회한다. 여기서는 Markdown.tsx와 동일한 플러그인
// 구성·순서(remarkGfm, remarkMath → remark-rehype → rehypeHeadingIds, rehypeKatex)로
// unified 프로세서를 만들어 마크다운 문자열을 실제로 처리하고, 나온 헤딩 id 배열이
// extractOutline(md)이 만든 slug와 정확히 일치하는지 검증한다.
//
// 알려진 불일치(의도적으로 테스트하지 않음 — rehypeHeadingIds.ts 상단 주석 참고):
// 링크가 든 헤딩, intraword 언더스코어(snake_case_name), setext 헤딩(제목\n---)은
// extractOutline(마크다운 원문 정규식)과 rehypeHeadingIds(렌더된 텍스트)가 서로 다른
// 것을 보므로 slug가 어긋난다. 근본 해결(목차를 mdast에서 뽑아 단일 소스화)은 이번
// 범위 밖이다.

import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkRehype from 'remark-rehype';
import rehypeKatex from 'rehype-katex';
import { visit } from 'unist-util-visit';
import type { Root, Element } from 'hast';

import { extractOutline } from './mdOutline';
import { rehypeHeadingIds } from './rehypeHeadingIds';

// Markdown.tsx(REHYPE_PLUGINS_WITH_IDS)와 동일한 순서: id를 먼저 붙이고, 그 다음
// katex가 수식을 렌더한다(Fix 2). react-markdown이 내부적으로 쓰는
// remark-rehype 옵션({ allowDangerousHtml: true })도 그대로 맞춘다.
function headingIdsOf(md: string): (string | undefined)[] {
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeHeadingIds)
    .use(rehypeKatex);

  const tree = processor.runSync(processor.parse(md)) as Root;

  const ids: (string | undefined)[] = [];
  visit(tree, 'element', (node: Element) => {
    if (/^h[1-6]$/.test(node.tagName)) {
      ids.push(node.properties?.id as string | undefined);
    }
  });
  return ids;
}

function expectSlugsMatch(md: string): void {
  const expected = extractOutline(md).map((item) => item.slug);
  expect(headingIdsOf(md)).toEqual(expected);
}

describe('rehypeHeadingIds pipeline contract (실제 remark→rehype 경로)', () => {
  it('plain heading', () => {
    expectSlugsMatch('## 실험 방법');
  });

  it('inline math heading (Fix 2: id가 katex보다 먼저 붙어야 함)', () => {
    expectSlugsMatch('## $\\chi^2$ 검정');
  });

  it('emphasis + inline code heading', () => {
    expectSlugsMatch('## **핵심** `foo` 요약');
  });

  it('heading ending in a colon', () => {
    expectSlugsMatch('## 결론:');
  });

  it('duplicate headings suffix the second with -2', () => {
    expectSlugsMatch('## 결론\n본문\n## 결론');
  });
});
