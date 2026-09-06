import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { AppIcon } from '@/components/icons';
import { S } from '@/lib/strings';

export interface PdfSelectionState {
  text: string;
  page: number;
  rect: DOMRect;
}

interface SelectionExplainPopoverProps {
  selection: PdfSelectionState | null;
  /** 팝오버 좌표를 계산할 기준(PDF 영역 래퍼). 이 요소는 relative로 둬야 한다. */
  containerRef: RefObject<HTMLElement | null>;
  onExplain: () => void;
  tooLong: boolean;
}

const GAP = 8;
const EDGE_PADDING = 4;

/** 선택 영역 위쪽 중앙에 뜨는 작은 카드. 위쪽 공간이 부족하면 아래로 내려간다. */
export default function SelectionExplainPopover({
  selection,
  containerRef,
  onExplain,
  tooLong,
}: SelectionExplainPopoverProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const card = cardRef.current;
    if (!selection || !container || !card) {
      setPosition(null);
      return;
    }

    const containerRect = container.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();

    const centerX = selection.rect.left + selection.rect.width / 2 - containerRect.left;
    const left = Math.min(
      Math.max(centerX - cardRect.width / 2, EDGE_PADDING),
      Math.max(containerRect.width - cardRect.width - EDGE_PADDING, EDGE_PADDING),
    );

    const spaceAbove = selection.rect.top - containerRect.top;
    const placeBelow = spaceAbove < cardRect.height + GAP;
    const rawTop = placeBelow
      ? selection.rect.bottom - containerRect.top + GAP
      : selection.rect.top - containerRect.top - cardRect.height - GAP;
    const top = Math.min(
      Math.max(rawTop, EDGE_PADDING),
      Math.max(containerRect.height - cardRect.height - EDGE_PADDING, EDGE_PADDING),
    );

    setPosition({ left, top });
    // selection.rect은 매번 새 DOMRect 인스턴스라 안전하게 좌표 값으로만 의존한다.
  }, [
    selection,
    selection?.rect.top,
    selection?.rect.left,
    selection?.rect.width,
    selection?.rect.height,
    containerRef,
  ]);

  if (!selection) return null;

  return (
    <div
      ref={cardRef}
      className="pointer-events-auto absolute z-20 flex items-center rounded-control border border-border bg-surface px-2 py-1.5 shadow-[0_1px_2px_rgba(0,0,0,.04),0_2px_8px_rgba(0,0,0,.04)] dark:shadow-none"
      style={{ left: position?.left ?? -9999, top: position?.top ?? -9999 }}
    >
      {tooLong ? (
        <span className="px-1 text-xs font-normal text-fg-muted">{S.readingGuide.explainTooLong}</span>
      ) : (
        <button
          type="button"
          onClick={onExplain}
          aria-label={S.readingGuide.explainSelectionAria}
          className="flex items-center gap-1.5 px-1 text-xs font-medium text-fg transition-colors duration-150 hover:text-accent focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent"
        >
          <AppIcon name="sparkles" className="h-3.5 w-3.5 text-accent" />
          {S.readingGuide.explainSelection}
        </button>
      )}
    </div>
  );
}
