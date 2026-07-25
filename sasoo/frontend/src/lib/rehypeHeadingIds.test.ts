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

  it('does not let a heading with an existing id consume a later duplicate counter', () => {
    const first = h('h2', '개요');
    first.properties = { id: 'custom' };
    const second = h('h3', '개요');
    run({ type: 'root', children: [first, second] });
    expect(first.properties?.id).toBe('custom');
    // '개요'는 아직 한 번도 slug로 소비되지 않았으므로 second는 '-2'가 아니라 base를 받는다.
    expect(second.properties?.id).toBe('개요');
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
