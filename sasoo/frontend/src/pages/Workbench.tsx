import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import {
  Play,
  Loader2,
  AlertCircle,
  PanelLeftClose,
  PanelLeftOpen,
  PanelLeft,
  Columns2,
  PanelRight,
  Square,
} from 'lucide-react';
import { getPaper, getPdfUrl, cancelAnalysis, type Paper } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';
import { useAnalysis } from '@/hooks/useAnalysis';
import PdfViewer from '@/components/PdfViewer';
import AnalysisPanel from '@/components/AnalysisPanel';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_PANEL_WIDTH = 20; // percent
const MAX_PANEL_WIDTH = 80; // percent
const DEFAULT_SPLIT = 50; // percent

const SNAP_POINTS = [25, 33, 50, 67, 75]; // percent
const SNAP_THRESHOLD = 2; // percent - magnetic snap distance
const KEYBOARD_STEP = 5; // percent per arrow key press

const PRESETS = [
  { label: 'PDF 중심', icon: PanelLeft, value: 70 },
  { label: '균등', icon: Columns2, value: 50 },
  { label: '분석 중심', icon: PanelRight, value: 30 },
] as const;

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
  const [isSnapping, setIsSnapping] = useState(false);

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
  // Snap to nearest snap point if within threshold
  const snapToNearest = useCallback((value: number): number => {
    for (const point of SNAP_POINTS) {
      if (Math.abs(value - point) <= SNAP_THRESHOLD) {
        setIsSnapping(true);
        return point;
      }
    }
    setIsSnapping(false);
    return value;
  }, []);

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
        setSplitPosition(snapToNearest(clamped));
      };

      const handleMouseUp = () => {
        setIsResizing(false);
        setIsSnapping(false);
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [snapToNearest]
  );

  const togglePdf = useCallback(() => {
    setPdfCollapsed((c) => !c);
  }, []);

  // Double-click to reset to default
  const handleDoubleClick = useCallback(() => {
    setSplitPosition(DEFAULT_SPLIT);
  }, []);

  // Keyboard resize support
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      let newPos = splitPosition;
      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          newPos = Math.max(MIN_PANEL_WIDTH, splitPosition - KEYBOARD_STEP);
          break;
        case 'ArrowRight':
          e.preventDefault();
          newPos = Math.min(MAX_PANEL_WIDTH, splitPosition + KEYBOARD_STEP);
          break;
        case 'Home':
          e.preventDefault();
          newPos = MIN_PANEL_WIDTH;
          break;
        case 'End':
          e.preventDefault();
          newPos = MAX_PANEL_WIDTH;
          break;
        default:
          return;
      }
      setSplitPosition(snapToNearest(newPos));
    },
    [splitPosition, snapToNearest]
  );

  // Find closest preset for highlighting
  const activePreset = PRESETS.find(
    (p) => Math.abs(p.value - splitPosition) < 3
  );

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
      <div className="flex items-center justify-between px-4 py-2 bg-surface-800/90 backdrop-blur-lg border-b border-surface-700/50 shrink-0">
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
              {(() => {
                const agent = getAgentMeta(paper.agent_used);
                if (!agent) return null;
                return (
                  <img
                    src={agent.image}
                    alt={agent.name}
                    className="w-5 h-5 rounded-full object-cover"
                    title={`${agent.name} — ${agent.personality}`}
                  />
                );
              })()}
            </div>
          </div>
        </div>

        {/* Preset buttons + Analysis button */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Split presets (only when PDF visible) */}
          {!pdfCollapsed && (
            <div className="flex items-center gap-0.5 mr-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => setSplitPosition(preset.value)}
                  className={`p-1.5 rounded-md transition-colors duration-150 ${
                    activePreset?.value === preset.value
                      ? 'bg-primary-500/20 text-primary-400'
                      : 'text-surface-400 hover:text-surface-200 hover:bg-surface-700'
                  }`}
                  title={`${preset.label} (${preset.value}:${100 - preset.value})`}
                >
                  <preset.icon className="w-3.5 h-3.5" />
                </button>
              ))}
            </div>
          )}
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
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 text-xs text-primary-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Analyzing... {status?.progress_pct ? `${Math.round(status.progress_pct)}%` : ''}</span>
              </div>
              <button
                onClick={async () => {
                  try {
                    await cancelAnalysis(id!);
                  } catch {
                    // Cancel may fail if already completed
                  }
                }}
                className="btn-ghost text-xs py-1 px-2 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                title="분석 취소"
              >
                <Square className="w-3 h-3" />
                취소
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Split view */}
      <div ref={containerRef} className="flex flex-1 min-h-0">
        {/* Left panel: PDF */}
        {!pdfCollapsed && (
          <div
            className="h-full overflow-hidden relative"
            style={{ width: `${splitPosition}%` }}
          >
            <PdfViewer pdfUrl={pdfUrl} title={paper.title} />
            {/* Transparent overlay to prevent iframe from stealing mouse events during resize */}
            {isResizing && (
              <div className="absolute inset-0 z-10" />
            )}
          </div>
        )}

        {/* Resize handle */}
        {!pdfCollapsed && (
          <div
            role="separator"
            tabIndex={0}
            aria-valuenow={Math.round(splitPosition)}
            aria-valuemin={MIN_PANEL_WIDTH}
            aria-valuemax={MAX_PANEL_WIDTH}
            aria-label="패널 크기 조절"
            onMouseDown={handleMouseDown}
            onDoubleClick={handleDoubleClick}
            onKeyDown={handleKeyDown}
            className={`resize-handle ${
              isResizing ? 'active' : ''
            } ${isSnapping ? 'snapping' : ''}`}
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
            agentName={paper?.agent_used}
            paperId={id}
          />
        </div>
      </div>
    </div>
  );
}
