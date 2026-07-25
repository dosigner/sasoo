import type { RefObject } from 'react';

import type { OutlineItem } from '@/lib/mdOutline';

// 분석 단계 본문 위에 뜨는 섹션 목차. 항목을 누르면 Markdown이 headingAnchors로
// 붙인 slug id로 스크롤한다. 표시 여부(헤딩 개수)는 호출부가 정한다.

/** h2를 기준(0)으로 헤딩 레벨 한 단계당 12px 들여쓴다. */
function indentStyle(level: number): { paddingLeft: string } {
  return { paddingLeft: `${Math.max(0, level - 2) * 12}px` };
}

interface SectionOutlineProps {
  outline: OutlineItem[];
  /**
   * 헤딩 id를 찾을 범위. 여러 PhaseSection이 같은 스크롤 컨테이너에 동시에 펼쳐질 수
   * 있고, rehypeHeadingIds의 중복 카운터는 Markdown 인스턴스마다 리셋되므로 두 단계가
   * 같은 헤딩 텍스트를 쓰면 문서 전역에 id가 중복된다. 생략하면 document 전체에서
   * 찾아 엉뚱한 단계로 점프할 수 있다.
   */
  scopeRef?: RefObject<HTMLElement>;
}

export default function SectionOutline({ outline, scopeRef }: SectionOutlineProps) {
  const jump = (slug: string) => {
    const root: ParentNode = scopeRef?.current ?? document;
    // id에 한글·하이픈·숫자가 섞이므로 #선택자 대신 속성 선택자를 쓴다.
    const el = root.querySelector<HTMLElement>(`[id="${CSS.escape(slug)}"]`);
    if (!el) return;

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });

    // 스크린리더에도 점프 맥락을 전달하기 위해 포커스를 옮긴다.
    el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
  };

  return (
    <nav
      aria-label="섹션 목차"
      className="mb-3 rounded-lg border border-border bg-surface px-3 py-2"
    >
      <ul className="space-y-0.5">
        {outline.map((item) => (
          <li key={item.slug} style={indentStyle(item.level)}>
            {/* 이 앱은 main.tsx에서 HashRouter를 쓰므로 <a href="#slug">는 URL 해시를
                덮어써 라우팅을 깬다. 앵커로 "개선"하지 말 것 — button + 수동 스크롤을 쓴다. */}
            <button
              type="button"
              onClick={() => jump(item.slug)}
              title={item.text}
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
