// 헤딩(h1~h6)에 slug id를 부여하는 rehype 플러그인. slug 규칙은 mdOutline.slugify와
// 동일해서 extractOutline이 만든 목차 링크가 여기 붙는 id와 정확히 매칭된다(ToC 점프용).
//
// 알려진 한계: extractOutline은 마크다운 원문을 정규식으로 읽고, 이 플러그인은 렌더된
// hast 텍스트를 읽는다. 두 소스가 서로 다르게 보는 경우 slug가 어긋난다:
//   - 링크가 든 헤딩(`## [foo](url)`) — extractOutline은 `[foo](url)`을 그대로 보지만
//     여기는 렌더된 "foo"만 봄
//   - intraword 언더스코어(`## snake_case_name`) — extractOutline의 EMPHASIS 정규식이
//     `_`를 지워 "snakecasename"이 되지만, 렌더된 텍스트는 원문 그대로 "snake_case_name"
//   - setext 헤딩(`제목\n---`) — extractOutline은 ATX(`#`)만 인식해 이 헤딩을 건너뛰므로
//     뒤따르는 헤딩들의 카운터가 밀려 엉뚱한 id를 받을 수 있음
// 실패 모드는 조용한 무반응(ToC를 클릭해도 스크롤되지 않음)이다. 근본 해결은 목차를
// mdast에서 직접 뽑아 단일 소스로 만드는 것인데, 이번 범위 밖이다.

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
        /^h[1-6]$/.test(node.tagName) &&
        !node.properties?.id
      ) {
        const base = slugify(hastText(node));
        const n = seen.get(base) ?? 0;
        seen.set(base, n + 1);
        node.properties = node.properties ?? {};
        node.properties.id = n > 0 ? `${base}-${n + 1}` : base;
      }
      (node.children ?? []).forEach(walk);
    };
    walk(tree);
  };
}
