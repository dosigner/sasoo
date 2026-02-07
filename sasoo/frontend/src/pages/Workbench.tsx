import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import {
  Play,
  Loader2,
  AlertCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { getPaper, getPdfUrl, type Paper } from '@/lib/api';
import { useAnalysis } from '@/hooks/useAnalysis';
import PdfViewer from '@/components/PdfViewer';
import AnalysisPanel from '@/components/AnalysisPanel';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_PANEL_WIDTH = 20; // percent
const MAX_PANEL_WIDTH = 80; // percent
const DEFAULT_SPLIT = 50; // percent

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Workbench() {
  const { id } = useParams<{ id: string }>();

  // Paper data
  const [paper, setPaper] = useState<Paper | null>(null);
  const [paperLoading, setPaperLoading] = useState(true);
  const [paperError, setPaperError] = useState<string | null>(null);

  // Analysis hook
  const {
    status,
    results,
    figures,
    recipe,
    mermaid,
    visualizations,
    isRunning,
    error: analysisError,
    startAnalysis,
  } = useAnalysis(id);

  // Split view
  const [splitPosition, setSplitPosition] = useState(DEFAULT_SPLIT);
  const [isResizing, setIsResizing] = useState(false);
  const [pdfCollapsed, setPdfCollapsed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // -----------------------------------------------------------------------
  // Load paper data
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!id) return;

    let cancelled = false;

    async function loadPaper() {
      setPaperLoading(true);
      setPaperError(null);
      try {
        const p = await getPaper(id!);
        if (!cancelled) setPaper(p);
      } catch (err) {
        if (!cancelled) {
          setPaperError(
            err instanceof Error ? err.message : 'Failed to load paper'
          );
        }
      } finally {
        if (!cancelled) setPaperLoading(false);
      }
    }

    loadPaper();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // -----------------------------------------------------------------------
  // Auto-start analysis for newly uploaded papers
  // -----------------------------------------------------------------------
  const autoStartedRef = useRef(false);

  useEffect(() => {
    if (
      paper &&
      paper.status === 'pending' &&
      !isRunning &&
      !status &&
      !autoStartedRef.current
    ) {
      autoStartedRef.current = true;
      startAnalysis();
    }
  }, [paper, isRunning, status, startAnalysis]);

  // Reset auto-start flag when paper id changes
  useEffect(() => {
    autoStartedRef.current = false;
  }, [id]);

  // -----------------------------------------------------------------------
  // Resize handlers
  // -----------------------------------------------------------------------
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsResizing(true);
      document.body.classList.add('resizing');

      const container = containerRef.current;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const relativeX = moveEvent.clientX - containerRect.left;
        const percentage = (relativeX / containerRect.width) * 100;
        const clamped = Math.max(
          MIN_PANEL_WIDTH,
          Math.min(MAX_PANEL_WIDTH, percentage)
        );
        setSplitPosition(clamped);
      };

      const handleMouseUp = () => {
        setIsResizing(false);
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    []
  );

  const togglePdf = useCallback(() => {
    setPdfCollapsed((c) => !c);
  }, []);

  // -----------------------------------------------------------------------
  // Loading / error states
  // -----------------------------------------------------------------------
  if (paperLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-primary-400 animate-spin" />
          <span className="text-sm text-surface-400">Loading paper...</span>
        </div>
      </div>
    );
  }

  if (paperError || !paper) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3 text-center px-8">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <h2 className="text-lg font-semibold text-surface-200">
            Failed to Load Paper
          </h2>
          <p className="text-sm text-surface-400 max-w-sm">
            {paperError || 'Paper not found.'}
          </p>
        </div>
      </div>
    );
  }

  const pdfUrl = getPdfUrl(String(paper.id));
  const canStartAnalysis =
    !isRunning && (paper.status === 'pending' || paper.status === 'completed' || paper.status === 'error');

  return (
    <div className="flex flex-col h-full">
      {/* Top bar: paper info + controls */}
      <div className="flex items-center justify-between px-4 py-2 bg-surface-800 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={togglePdf}
            className="btn-ghost p-1.5 rounded-md shrink-0"
            title={pdfCollapsed ? 'Show PDF' : 'Hide PDF'}
            aria-label={pdfCollapsed ? 'PDF 표시' : 'PDF 숨기기'}
            aria-expanded={!pdfCollapsed}
          >
            {pdfCollapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </button>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-surface-200 truncate">
              {paper.title}
            </h1>
            <div className="flex items-center gap-2 text-2xs text-surface-500">
              {paper.authors && (
                <span className="truncate max-w-[300px]">
                  {paper.authors}
                </span>
              )}
              {paper.year && (
                <>
                  <span className="w-1 h-1 rounded-full bg-surface-600" />
                  <span>{paper.year}</span>
                </>
              )}
              <span className="w-1 h-1 rounded-full bg-surface-600" />
              <span className="badge-primary text-2xs">{paper.domain}</span>
            </div>
          </div>
        </div>

        {/* Analysis button */}
        <div className="flex items-center gap-2 shrink-0">
          {analysisError && (
            <span className="text-2xs text-red-400 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {analysisError}
            </span>
          )}
          {canStartAnalysis && (
            <button
              onClick={startAnalysis}
              className="btn-primary text-xs py-1.5 px-4"
            >
              <Play className="w-3.5 h-3.5" />
              {paper.status === 'completed' ? 'Re-analyze' : 'Start Analysis'}
            </button>
          )}
          {isRunning && (
            <div className="flex items-center gap-2 text-xs text-primary-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Analyzing...</span>
            </div>
          )}
        </div>
      </div>

      {/* Split view */}
      <div ref={containerRef} className="flex flex-1 min-h-0">
        {/* Left panel: PDF */}
        {!pdfCollapsed && (
          <div
            className="h-full overflow-hidden"
            style={{ width: `${splitPosition}%` }}
          >
            <PdfViewer pdfUrl={pdfUrl} title={paper.title} />
          </div>
        )}

        {/* Resize handle */}
        {!pdfCollapsed && (
          <div
            onMouseDown={handleMouseDown}
            className={`resize-handle shrink-0 ${
              isResizing ? 'bg-primary-500' : ''
            }`}
          />
        )}

        {/* Right panel: Analysis */}
        <div
          className="flex flex-col h-full overflow-hidden bg-surface-900"
          style={{
            width: pdfCollapsed ? '100%' : `${100 - splitPosition}%`,
          }}
        >
          <AnalysisPanel
            status={status}
            results={results}
            figures={figures}
            recipe={recipe}
            mermaid={mermaid}
            visualizations={visualizations}
            isRunning={isRunning}
            paperId={id}
          />
        </div>
      </div>
    </div>
  );
}
