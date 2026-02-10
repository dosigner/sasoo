import { useState, useCallback, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  X,
  ChevronLeft,
  ChevronRight,
  ImageIcon,
  Maximize2,
  Loader2,
  BookOpen,
  Sparkles,
} from 'lucide-react';
import type { Figure } from '@/lib/api';
import { generateFigureExplanation } from '@/lib/api';
import { useFocusTrap } from '@/hooks/useFocusTrap';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FigureGalleryProps {
  figures: Figure[];
  paperId: string;
  loading?: boolean;
}

interface CachedExplanation {
  explanation: string;
  modelUsed: string;
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
      return { label: 'High', classes: 'bg-emerald-500/10 text-emerald-400' };
    case 'medium':
      return { label: 'Medium', classes: 'bg-amber-500/10 text-amber-400' };
    case 'low':
      return { label: 'Low', classes: 'bg-red-500/10 text-red-400' };
    default:
      return { label: 'Unknown', classes: 'bg-surface-500/10 text-surface-400' };
  }
}

/** Build a URL for a figure's image from its file_path */
function getFigureImageUrl(figure: Figure): string {
  if (!figure.file_path) return '';
  // Normalize backslashes to forward slashes (Windows paths)
  const normalized = figure.file_path.replace(/\\/g, '/');
  // Extract path relative to library root: {folder}/figures/{filename}
  const libraryIdx = normalized.indexOf('/library/');
  if (libraryIdx >= 0) {
    const relative = normalized.substring(libraryIdx + '/library/'.length);
    // In Electron production (file:// protocol), use absolute backend URL
    const isFileProtocol = typeof window !== 'undefined' && window.location.protocol === 'file:';
    const baseUrl = isFileProtocol ? 'http://localhost:8000' : '';
    return `${baseUrl}/static/library/${encodeURI(relative)}`;
  }
  return figure.file_path;
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function FigureSkeleton() {
  return (
    <div className="card p-0 overflow-hidden animate-pulse">
      <div className="aspect-[4/3] bg-surface-700" />
      <div className="p-3 space-y-2">
        <div className="h-3 bg-surface-700 rounded w-3/4" />
        <div className="h-3 bg-surface-700 rounded w-1/2" />
      </div>
    </div>
  );
}

function ExplanationSkeleton() {
  return (
    <div className="space-y-4 animate-pulse p-6">
      <div className="flex items-center gap-2 mb-6">
        <div className="w-5 h-5 bg-primary-500/20 rounded" />
        <div className="h-5 bg-surface-700 rounded w-48" />
      </div>
      <div className="space-y-3">
        <div className="h-4 bg-surface-700 rounded w-full" />
        <div className="h-4 bg-surface-700 rounded w-5/6" />
        <div className="h-4 bg-surface-700 rounded w-4/5" />
      </div>
      <div className="h-5 bg-surface-700 rounded w-36 mt-6" />
      <div className="space-y-3">
        <div className="h-4 bg-surface-700 rounded w-full" />
        <div className="h-4 bg-surface-700 rounded w-11/12" />
        <div className="h-4 bg-surface-700 rounded w-4/5" />
        <div className="h-4 bg-surface-700 rounded w-full" />
        <div className="h-4 bg-surface-700 rounded w-3/4" />
      </div>
      <div className="h-5 bg-surface-700 rounded w-44 mt-6" />
      <div className="space-y-3">
        <div className="h-4 bg-surface-700 rounded w-full" />
        <div className="h-4 bg-surface-700 rounded w-5/6" />
        <div className="h-4 bg-surface-700 rounded w-full" />
        <div className="h-4 bg-surface-700 rounded w-2/3" />
      </div>
      <div className="flex items-center gap-2 mt-8 text-surface-500">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-xs">AI가 그림을 분석하고 있습니다...</span>
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
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}

function Lightbox({
  figures,
  paperId,
  currentIndex,
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
        setError(err.message || '설명을 생성하지 못했습니다.');
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
        className="absolute inset-0 bg-black/60 backdrop-blur-md"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Centered modal card */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={`그림 상세 보기: ${figure.figure_num || 'Figure'}`}
        className="figure-modal relative z-10 flex w-full max-w-[90vw] h-[85vh] bg-surface-900 border border-surface-700/60 rounded-2xl shadow-2xl overflow-hidden"
      >
        {/* Header bar */}
        <div className="figure-modal-header absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-4 bg-surface-900/95 backdrop-blur border-b border-surface-700/50 z-10">
          <div className="flex items-center gap-3">
            <h4 className="text-sm font-semibold text-surface-200 flex items-center gap-2">
              <ImageIcon className="w-4 h-4 text-primary-400" />
              {figure.figure_num || 'Figure'}
            </h4>
            <span className={`badge text-2xs ${badge.classes}`}>
              {badge.label}
            </span>
            {figure.caption && (
              <span className="text-2xs text-surface-500 truncate max-w-[300px] hidden lg:inline">
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
                className="p-1.5 rounded-md text-surface-400 hover:text-white hover:bg-surface-700 transition-colors disabled:opacity-30 disabled:pointer-events-none"
                aria-label="이전 그림"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-2xs text-surface-500 tabular-nums min-w-[36px] text-center">
                {currentIndex + 1} / {figures.length}
              </span>
              <button
                onClick={onNext}
                disabled={currentIndex >= figures.length - 1}
                className="p-1.5 rounded-md text-surface-400 hover:text-white hover:bg-surface-700 transition-colors disabled:opacity-30 disabled:pointer-events-none"
                aria-label="다음 그림"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            {/* Close */}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-surface-400 hover:text-white hover:bg-surface-700 transition-colors"
              aria-label="닫기"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body – two panels below header */}
        <div className="flex w-full h-full pt-12">
          {/* LEFT: Image */}
          <div className="figure-modal-image w-[45%] flex-shrink-0 flex flex-col items-center justify-center p-6 bg-surface-950/50 min-w-0">
            <div className="flex-1 flex items-center justify-center w-full overflow-hidden">
              <img
                src={getFigureImageUrl(figure)}
                alt={figure.caption || `Figure ${figure.figure_num}`}
                className="max-w-full max-h-full object-contain rounded-lg"
              />
            </div>
            {figure.caption && (
              <p className="mt-3 text-xs text-surface-400 leading-relaxed text-center max-w-md line-clamp-3 lg:line-clamp-none">
                {figure.caption}
              </p>
            )}
          </div>

          {/* Divider */}
          <div className="figure-modal-divider w-px bg-surface-700/40 flex-shrink-0" />

          {/* RIGHT: Explanation */}
          <div
            ref={rightPanelRef}
            className="flex-1 overflow-y-auto min-w-0 figure-explanation-panel"
          >
            {isLoading ? (
              <ExplanationSkeleton />
            ) : error ? (
              <div className="flex flex-col items-center justify-center h-full text-center p-8">
                <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mb-4">
                  <X className="w-6 h-6 text-red-400" />
                </div>
                <p className="text-sm text-surface-300 mb-2">설명 생성 실패</p>
                <p className="text-xs text-surface-500 mb-4">{error}</p>
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
                          setError(err.message || '설명을 생성하지 못했습니다.');
                          setLoadingId(null);
                        });
                    }
                  }}
                  className="btn-secondary text-xs"
                  aria-label="다시 시도"
                >
                  다시 시도
                </button>
              </div>
            ) : cached ? (
              <div className="p-6">
                <div className="flex items-center gap-2 mb-5 pb-3 border-b border-surface-700/50">
                  <Sparkles className="w-4 h-4 text-primary-400" />
                  <h3 className="text-sm font-semibold text-surface-200">
                    전문가 상세 설명
                  </h3>
                  {cached.modelUsed && cached.modelUsed !== 'cached' && (
                    <span className="badge text-2xs bg-primary-500/10 text-primary-400 ml-auto">
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
                <BookOpen className="w-10 h-10 text-surface-600 mb-3" />
                <p className="text-sm text-surface-400">
                  그림을 클릭하면 AI 전문가가 상세한 설명을 생성합니다.
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
// Main Component
// ---------------------------------------------------------------------------

export default function FigureGallery({
  figures,
  paperId,
  loading = false,
}: FigureGalleryProps) {
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  const openLightbox = useCallback((index: number) => {
    setLightboxIndex(index);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxIndex(null);
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

  if (loading) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-primary-400" />
          Extracted Figures
        </h3>
        <div className="grid grid-cols-3 2xl:grid-cols-4 gap-3">
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
        <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-primary-400" />
          Extracted Figures
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <ImageIcon className="w-8 h-8 text-surface-600 mb-2" />
          <p className="text-sm text-surface-400">
            No figures extracted from this paper.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
        <ImageIcon className="w-4 h-4 text-primary-400" />
        Extracted Figures
        <span className="badge-primary text-2xs ml-1">
          {figures.length}
        </span>
      </h3>

      <div className="grid grid-cols-3 2xl:grid-cols-4 gap-3">
        {figures.map((figure, index) => {
          const badge = qualityBadge(figure.quality);

          return (
            <div
              key={figure.id ?? index}
              className="card-hover p-0 overflow-hidden cursor-pointer group"
              role="button"
              tabIndex={0}
              onClick={() => openLightbox(index)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  openLightbox(index);
                }
              }}
              aria-label={`${figure.figure_num || 'Figure'} 상세 보기`}
            >
              <div className="relative aspect-[4/3] bg-surface-700 overflow-hidden">
                <img
                  src={getFigureImageUrl(figure)}
                  alt={figure.caption || `Figure ${figure.figure_num}`}
                  className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
                  <Maximize2 className="w-5 h-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <span className={`absolute top-2 right-2 badge text-2xs ${badge.classes}`}>
                  {badge.label}
                </span>
              </div>

              <div className="p-3">
                <h4 className="text-xs font-medium text-surface-200 mb-1">
                  {figure.figure_num || 'Figure'}
                </h4>
                {figure.caption && (
                  <p className="text-2xs text-surface-400 line-clamp-2">
                    {figure.caption}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {lightboxIndex !== null && (
        <Lightbox
          figures={figures}
          paperId={paperId}
          currentIndex={lightboxIndex}
          onClose={closeLightbox}
          onPrev={prevFigure}
          onNext={nextFigure}
        />
      )}
    </div>
  );
}
