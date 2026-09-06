import { useState, lazy, Suspense } from 'react';
import { AlertCircle, Maximize2, RefreshCw } from 'lucide-react';
import type { VisualizationItem } from '@/lib/api';
import { S } from '@/lib/strings';
import { PaperBananaViewer } from '../VisualizationGallery';

const MermaidRenderer = lazy(() => import('../MermaidRenderer'));
const T = S.synthesis;

interface DiagramCardProps {
  item: VisualizationItem;
  paperId: number;
  expandAll: boolean;
  regenerating?: boolean;
  regenerateError?: string;
  onOpen: () => void;
  onRegenerate?: () => void;
  onRepair?: (code: string, errorMessage: string) => Promise<string | null>;
}

function Skeleton() {
  return (
    <div
      className="mx-4 mb-4 h-48 animate-pulse rounded-lg bg-border"
      role="status"
      aria-busy="true"
      aria-label={T.diagramGenerating}
    />
  );
}

function Failure({ message, onRegenerate, regenerating }: { message: string; onRegenerate?: () => void; regenerating?: boolean }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-6 text-center">
      <AlertCircle className="h-5 w-5 text-danger" />
      <p className="text-xs text-danger">{message}</p>
      {onRegenerate && (
        <button className="btn-ghost text-2xs px-2 py-1" onClick={onRegenerate} disabled={regenerating}>
          <RefreshCw className={`h-3 w-3 ${regenerating ? 'animate-spin' : ''}`} />
          {T.diagramRegenerate}
        </button>
      )}
    </div>
  );
}

/** 다이어그램이 위, 설명이 아래 접힘. 클릭하면 라이트박스(스펙 §4). */
export function DiagramCard({
  item,
  paperId,
  expandAll,
  regenerating = false,
  regenerateError,
  onOpen,
  onRegenerate,
  onRepair,
}: DiagramCardProps) {
  const [descOpen, setDescOpen] = useState(false);
  const isConcept = item.tool === 'paperbanana';
  const ready = isConcept ? !!item.image_url : !!item.mermaid_code;
  const failed = item.status === 'error' && !ready;
  const generating = !ready && !failed;

  return (
    <article className="group card overflow-hidden p-0">
      <header className="flex items-center gap-2 px-4 pb-2 pt-3">
        <h4 className="min-w-0 flex-1 truncate text-xs font-medium text-fg-secondary">{item.title}</h4>
        <div className="flex items-center gap-1 opacity-0 transition focus-within:opacity-100 group-hover:opacity-100">
          {onRegenerate && (
            <button
              className="btn-ghost text-2xs px-2 py-0.5"
              onClick={onRegenerate}
              disabled={regenerating}
              aria-label={T.diagramRegenerate}
              title={T.diagramRegenerate}
            >
              <RefreshCw className={`h-3 w-3 ${regenerating ? 'animate-spin' : ''}`} />
            </button>
          )}
          {ready && (
            <button className="btn-ghost text-2xs px-2 py-0.5" onClick={onOpen} aria-label={T.expand} title={T.expand}>
              <Maximize2 className="h-3 w-3" />
            </button>
          )}
        </div>
      </header>
      {regenerateError && <p className="px-4 pb-2 text-2xs text-danger">{regenerateError}</p>}

      {generating ? (
        <Skeleton />
      ) : failed ? (
        <Failure
          message={item.error_message || T.generationFailed}
          onRegenerate={onRegenerate}
          regenerating={regenerating}
        />
      ) : (
        <div
          className="cursor-zoom-in [&_svg]:max-h-[58vh]"
          onClick={onOpen}
          role="button"
          tabIndex={0}
          aria-label={T.expand}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onOpen();
            }
          }}
        >
          {isConcept ? (
            <div className="px-4 pb-1">
              <PaperBananaViewer item={item} />
            </div>
          ) : (
            <Suspense fallback={<Skeleton />}>
              <MermaidRenderer
                compact
                diagram={{
                  paper_id: paperId,
                  mermaid_code: item.mermaid_code ?? '',
                  diagram_type: item.diagram_type,
                  description: item.description,
                }}
                title={item.title}
                onRepair={onRepair}
              />
            </Suspense>
          )}
        </div>
      )}

      {item.description && (
        // 패딩은 바깥에 둔다. line-clamp 요소에 패딩이 있으면 잘린 세 번째 줄이
        // 패딩 영역으로 비쳐 보인다.
        <div className="px-4 pb-3 pt-2">
          <p
            className={`cursor-text text-xs leading-relaxed text-fg-muted ${descOpen || expandAll ? '' : 'line-clamp-2'}`}
            onClick={() => setDescOpen((v) => !v)}
          >
            {item.description}
          </p>
        </div>
      )}
    </article>
  );
}
