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
