import type { HastNode } from './rehypeHeadingIds';
import type { TerminologyEntry } from './readingGuide';
import { matchTerms } from './terminology';

const SKIP = new Set(['a', 'button', 'code', 'pre', 'math', 'svg', 'script', 'style']);

export function rehypeTerminology(entries: readonly TerminologyEntry[]) {
  return (tree: HastNode) => {
    const walk = (node: HastNode) => {
      const classes = String(node.properties?.className ?? '');
      if (SKIP.has(node.tagName ?? '') || /katex|math-inline|math-display/.test(classes) || !node.children) return;
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text' || !child.value) {
          walk(child);
          return [child];
        }
        const text = child.value;
        const matches = matchTerms(text, entries);
        if (!matches.length) return [child];
        const nodes: HastNode[] = [];
        let cursor = 0;
        for (const match of matches) {
          if (match.start > cursor) nodes.push({ type: 'text', value: text.slice(cursor, match.start) });
          nodes.push({ type: 'element', tagName: 'span', properties: { 'data-terminology': match.entry.term },
            children: [{ type: 'text', value: text.slice(match.start, match.end) }] });
          cursor = match.end;
        }
        if (cursor < text.length) nodes.push({ type: 'text', value: text.slice(cursor) });
        return nodes;
      });
    };
    walk(tree);
  };
}
