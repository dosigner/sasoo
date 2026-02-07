import { useState, useCallback, useEffect } from 'react';
import {
  ZoomIn,
  ZoomOut,
  RotateCw,
  ChevronLeft,
  ChevronRight,
  Maximize2,
  Minimize2,
  FileText,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PdfViewerProps {
  /** URL to serve the PDF */
  pdfUrl: string;
  /** Paper title for display */
  title?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PdfViewer({ pdfUrl, title }: PdfViewerProps) {
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // Fallback: hide loading overlay after timeout (iframe onLoad is unreliable for PDFs)
  useEffect(() => {
    if (isLoading) {
      const timer = setTimeout(() => {
        setIsLoading(false);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [isLoading, pdfUrl]);

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(z + 25, 300));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(z - 25, 50));
  }, []);

  const resetZoom = useCallback(() => {
    setZoom(100);
  }, []);

  const prevPage = useCallback(() => {
    setCurrentPage((p) => Math.max(p - 1, 1));
  }, []);

  const nextPage = useCallback(() => {
    if (totalPages) {
      setCurrentPage((p) => Math.min(p + 1, totalPages));
    }
  }, [totalPages]);

  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((f) => !f);
  }, []);

  // Build iframe URL with page and zoom parameters
  // Most PDF viewers in browsers support #page=N&zoom=N
  const iframeSrc = `${pdfUrl}#page=${currentPage}&zoom=${zoom}`;

  return (
    <div
      className={`flex flex-col h-full ${
        isFullscreen ? 'fixed inset-0 z-50 bg-surface-900' : ''
      }`}
    >
      {/* Toolbar */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-surface-800 border-b border-surface-700 shrink-0"
        role="toolbar"
        aria-label="PDF 도구"
      >
        <div className="flex items-center gap-1.5 min-w-0">
          <FileText className="w-4 h-4 text-surface-400 shrink-0" />
          {title && (
            <span className="text-xs text-surface-300 truncate max-w-[200px]">
              {title}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* Zoom controls */}
          <button
            onClick={zoomOut}
            className="btn-ghost p-1.5 rounded-md"
            title="Zoom out"
            aria-label="축소"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={resetZoom}
            className="btn-ghost px-2 py-1 rounded-md text-xs font-mono tabular-nums min-w-[48px]"
            title="Reset zoom"
          >
            {zoom}%
          </button>
          <button
            onClick={zoomIn}
            className="btn-ghost p-1.5 rounded-md"
            title="Zoom in"
            aria-label="확대"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>

          <div className="w-px h-4 bg-surface-600 mx-1" />

          {/* Page navigation */}
          <button
            onClick={prevPage}
            disabled={currentPage <= 1}
            className="btn-ghost p-1.5 rounded-md"
            title="Previous page"
            aria-label="이전 페이지"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <div className="flex items-center gap-1 text-xs text-surface-300">
            <input
              type="number"
              min={1}
              max={totalPages || undefined}
              value={currentPage}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                if (val >= 1 && (!totalPages || val <= totalPages)) {
                  setCurrentPage(val);
                }
              }}
              className="w-10 text-center bg-surface-700 border border-surface-600 rounded px-1 py-0.5 text-xs text-surface-200 focus:outline-none focus:border-primary-500"
            />
            {totalPages && (
              <span className="text-surface-500">/ {totalPages}</span>
            )}
          </div>
          <button
            onClick={nextPage}
            disabled={totalPages !== null && currentPage >= totalPages}
            className="btn-ghost p-1.5 rounded-md"
            title="Next page"
            aria-label="다음 페이지"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>

          <div className="w-px h-4 bg-surface-600 mx-1" />

          {/* Fullscreen */}
          <button
            onClick={toggleFullscreen}
            className="btn-ghost p-1.5 rounded-md"
            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            aria-label={isFullscreen ? '전체화면 종료' : '전체화면'}
            aria-expanded={isFullscreen}
          >
            {isFullscreen ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* PDF content */}
      <div className="flex-1 relative overflow-hidden bg-surface-950">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-900/80 z-10">
            <div className="flex flex-col items-center gap-3">
              <RotateCw className="w-6 h-6 text-primary-400 animate-spin" />
              <span className="text-sm text-surface-400">
                Loading PDF...
              </span>
            </div>
          </div>
        )}

        {loadError && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-900/80 z-10">
            <div className="flex flex-col items-center gap-3 text-center px-8">
              <FileText className="w-10 h-10 text-surface-500" />
              <div>
                <p className="text-sm text-surface-300 mb-1">
                  Unable to load PDF
                </p>
                <p className="text-xs text-surface-500">
                  The file may be corrupted or the server is unavailable.
                </p>
              </div>
              <button
                onClick={() => {
                  setLoadError(false);
                  setIsLoading(true);
                }}
                className="btn-secondary text-xs mt-2"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        <iframe
          src={iframeSrc}
          className="w-full h-full border-0"
          title="PDF Viewer"
          onLoad={() => {
            setIsLoading(false);
            setLoadError(false);
            // Try to read page count from the iframe's content
            // This is a best-effort approach; real PDF.js would be better
            try {
              const iframe = document.querySelector(
                'iframe[title="PDF Viewer"]'
              ) as HTMLIFrameElement;
              if (iframe?.contentDocument) {
                const pageCountEl =
                  iframe.contentDocument.querySelector('#numPages');
                if (pageCountEl?.textContent) {
                  const match = pageCountEl.textContent.match(/(\d+)/);
                  if (match) setTotalPages(parseInt(match[1], 10));
                }
              }
            } catch {
              // Cross-origin restriction; page count unavailable
            }
          }}
          onError={() => {
            setIsLoading(false);
            setLoadError(true);
          }}
        />
      </div>
    </div>
  );
}
