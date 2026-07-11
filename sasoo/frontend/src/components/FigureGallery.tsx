import { useState, useCallback, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2 } from 'lucide-react';
import { getLibraryAssetUrl, type Figure, type VisualState } from '@/lib/api';
import { S } from '@/lib/strings';
import { generateFigureExplanation } from '@/lib/api';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { AppIcon } from '@/components/icons';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FigureGalleryProps {
  figures: Figure[];
  paperId: string;
  loading?: boolean;
  visualState?: VisualState;
  visualError?: string | null;
  artifactsReady?: boolean;
  artifactsError?: string | null;
  onJumpToFigurePage?: (figure: Figure) => void;
}

interface CachedExplanation {
  explanation: string;
  modelUsed: string;
}

interface FigureGroup {
  parent: Figure;
  children: Figure[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function qualityBadge(quality: string | null): {
  label: string;
  classes: string;
} {
  switch (quality) {
    case 'high':
      return { label: S.figures.qualityHigh, classes: 'bg-success/10 text-success' };
    case 'medium':
      return { label: S.figures.qualityMedium, classes: 'bg-warning/10 text-warning' };
    case 'low':
      return { label: S.figures.qualityLow, classes: 'bg-danger/10 text-danger' };
    default:
      return { label: S.figures.qualityUnknown, classes: 'bg-fg-muted/10 text-fg-muted' };
  }
}

function getFigureImageUrl(figure: Figure): string {
  return getLibraryAssetUrl(figure.file_path);
}

function formatConfidence(confidence: number | null | undefined): string | null {
  if (typeof confidence !== 'number' || Number.isNaN(confidence)) return null;
  return `${Math.round(confidence * 100)}%`;
}

function buildStatusBadge(figure: Figure): { label: string; classes: string } {
  if (figure.extraction_status === 'uncertain') {
    return {
      label: S.figures.statusUncertain,
      classes: 'bg-warning/10 text-warning border border-warning/20',
    };
  }

  return {
    label: S.figures.statusReady,
    classes: 'bg-success/10 text-success border border-success/20',
  };
}

function buildFigureGroups(figures: Figure[]): FigureGroup[] {
  const byId = new Map<number, Figure>();
  const childMap = new Map<number, Figure[]>();
  const rootFigures: Figure[] = [];

  for (const figure of figures) {
    if (typeof figure.id === 'number') {
      byId.set(figure.id, figure);
    }
  }

  for (const figure of figures) {
    if (typeof figure.parent_figure_id === 'number' && byId.has(figure.parent_figure_id)) {
      const siblings = childMap.get(figure.parent_figure_id) ?? [];
      siblings.push(figure);
      childMap.set(figure.parent_figure_id, siblings);
      continue;
    }
    rootFigures.push(figure);
  }

  return rootFigures.map((parent) => ({
    parent,
    children: typeof parent.id === 'number' ? childMap.get(parent.id) ?? [] : [],
  }));
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function FigureSkeleton() {
  return (
    <div className="card p-0 overflow-hidden animate-pulse">
      <div className="aspect-[4/3] bg-border" />
      <div className="p-3 space-y-2">
        <div className="h-3 bg-border rounded w-3/4" />
        <div className="h-3 bg-border rounded w-1/2" />
      </div>
    </div>
  );
}

function ExplanationSkeleton() {
  return (
    <div className="space-y-4 animate-pulse p-6">
      <div className="flex items-center gap-2 mb-6">
        <div className="w-5 h-5 bg-accent/20 rounded" />
        <div className="h-5 bg-border rounded w-48" />
      </div>
      <div className="space-y-3">
        <div className="h-4 bg-border rounded w-full" />
        <div className="h-4 bg-border rounded w-5/6" />
        <div className="h-4 bg-border rounded w-4/5" />
      </div>
      <div className="h-5 bg-border rounded w-36 mt-6" />
      <div className="space-y-3">
        <div className="h-4 bg-border rounded w-full" />
        <div className="h-4 bg-border rounded w-11/12" />
        <div className="h-4 bg-border rounded w-4/5" />
        <div className="h-4 bg-border rounded w-full" />
        <div className="h-4 bg-border rounded w-3/4" />
      </div>
      <div className="h-5 bg-border rounded w-44 mt-6" />
      <div className="space-y-3">
        <div className="h-4 bg-border rounded w-full" />
        <div className="h-4 bg-border rounded w-5/6" />
        <div className="h-4 bg-border rounded w-full" />
        <div className="h-4 bg-border rounded w-2/3" />
      </div>
      <div className="flex items-center gap-2 mt-8 text-fg-muted">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-xs">{S.figures.explanationLoading}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lightbox (Split Panel)
// ---------------------------------------------------------------------------

interface LightboxProps {
  figures: Figure[];
  paperId: string;
  currentIndex: number;
  isClosing: boolean;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}

function Lightbox({
  figures,
  paperId,
  currentIndex,
  isClosing,
  onClose,
  onPrev,
  onNext,
}: LightboxProps) {
  const figure = figures[currentIndex];
  const [explanations, setExplanations] = useState<Record<number, CachedExplanation>>({});
  const [loadingId, setLoadingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rightPanelRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  useFocusTrap(modalRef, true, onClose);

  // Fetch explanation when figure changes
  useEffect(() => {
    if (!figure || !figure.id) return;

    const figureId = figure.id;

    // Already cached
    if (explanations[figureId]) {
      setError(null);
      return;
    }

    // Already have a pre-existing detailed_explanation from the DB
    if (figure.detailed_explanation) {
      setExplanations((prev) => ({
        ...prev,
        [figureId]: {
          explanation: figure.detailed_explanation!,
          modelUsed: 'cached',
        },
      }));
      setError(null);
      return;
    }

    // Fetch from API
    let cancelled = false;
    setLoadingId(figureId);
    setError(null);

    generateFigureExplanation(paperId, figureId)
      .then((res) => {
        if (cancelled) return;
        setExplanations((prev) => ({
          ...prev,
          [figureId]: {
            explanation: res.explanation,
            modelUsed: res.model_used,
          },
        }));
        setLoadingId(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || S.figures.explanationFailed);
        setLoadingId(null);
      });

    return () => {
      cancelled = true;
    };
  }, [figure, paperId, explanations]);

  // Scroll right panel to top when changing figures
  useEffect(() => {
    if (rightPanelRef.current) {
      rightPanelRef.current.scrollTop = 0;
    }
  }, [currentIndex]);

  if (!figure) return null;

  const badge = qualityBadge(figure.quality);
  const figureId = figure.id ?? 0;
  const cached = explanations[figureId];
  const isLoading = loadingId === figureId;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      {/* Backdrop – click to close */}
      <div
        className={`absolute inset-0 bg-black/60 backdrop-blur-md ${
          isClosing ? 'animate-backdrop-out' : 'animate-backdrop-in'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Centered modal card */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={`그림 상세 보기: ${figure.figure_num || 'Figure'}`}
        className={`figure-modal relative z-10 flex w-full max-w-[90vw] h-[85vh] bg-surface border border-border/60 rounded-2xl shadow-2xl overflow-hidden ${
          isClosing ? 'animate-modal-out' : 'animate-modal-in'
        }`}
      >
        {/* Header bar */}
        <div className="figure-modal-header absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-4 bg-surface/95 backdrop-blur border-b border-border/50 z-10">
          <div className="flex items-center gap-3">
            <h4 className="text-sm font-semibold text-fg flex items-center gap-2">
              <AppIcon name="figures" className="w-4 h-4 text-accent" />
              {figure.figure_num || 'Figure'}
            </h4>
            <span className={`badge text-2xs ${badge.classes}`}>
              {badge.label}
            </span>
            {figure.caption && (
              <span className="text-2xs text-fg-muted truncate max-w-[300px] hidden lg:inline">
                {figure.caption}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Prev / Next */}
            <div className="flex items-center gap-1 mr-2">
              <button
                onClick={onPrev}
                disabled={currentIndex <= 0}
                className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors disabled:opacity-30 disabled:pointer-events-none"
                aria-label="이전 그림"
              >
                <AppIcon name="chevron-left" className="w-4 h-4" />
              </button>
              <span className="text-2xs text-fg-muted tabular-nums min-w-[36px] text-center">
                {currentIndex + 1} / {figures.length}
              </span>
              <button
                onClick={onNext}
                disabled={currentIndex >= figures.length - 1}
                className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors disabled:opacity-30 disabled:pointer-events-none"
                aria-label="다음 그림"
              >
                <AppIcon name="chevron-right" className="w-4 h-4" />
              </button>
            </div>
            {/* Close */}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors"
              aria-label="닫기"
            >
              <AppIcon name="close" className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body – two panels below header */}
        <div className="flex w-full h-full pt-12 min-h-0">
          {/* LEFT: Image */}
          <div className="figure-modal-image w-[45%] flex-shrink-0 flex flex-col items-center justify-center p-6 bg-bg/50 min-w-0">
            <div className="flex-1 flex items-center justify-center w-full overflow-hidden">
              <img
                src={getFigureImageUrl(figure)}
                alt={figure.caption || `Figure ${figure.figure_num}`}
                className="max-w-full max-h-full object-contain rounded-lg"
              />
            </div>
            {figure.caption && (
              <p className="mt-3 text-xs text-fg-muted leading-relaxed text-center max-w-md line-clamp-3 lg:line-clamp-none">
                {figure.caption}
              </p>
            )}
          </div>

          {/* Divider */}
          <div className="figure-modal-divider w-px bg-border/40 flex-shrink-0" />

          {/* RIGHT: Explanation */}
          <div
            ref={rightPanelRef}
            className="flex-1 overflow-y-auto min-w-0 min-h-0 figure-explanation-panel"
          >
            {isLoading ? (
              <ExplanationSkeleton />
            ) : error ? (
              <div className="flex flex-col items-center justify-center h-full text-center p-8">
                <div className="w-12 h-12 rounded-full bg-danger/10 flex items-center justify-center mb-4">
                  <AppIcon name="error" className="w-6 h-6 text-danger" />
                </div>
                <p className="text-sm text-fg-secondary mb-2">{S.figures.explanationFailed}</p>
                <p className="text-xs text-fg-muted mb-4">{error}</p>
                <button
                  onClick={() => {
                    if (figure.id) {
                      setError(null);
                      setLoadingId(figure.id);
                      generateFigureExplanation(paperId, figure.id)
                        .then((res) => {
                          setExplanations((prev) => ({
                            ...prev,
                            [figure.id!]: {
                              explanation: res.explanation,
                              modelUsed: res.model_used,
                            },
                          }));
                          setLoadingId(null);
                        })
                        .catch((err) => {
                          setError(err.message || S.figures.explanationFailed);
                          setLoadingId(null);
                        });
                    }
                  }}
                  className="btn-secondary text-xs"
                  aria-label={S.figures.retry}
                >
                  {S.figures.retry}
                </button>
              </div>
            ) : cached ? (
              <div className="p-6">
                <div className="flex items-center gap-2 mb-5 pb-3 border-b border-border/50">
                  <AppIcon name="sparkles" className="w-4 h-4 text-accent" />
                  <h3 className="text-sm font-semibold text-fg">
                    {S.figures.expertExplanation}
                  </h3>
                  {cached.modelUsed && cached.modelUsed !== 'cached' && (
                    <span className="badge text-2xs bg-accent/10 text-accent ml-auto">
                      {cached.modelUsed}
                    </span>
                  )}
                </div>
                <div className="analysis-content figure-explanation-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {cached.explanation}
                  </ReactMarkdown>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center p-8">
                <AppIcon name="library" className="w-10 h-10 text-fg-muted mb-3" />
                <p className="text-sm text-fg-muted">
                  {S.figures.clickForExplanation}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Figure Card
// ---------------------------------------------------------------------------

interface FigureCardProps {
  figure: Figure;
  index: number;
  childCount?: number;
  onOpen: (index: number) => void;
  onJumpToFigurePage?: (figure: Figure) => void;
}

function FigureCard({
  figure,
  index,
  childCount = 0,
  onOpen,
  onJumpToFigurePage,
}: FigureCardProps) {
  const badge = qualityBadge(figure.quality);
  const statusBadge = buildStatusBadge(figure);
  const confidenceLabel = formatConfidence(figure.confidence);

  return (
    <div
      className="card-hover overflow-hidden p-0 group"
      role="button"
      tabIndex={0}
      onClick={() => onOpen(index)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen(index);
        }
      }}
      aria-label={S.figures.viewDetail(figure.figure_num || 'Figure')}
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-surface">
        <img
          src={getFigureImageUrl(figure)}
          alt={figure.caption || `Figure ${figure.figure_num}`}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
        />
        <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/30">
          <AppIcon name="maximize" className="h-5 w-5 text-white opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <div className="absolute left-2 right-2 top-2 flex flex-wrap items-center justify-between gap-2">
          <span className={`badge text-2xs ${badge.classes}`}>
            {badge.label}
          </span>
          <span className={`badge text-2xs ${statusBadge.classes}`}>
            {statusBadge.label}
          </span>
        </div>
      </div>

      <div className="space-y-3 p-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-xs font-semibold text-fg">
              {figure.figure_num || `Figure ${index + 1}`}
            </h4>
            {figure.is_composite && (
              <span className="status-pill border-accent/20 bg-accent/10 text-accent">
                {S.figures.composite}
              </span>
            )}
            {childCount > 0 && (
              <span className="status-pill border-border/50 bg-surface/80 text-fg-secondary">
                {S.figures.childGroup(childCount)}
              </span>
            )}
          </div>
          {figure.caption && (
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-fg-muted">
              {figure.caption}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {confidenceLabel && (
            <span className="status-pill border-accent/20 bg-accent/10 text-accent">
              {S.figures.confidence(confidenceLabel)}
            </span>
          )}
          {figure.classifier_model && (
            <span className="status-pill border-border/50 bg-surface/80 text-fg-secondary">
              {S.figures.provenanceLabel(figure.classifier_model)}
            </span>
          )}
          {figure.resolver_version && (
            <span className="status-pill border-border/50 bg-surface/80 text-fg-muted">
              {figure.resolver_version}
            </span>
          )}
        </div>

        {typeof figure.page_number === 'number' && onJumpToFigurePage && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onJumpToFigurePage(figure);
            }}
            className="btn-secondary w-full text-xs"
          >
            <AppIcon name="arrow-right" className="h-3.5 w-3.5" />
            {S.figures.jumpToPage}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function FigureGallery({
  figures,
  paperId,
  loading = false,
  visualState = 'ready',
  visualError = null,
  artifactsError = null,
  onJumpToFigurePage,
}: FigureGalleryProps) {
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [lightboxVisible, setLightboxVisible] = useState(false);
  const [lightboxClosing, setLightboxClosing] = useState(false);
  const figureGroups = buildFigureGroups(figures);
  const figureCards = figureGroups.flatMap(({ parent, children }, groupIndex) => {
    const parentIndex = Math.max(figures.indexOf(parent), 0);

    return [
      {
        key: parent.id ?? `group-${groupIndex}`,
        figure: parent,
        index: parentIndex,
        childCount: children.length,
      },
      ...children.map((child, childIndex) => ({
        key: child.id ?? `child-${groupIndex}-${childIndex}`,
        figure: child,
        index: Math.max(figures.indexOf(child), 0),
        childCount: 0,
      })),
    ];
  });

  const openLightbox = useCallback((index: number) => {
    setLightboxIndex(index);
    setLightboxVisible(true);
    setLightboxClosing(false);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxClosing(true);
    setTimeout(() => {
      setLightboxVisible(false);
      setLightboxClosing(false);
      setLightboxIndex(null);
    }, 170);
  }, []);

  const prevFigure = useCallback(() => {
    setLightboxIndex((i) => (i !== null && i > 0 ? i - 1 : i));
  }, []);

  const nextFigure = useCallback(() => {
    setLightboxIndex((i) =>
      i !== null && i < figures.length - 1 ? i + 1 : i
    );
  }, [figures.length]);

  useEffect(() => {
    if (lightboxIndex === null) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') prevFigure();
      if (e.key === 'ArrowRight') nextFigure();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [lightboxIndex, prevFigure, nextFigure]);

  const effectiveError = visualError ?? artifactsError;
  const hasArtifactError = visualState === 'error' && Boolean(effectiveError);
  const isPreparingArtifacts = visualState === 'running';
  const isPartialArtifacts = visualState === 'partial';

  if (loading) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
          <AppIcon name="figures" className="w-4 h-4 text-accent" />
          {S.figures.title}
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          <FigureSkeleton />
          <FigureSkeleton />
          <FigureSkeleton />
        </div>
      </div>
    );
  }

  if (figures.length === 0) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
          <AppIcon name="figures" className="w-4 h-4 text-accent" />
          {S.figures.title}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          {isPreparingArtifacts ? (
            <Loader2 className="w-8 h-8 text-accent mb-2 animate-spin" />
          ) : hasArtifactError ? (
            <AppIcon name="error" className="w-8 h-8 text-danger mb-2" />
          ) : isPartialArtifacts ? (
            <AppIcon name="warning" className="w-8 h-8 text-warning mb-2" />
          ) : (
            <AppIcon name="figures" className="w-8 h-8 text-fg-muted mb-2" />
          )}
          <p className="text-sm text-fg-muted">
            {isPreparingArtifacts
              ? S.figures.preparing
              : hasArtifactError
                ? effectiveError
                : isPartialArtifacts
                  ? S.figures.partialWarning
                : S.figures.noFigures}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
        <AppIcon name="figures" className="w-4 h-4 text-accent" />
        {S.figures.title}
        <span className="badge-primary text-2xs ml-1">
          {figures.length}
        </span>
      </h3>

      {hasArtifactError ? (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-danger/20 bg-danger/8 px-3 py-2 text-xs text-danger">
          <AppIcon name="error" className="w-3.5 h-3.5 text-danger" />
          <span>{effectiveError}</span>
        </div>
      ) : isPreparingArtifacts && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/8 px-3 py-2 text-xs text-accent">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-accent" />
          <span>{S.figures.syncing}</span>
        </div>
      )}

      {!hasArtifactError && !isPreparingArtifacts && isPartialArtifacts && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AppIcon name="warning" className="w-3.5 h-3.5 text-warning" />
          <span>{S.figures.partialWarning}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {figureCards.map(({ key, figure, index, childCount }) => (
          <FigureCard
            key={key}
            figure={figure}
            index={index}
            childCount={childCount}
            onOpen={openLightbox}
            onJumpToFigurePage={onJumpToFigurePage}
          />
        ))}
      </div>

      {lightboxVisible && lightboxIndex !== null && (
        <Lightbox
          figures={figures}
          paperId={paperId}
          currentIndex={lightboxIndex}
          isClosing={lightboxClosing}
          onClose={closeLightbox}
          onPrev={prevFigure}
          onNext={nextFigure}
        />
      )}
    </div>
  );
}
