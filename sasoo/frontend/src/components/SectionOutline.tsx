import type { OutlineItem } from '@/lib/mdOutline';

// 분석 단계 본문 위에 뜨는 섹션 목차. 항목을 누르면 Markdown이 headingAnchors로
// 붙인 slug id로 스크롤한다. 표시 여부(헤딩 개수)는 호출부가 정한다.

/** h2를 기준(0)으로 헤딩 레벨 한 단계당 12px 들여쓴다. */
function indentStyle(level: number): { paddingLeft: string } {
  return { paddingLeft: `${Math.max(0, level - 2) * 12}px` };
}

interface SectionOutlineProps {
  outline: OutlineItem[];
}

export default function SectionOutline({ outline }: SectionOutlineProps) {
  const jump = (slug: string) => {
    document
      .getElementById(slug)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <nav
      aria-label="섹션 목차"
      className="mb-3 rounded-lg border border-border bg-surface px-3 py-2"
    >
      <ul className="space-y-0.5">
        {outline.map((item) => (
          <li key={item.slug} style={indentStyle(item.level)}>
            <button
              type="button"
              onClick={() => jump(item.slug)}
              className="w-full truncate text-left text-xs text-fg-muted transition-colors hover:text-accent"
            >
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
