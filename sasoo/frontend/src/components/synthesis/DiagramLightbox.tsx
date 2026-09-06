import { useEffect, useRef, useState, lazy, Suspense } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Loader2, Minus, Plus, X } from 'lucide-react';
import type { VisualizationItem } from '@/lib/api';
import { getStaticUrl } from '@/lib/api';
import { S } from '@/lib/strings';
import { useFocusTrap } from '@/hooks/useFocusTrap';

const MermaidRenderer = lazy(() => import('../MermaidRenderer'));
const T = S.synthesis;
const MIN_SCALE = 0.25;
const MAX_SCALE = 4;

export interface LightboxTarget {
  item: VisualizationItem;
  /** 구획 이름. 헤더 메타와 방향키 이동 범위 표시에 쓴다. */
  blockLabel: string;
}

interface DiagramLightboxProps {
  targets: LightboxTarget[];
  index: number;
  paperId: number;
  onClose: () => void;
  onIndexChange: (next: number) => void;
  makeRepairHandler: (
    paperId: number,
    vizId: number
  ) => (code: string, errorMessage: string) => Promise<string | null>;
}

interface ViewState {
  scale: number;
  tx: number;
  ty: number;
}

const RESET: ViewState = { scale: 1, tx: 0, ty: 0 };
const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

// 워크벤치 전체(PDF 뷰어와 분석 패널) 위에 올라가야 하므로 body로 포털한다.
// 패널 안에서 fixed를 쓰면 조상의 transform이나 backdrop-filter가 containing
// block이 되어 패널 안에 갇힌다.
export function DiagramLightbox({
  targets,
  index,
  paperId,
  onClose,
  onIndexChange,
  makeRepairHandler,
}: DiagramLightboxProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  const [view, setView] = useState<ViewState>(RESET);
  useFocusTrap(modalRef, true, onClose);

  const target = targets[index];
  const count = targets.length;

  useEffect(() => {
    setView(RESET);
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && index > 0) onIndexChange(index - 1);
      else if (e.key === 'ArrowRight' && index < count - 1) onIndexChange(index + 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, count, onIndexChange]);

  // 휠 줌은 커서 아래 점을 고정한다. preventDefault가 필요해 non-passive로 단다.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      setView((v) => {
        const next = clampScale(v.scale * Math.exp(-e.deltaY * 0.0015));
        const k = next / v.scale;
        return { scale: next, tx: px - (px - v.tx) * k, ty: py - (py - v.ty) * k };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    // 렌더러 툴바의 버튼과 코드 편집기는 드래그 대상이 아니다.
    if ((e.target as HTMLElement).closest('button, textarea, input, a')) return;
    dragRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d) return;
    setView((v) => ({ ...v, tx: d.tx + e.clientX - d.x, ty: d.ty + e.clientY - d.y }));
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };
  const zoomBy = (k: number) => setView((v) => ({ ...v, scale: clampScale(v.scale * k) }));

  if (!target) return null;
  const { item } = target;
  const iconBtn = 'btn-ghost text-2xs px-2 py-1 disabled:opacity-40';

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-md animate-backdrop-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={item.title}
        className="relative z-10 flex h-full flex-col animate-modal-in"
      >
        <div className="flex h-12 items-center gap-3 border-b border-border/60 bg-surface/95 px-4 backdrop-blur-sm">
          <span className="min-w-0 truncate text-sm font-semibold text-fg">{item.title}</span>
          <span className="shrink-0 text-2xs text-fg-muted tabular-nums">
            {target.blockLabel} {index + 1}/{count}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <button className={iconBtn} onClick={() => zoomBy(1 / 1.25)} aria-label={T.zoomOut} title={T.zoomOut}>
              <Minus className="h-3 w-3" />
            </button>
            <button className={`${iconBtn} tabular-nums`} onClick={() => setView(RESET)} title={T.zoomReset}>
              {Math.round(view.scale * 100)}%
            </button>
            <button className={iconBtn} onClick={() => zoomBy(1.25)} aria-label={T.zoomIn} title={T.zoomIn}>
              <Plus className="h-3 w-3" />
            </button>
            <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
            <button className={iconBtn} disabled={index === 0} onClick={() => onIndexChange(index - 1)} aria-label={T.prev} title={T.prev}>
              <ChevronLeft className="h-3 w-3" />
            </button>
            <button className={iconBtn} disabled={index >= count - 1} onClick={() => onIndexChange(index + 1)} aria-label={T.next} title={T.next}>
              <ChevronRight className="h-3 w-3" />
            </button>
            <button className={iconBtn} onClick={onClose} aria-label={T.close} title={T.close}>
              <X className="h-3 w-3" />
            </button>
          </div>
        </div>

        <div
          ref={viewportRef}
          className="flex-1 touch-none overflow-hidden cursor-grab active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div
            className="inline-block min-w-[min(72vw,1080px)] origin-top-left p-8 will-change-transform"
            style={{ transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})` }}
          >
            {item.tool === 'mermaid' && item.mermaid_code ? (
              <div className="rounded-xl border border-border/60 bg-surface p-4 shadow-2xl">
              <Suspense fallback={<Loader2 className="h-5 w-5 animate-spin text-accent" />}>
                <MermaidRenderer
                  diagram={{
                    paper_id: paperId,
                    mermaid_code: item.mermaid_code,
                    diagram_type: item.diagram_type,
                    description: item.description,
                  }}
                  title={item.title}
                  onRepair={makeRepairHandler(paperId, item.id)}
                />
              </Suspense>
              </div>
            ) : item.image_url ? (
              <img
                src={getStaticUrl(item.image_url)}
                alt={item.title}
                className="max-w-[80vw] rounded-lg border border-border bg-surface"
                draggable={false}
              />
            ) : null}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
