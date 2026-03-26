import { useCallback, useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import * as pdfjsViewer from 'pdfjs-dist/web/pdf_viewer';
import 'pdfjs-dist/web/pdf_viewer.css';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import { ContentState } from '@/components/ui';
import { AppIcon } from '@/components/icons';
import { type PdfNavigationRequest } from '@/lib/api';
import { S } from '@/lib/strings';

const {
  EventBus,
  FindState,
  NullL10n,
  PDFFindController,
  PDFLinkService,
  PDFViewer,
} = pdfjsViewer as typeof pdfjsViewer & {
  EventBus: new () => any;
  FindState: {
    FOUND: number;
    NOT_FOUND: number;
    WRAPPED: number;
    PENDING: number;
  };
  NullL10n: any;
  PDFFindController: new (options: { eventBus: any; linkService: any }) => any;
  PDFLinkService: new (options?: { eventBus: any }) => any;
  PDFViewer: new (options: any) => any;
};

GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface PdfViewerProps {
  pdfUrl: string;
  title?: string;
  navigationRequest?: PdfNavigationRequest | null;
  onPageChange?: (page: number) => void;
}

type ViewerInstances = {
  eventBus: any;
  findController: any;
  linkService: any;
  pdfViewer: any;
};

type MatchCountState = {
  current: number;
  total: number;
};

type ZoomAnchor = {
  clientX: number;
  clientY: number;
  pageNumber: number | null;
  pageXRatio: number;
  pageYRatio: number;
  contentX: number;
  contentY: number;
  offsetX: number;
  offsetY: number;
};

const MIN_ZOOM_SCALE = 0.5;
const MAX_ZOOM_SCALE = 4;
const WHEEL_ZOOM_DELTA_LIMIT = 48;
const WHEEL_ZOOM_SENSITIVITY = 0.004;
const TRACKPAD_WHEEL_ZOOM_SENSITIVITY = 0.0053;
const TRACKPAD_WHEEL_ZOOM_CURVE = 1.06;
const TRACKPAD_PIXEL_DELTA_THRESHOLD = 24;

function clampPage(page: number, totalPages: number): number {
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(page, 1), Math.max(totalPages, 1));
}

function getSearchStatusLabel(state: number | null, total: number): string {
  if (state === FindState.PENDING) {
    return '검색 중';
  }
  if (state === FindState.NOT_FOUND) {
    return '일치 없음';
  }
  if (state === FindState.WRAPPED && total > 0) {
    return '문서 처음부터 다시 찾음';
  }
  if (total > 0) {
    return '검색 결과';
  }
  return '본문 검색';
}

export default function PdfViewer({
  pdfUrl,
  title,
  navigationRequest,
  onPageChange,
}: PdfViewerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const viewerContainerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const pageInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const zoomFrameRef = useRef<number | null>(null);
  const instancesRef = useRef<ViewerInstances | null>(null);
  const documentRef = useRef<PDFDocumentProxy | null>(null);
  const pendingPageRef = useRef(1);
  const committedSearchRef = useRef('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [totalPages, setTotalPages] = useState(0);
  const [scalePercent, setScalePercent] = useState(100);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchState, setSearchState] = useState<number | null>(null);
  const [matchCount, setMatchCount] = useState<MatchCountState>({ current: 0, total: 0 });

  const createZoomAnchor = useCallback(
    (anchorClientPoint: { clientX: number; clientY: number }): ZoomAnchor | undefined => {
      const container = viewerContainerRef.current;
      const viewer = viewerRef.current;
      if (!container || !viewer) return undefined;

      const rect = container.getBoundingClientRect();
      const offsetX = anchorClientPoint.clientX - rect.left;
      const offsetY = anchorClientPoint.clientY - rect.top;
      const anchor: ZoomAnchor = {
        clientX: anchorClientPoint.clientX,
        clientY: anchorClientPoint.clientY,
        pageNumber: null,
        pageXRatio: 0.5,
        pageYRatio: 0.5,
        contentX: container.scrollLeft + offsetX,
        contentY: container.scrollTop + offsetY,
        offsetX,
        offsetY,
      };

      const target = container.ownerDocument.elementFromPoint(
        anchorClientPoint.clientX,
        anchorClientPoint.clientY,
      ) as HTMLElement | null;
      const pageElement = target?.closest('.page') as HTMLElement | null;
      if (!pageElement || !viewer.contains(pageElement)) {
        return anchor;
      }

      const pageNumber = Number.parseInt(pageElement.dataset.pageNumber ?? '', 10);
      if (!Number.isFinite(pageNumber)) {
        return anchor;
      }

      const pageRect = pageElement.getBoundingClientRect();
      anchor.pageNumber = pageNumber;
      anchor.pageXRatio = Math.min(
        1,
        Math.max(0, (anchorClientPoint.clientX - pageRect.left) / Math.max(pageRect.width, 1)),
      );
      anchor.pageYRatio = Math.min(
        1,
        Math.max(0, (anchorClientPoint.clientY - pageRect.top) / Math.max(pageRect.height, 1)),
      );
      return anchor;
    },
    [],
  );

  const scheduleAnchoredScroll = useCallback(
    (previousScale: number, nextScale: number, anchor: ZoomAnchor) => {
      const container = viewerContainerRef.current;
      const viewer = viewerRef.current;
      if (!container) return;
      if (zoomFrameRef.current !== null) {
        cancelAnimationFrame(zoomFrameRef.current);
      }

      zoomFrameRef.current = requestAnimationFrame(() => {
        zoomFrameRef.current = null;

        if (anchor.pageNumber && viewer) {
          const pageElement = viewer.querySelector<HTMLElement>(
            `.page[data-page-number="${anchor.pageNumber}"]`,
          );
          if (pageElement) {
            const pageRect = pageElement.getBoundingClientRect();
            const targetClientX = pageRect.left + pageRect.width * anchor.pageXRatio;
            const targetClientY = pageRect.top + pageRect.height * anchor.pageYRatio;
            container.scrollLeft += targetClientX - anchor.clientX;
            container.scrollTop += targetClientY - anchor.clientY;
            return;
          }
        }

        const ratio = nextScale / previousScale;
        container.scrollLeft = anchor.contentX * ratio - anchor.offsetX;
        container.scrollTop = anchor.contentY * ratio - anchor.offsetY;
      });
    },
    [],
  );

  const applyZoom = useCallback(
    (
      nextScale: number,
      anchorClientPoint?: {
        clientX: number;
        clientY: number;
      },
    ) => {
      const instances = instancesRef.current;
      const container = viewerContainerRef.current;
      if (!instances || !container) return;

      const currentScale = Number(instances.pdfViewer.currentScale) || 1;
      const clampedScale = Math.min(
        MAX_ZOOM_SCALE,
        Math.max(MIN_ZOOM_SCALE, Math.round(nextScale * 100) / 100),
      );

      if (Math.abs(clampedScale - currentScale) < 0.005) {
        return;
      }

      const anchor = anchorClientPoint ? createZoomAnchor(anchorClientPoint) : undefined;

      instances.pdfViewer.currentScale = clampedScale;

      if (anchor) {
        scheduleAnchoredScroll(currentScale, clampedScale, anchor);
      }
    },
    [createZoomAnchor, scheduleAnchoredScroll],
  );

  const zoomAroundViewportCenter = useCallback(
    (scaleFactor: number) => {
      const container = viewerContainerRef.current;
      const instances = instancesRef.current;
      if (!container || !instances) return;
      const rect = container.getBoundingClientRect();
      applyZoom(
        Number(instances.pdfViewer.currentScale || 1) * scaleFactor,
        {
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
        },
      );
    },
    [applyZoom],
  );

  useEffect(() => {
    return () => {
      if (zoomFrameRef.current !== null) {
        cancelAnimationFrame(zoomFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    pendingPageRef.current = 1;
    committedSearchRef.current = '';
    setLoading(true);
    setError(null);
    setCurrentPage(1);
    setPageInput('1');
    setTotalPages(0);
    setScalePercent(100);
    setSearchQuery('');
    setSearchState(null);
    setMatchCount({ current: 0, total: 0 });

    if (!viewerContainerRef.current || !viewerRef.current) {
      return;
    }

    let cancelled = false;
    let loadingTask: ReturnType<typeof getDocument> | null = null;

    const eventBus = new EventBus();
    const linkService = new PDFLinkService({ eventBus });
    const findController = new PDFFindController({ eventBus, linkService });
    const pdfViewer = new PDFViewer({
      container: viewerContainerRef.current,
      viewer: viewerRef.current,
      eventBus,
      findController,
      linkService,
      removePageBorders: true,
      l10n: NullL10n,
    });

    linkService.setViewer(pdfViewer);
    instancesRef.current = {
      eventBus,
      findController,
      linkService,
      pdfViewer,
    };

    const handlePageChanging = (event: { pageNumber: number }) => {
      if (cancelled) return;
      setCurrentPage(event.pageNumber);
      setPageInput(String(event.pageNumber));
      onPageChange?.(event.pageNumber);
    };

    const handleScaleChanging = (event: { scale: number }) => {
      if (cancelled) return;
      setScalePercent(Math.round(event.scale * 100));
    };

    const handlePagesInit = () => {
      if (cancelled) return;
      pdfViewer.currentScaleValue = 'page-width';
      pdfViewer.currentPageNumber = clampPage(pendingPageRef.current, pdfViewer.pagesCount);
    };

    const handleFindControlState = (event: { matchesCount?: MatchCountState; state?: number }) => {
      if (cancelled) return;
      setSearchState(event.state ?? null);
      if (event.matchesCount) {
        setMatchCount(event.matchesCount);
      }
    };

    const handleFindMatchesCount = (event: { matchesCount?: MatchCountState }) => {
      if (cancelled || !event.matchesCount) return;
      setMatchCount(event.matchesCount);
    };

    eventBus.on('pagechanging', handlePageChanging);
    eventBus.on('scalechanging', handleScaleChanging);
    eventBus.on('pagesinit', handlePagesInit);
    eventBus.on('updatefindcontrolstate', handleFindControlState);
    eventBus.on('updatefindmatchescount', handleFindMatchesCount);

    loadingTask = getDocument(pdfUrl);

    loadingTask.promise
      .then((pdfDocument) => {
        if (cancelled) {
          void pdfDocument.destroy();
          return;
        }

        documentRef.current = pdfDocument;
        setTotalPages(pdfDocument.numPages);
        linkService.setDocument(pdfDocument);
        pdfViewer.setDocument(pdfDocument);

        void pdfViewer.onePageRendered?.then(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });
      })
      .catch((loadError: Error) => {
        if (cancelled) return;
        setError(loadError.message || 'PDF 문서를 렌더링하지 못했습니다.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      if (zoomFrameRef.current !== null) {
        cancelAnimationFrame(zoomFrameRef.current);
        zoomFrameRef.current = null;
      }
      eventBus.off('pagechanging', handlePageChanging);
      eventBus.off('scalechanging', handleScaleChanging);
      eventBus.off('pagesinit', handlePagesInit);
      eventBus.off('updatefindcontrolstate', handleFindControlState);
      eventBus.off('updatefindmatchescount', handleFindMatchesCount);
      instancesRef.current = null;
      pdfViewer.cleanup();
      linkService.setDocument(null);
      documentRef.current = null;
      if (viewerRef.current) {
        viewerRef.current.textContent = '';
      }
      void loadingTask?.destroy();
    };
  }, [onPageChange, pdfUrl]);

  useEffect(() => {
    if (!navigationRequest) return;
    pendingPageRef.current = navigationRequest.page;

    const instances = instancesRef.current;
    if (!instances || !documentRef.current) return;

    const nextPage = clampPage(navigationRequest.page, instances.pdfViewer.pagesCount);
    instances.pdfViewer.currentPageNumber = nextPage;
  }, [navigationRequest]);

  useEffect(() => {
    const container = viewerContainerRef.current;
    const root = rootRef.current;
    if (!container || !root) return;

    const handleWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const instances = instancesRef.current;
      if (!instances) return;
      event.preventDefault();
      const deltaMultiplier =
        event.deltaMode === WheelEvent.DOM_DELTA_LINE
          ? 16
          : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
            ? container.clientHeight
            : 1;
      const normalizedDelta = event.deltaY * deltaMultiplier;
      const limitedDelta = Math.max(
        -WHEEL_ZOOM_DELTA_LIMIT,
        Math.min(WHEEL_ZOOM_DELTA_LIMIT, normalizedDelta),
      );
      const isTrackpadLike =
        event.deltaMode === WheelEvent.DOM_DELTA_PIXEL &&
        Math.abs(event.deltaY) <= TRACKPAD_PIXEL_DELTA_THRESHOLD;
      const curvedDelta = isTrackpadLike
        ? Math.sign(limitedDelta) * Math.pow(Math.abs(limitedDelta), TRACKPAD_WHEEL_ZOOM_CURVE)
        : limitedDelta;
      const scaleFactor = Math.exp(
        -curvedDelta *
          (isTrackpadLike ? TRACKPAD_WHEEL_ZOOM_SENSITIVITY : WHEEL_ZOOM_SENSITIVITY),
      );

      applyZoom(
        Number(instances.pdfViewer.currentScale || 1) * scaleFactor,
        { clientX: event.clientX, clientY: event.clientY },
      );
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const instances = instancesRef.current;
      if (!instances) return;
      if (document.activeElement === pageInputRef.current || document.activeElement === searchInputRef.current) {
        return;
      }

      if (event.key === '=' || event.key === '+') {
        event.preventDefault();
        zoomAroundViewportCenter(1.1);
      } else if (event.key === '-' || event.key === '_') {
        event.preventDefault();
        zoomAroundViewportCenter(1 / 1.1);
      } else if (event.key === '0') {
        event.preventDefault();
        instances.pdfViewer.currentScaleValue = 'page-width';
      } else if (event.key.toLowerCase() === 'f') {
        event.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    root.addEventListener('keydown', handleKeyDown);
    return () => {
      container.removeEventListener('wheel', handleWheel);
      root.removeEventListener('keydown', handleKeyDown);
    };
  }, [applyZoom, zoomAroundViewportCenter]);

  const submitPageInput = () => {
    const instances = instancesRef.current;
    if (!instances) return;
    const nextPage = clampPage(Number.parseInt(pageInput, 10), totalPages);
    setPageInput(String(nextPage));
    instances.pdfViewer.currentPageNumber = nextPage;
  };

  const dispatchFind = (type: '' | 'again' = '', findPrevious = false) => {
    const instances = instancesRef.current;
    if (!instances) return;

    const query = (searchQuery.trim() || committedSearchRef.current).trim();
    if (!query) {
      committedSearchRef.current = '';
      setSearchState(null);
      setMatchCount({ current: 0, total: 0 });
      instances.eventBus.dispatch('findbarclose', { source: rootRef.current });
      return;
    }

    committedSearchRef.current = query;
    if (!searchQuery.trim()) {
      setSearchQuery(query);
    }

    instances.eventBus.dispatch('find', {
      source: rootRef.current,
      type,
      query,
      caseSensitive: false,
      entireWord: false,
      findPrevious,
      highlightAll: true,
      matchDiacritics: false,
    });
  };

  const submitSearch = () => {
    dispatchFind('');
  };

  const findPreviousMatch = () => {
    dispatchFind('again', true);
  };

  const findNextMatch = () => {
    dispatchFind('again', false);
  };

  const goToPreviousPage = () => {
    instancesRef.current?.pdfViewer.previousPage();
  };

  const goToNextPage = () => {
    instancesRef.current?.pdfViewer.nextPage();
  };

  const zoomOut = () => {
    zoomAroundViewportCenter(1 / 1.1);
  };

  const zoomIn = () => {
    zoomAroundViewportCenter(1.1);
  };

  const fitWidth = () => {
    if (instancesRef.current?.pdfViewer) {
      instancesRef.current.pdfViewer.currentScaleValue = 'page-width';
    }
  };

  const fitPage = () => {
    if (instancesRef.current?.pdfViewer) {
      instancesRef.current.pdfViewer.currentScaleValue = 'page-fit';
    }
  };

  const searchStatusLabel = getSearchStatusLabel(searchState, matchCount.total);

  return (
    <div
      ref={rootRef}
      className="pdf-viewer-shell flex h-full flex-col bg-surface-950 [.light_&]:bg-white"
      aria-label={title || 'PDF viewer'}
      tabIndex={-1}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-surface-800/80 bg-surface-950/92 px-3 py-2 [.light_&]:border-surface-200/80 [.light_&]:bg-white/92">
        <button
          type="button"
          onClick={goToPreviousPage}
          disabled={currentPage <= 1}
          className="pdf-toolbar-btn"
          aria-label="이전 페이지"
          title="이전 페이지"
        >
          <AppIcon name="chevron-left" className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-2">
          <input
            ref={pageInputRef}
            type="text"
            inputMode="numeric"
            value={pageInput}
            onChange={(event) => setPageInput(event.target.value.replace(/[^\d]/g, ''))}
            onBlur={submitPageInput}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                submitPageInput();
              }
            }}
            className="input h-8 w-14 px-2 py-1 text-center text-xs"
            aria-label="페이지 번호"
          />
          <span className="text-xs font-medium text-surface-400">/ {Math.max(totalPages, 1)}</span>
        </div>

        <button
          type="button"
          onClick={goToNextPage}
          disabled={currentPage >= totalPages}
          className="pdf-toolbar-btn"
          aria-label="다음 페이지"
          title="다음 페이지"
        >
          <AppIcon name="chevron-right" className="h-4 w-4" />
        </button>

        <div className="h-5 w-px bg-surface-800/80 [.light_&]:bg-surface-200/80" />

        <button
          type="button"
          onClick={zoomOut}
          className="pdf-toolbar-btn"
          aria-label="축소"
          title="축소"
        >
          <AppIcon name="minimize" className="h-4 w-4" />
        </button>

        <span className="min-w-[3.5rem] text-center text-xs font-medium text-surface-300">
          {scalePercent}%
        </span>

        <button
          type="button"
          onClick={zoomIn}
          className="pdf-toolbar-btn"
          aria-label="확대"
          title="확대"
        >
          <AppIcon name="plus" className="h-4 w-4" />
        </button>

        <button type="button" onClick={fitWidth} className="pdf-toolbar-btn px-3 text-xs">
          너비 맞춤
        </button>

        <button type="button" onClick={fitPage} className="pdf-toolbar-btn px-3 text-xs">
          페이지 맞춤
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-surface-800/80 bg-surface-950/88 px-3 py-2 [.light_&]:border-surface-200/80 [.light_&]:bg-white/90">
        <div className="relative min-w-[14rem] flex-1">
          <AppIcon
            name="search"
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-surface-500"
          />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                if (event.shiftKey) {
                  findPreviousMatch();
                } else {
                  submitSearch();
                }
              }
            }}
            placeholder="본문 검색"
            className="input h-8 w-full pl-9 pr-3 text-xs"
            aria-label="PDF 본문 검색"
          />
        </div>

        <button type="button" onClick={submitSearch} className="pdf-toolbar-btn px-3 text-xs">
          검색
        </button>

        <button
          type="button"
          onClick={findPreviousMatch}
          disabled={!searchQuery.trim() && !committedSearchRef.current}
          className="pdf-toolbar-btn"
          aria-label="이전 검색 결과"
          title="이전 검색 결과"
        >
          <AppIcon name="chevron-left" className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={findNextMatch}
          disabled={!searchQuery.trim() && !committedSearchRef.current}
          className="pdf-toolbar-btn"
          aria-label="다음 검색 결과"
          title="다음 검색 결과"
        >
          <AppIcon name="chevron-right" className="h-4 w-4" />
        </button>

        <div className="min-w-[7rem] text-right text-xs font-medium text-surface-400">
          {matchCount.total > 0 ? `${matchCount.current} / ${matchCount.total}` : searchStatusLabel}
        </div>
      </div>

      <div className="min-h-0 flex flex-1 overflow-hidden bg-[#09090b] [.light_&]:bg-white">
        <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          <div ref={viewerContainerRef} className="pdfjs-viewer-container absolute inset-0 h-full overflow-auto">
            <div ref={viewerRef} className="pdfViewer pdfjs-viewer-pages" />
          </div>

          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
              <ContentState
                icon={(props) => <AppIcon name="library" {...props} />}
                title={S.pdf.loading}
                description="문서 뷰어를 준비하고 있습니다."
                loading
                tone="muted"
              />
            </div>
          )}

          {error && (
            <div className="absolute inset-0 z-20 flex items-center justify-center p-6">
              <ContentState
                icon={(props) => <AppIcon name="library" {...props} />}
                title={S.pdf.loadFailed}
                description={error}
                tone="error"
              />
            </div>
          )}
        </div>

        <noscript>
          <div className="flex h-full items-center justify-center p-6">
            <ContentState
              icon={(props) => <AppIcon name="library" {...props} />}
              title={S.pdf.loadFailed}
              description="PDF 보기를 위해 JavaScript가 필요합니다."
              tone="error"
            />
          </div>
        </noscript>
      </div>
    </div>
  );
}
