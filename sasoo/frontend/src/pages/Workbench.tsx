import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Play,
  Loader2,
  AlertCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Square,
  ArrowLeft,
} from 'lucide-react';
import {
  getPaper,
  getPdfUrl,
  cancelAnalysis,
  getSettings,
  type Paper,
  type PaperBananaProfile,
  type PdfNavigationRequest,
} from '@/lib/api';
import { useAnalysis } from '@/hooks/useAnalysis';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { buildChatStarterPrompts } from '@/lib/workbenchSummaries';
import PdfViewer from '@/components/PdfViewer';
import AnalysisPanel from '@/components/AnalysisPanel';
import ChatPanel from '@/components/ChatPanel';
import ChatComposerFab from '@/components/ChatComposerFab';
import { ContentState, Modal } from '@/components/ui';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_PANEL_WIDTH = 20; // percent
const MAX_PANEL_WIDTH = 80; // percent
const DEFAULT_SPLIT = 50; // percent

const SNAP_POINTS = [25, 33, 50, 67, 75]; // percent
const SNAP_THRESHOLD = 2; // percent - magnetic snap distance
const KEYBOARD_STEP = 5; // percent per arrow key press
const ANALYSIS_PROFILE_OPTIONS: PaperBananaProfile[] = ['fast', 'balanced', 'quality'];

type AnalysisProfileSelection = 'default' | PaperBananaProfile;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Workbench() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

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
  const [navigationRequest, setNavigationRequest] = useState<PdfNavigationRequest | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMinimized, setChatMinimized] = useState(false);
  const [chatDraft, setChatDraft] = useState('');

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
          if (err instanceof Error) console.warn('[workbench] load error:', err.message);
          setPaperError(S.workbench.loadFailed);
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
  // Auto-start analysis (with optional confirmation dialog)
  // -----------------------------------------------------------------------
  const autoStartedRef = useRef(false);
  const [showAnalysisConfirm, setShowAnalysisConfirm] = useState(false);
  const [defaultPaperBananaProfile, setDefaultPaperBananaProfile] = useState<PaperBananaProfile>('fast');
  const [analysisProfileSelection, setAnalysisProfileSelection] = useState<AnalysisProfileSelection>('default');

  const getProfileLabel = useCallback((profile: PaperBananaProfile) => {
    if (profile === 'fast') return S.settings.profileFast;
    if (profile === 'balanced') return S.settings.profileBalanced;
    return S.settings.profileQuality;
  }, []);

  const openAnalysisConfirm = useCallback(() => {
    setAnalysisProfileSelection('default');
    setShowAnalysisConfirm(true);
  }, []);

  const handleStartAnalysis = useCallback(async (
    selection: AnalysisProfileSelection = analysisProfileSelection
  ) => {
    const effectiveProfile =
      selection === 'default' ? defaultPaperBananaProfile : selection;
    setShowAnalysisConfirm(false);
    await startAnalysis({ paperbanana_profile: effectiveProfile });
  }, [analysisProfileSelection, defaultPaperBananaProfile, startAnalysis]);

  useEffect(() => {
    if (
      paper &&
      paper.status === 'pending' &&
      !isRunning &&
      !status &&
      !autoStartedRef.current
    ) {
      autoStartedRef.current = true;
      // Check auto_analyze setting
      getSettings()
        .then((settings) => {
          setDefaultPaperBananaProfile(settings.paperbanana_profile || 'fast');
          if (settings.auto_analyze) {
            startAnalysis({
              paperbanana_profile: settings.paperbanana_profile || 'fast',
            });
          } else {
            openAnalysisConfirm();
          }
        })
        .catch(() => {
          // If settings fetch fails, show dialog as safe default
          openAnalysisConfirm();
        });
    }
  }, [paper, isRunning, openAnalysisConfirm, startAnalysis, status]);

  // Reset auto-start flag when paper id changes
  useEffect(() => {
    autoStartedRef.current = false;
    setShowAnalysisConfirm(false);
  }, [id]);

  useEffect(() => {
    let cancelled = false;

    getSettings()
      .then((settings) => {
        if (!cancelled) {
          setDefaultPaperBananaProfile(settings.paperbanana_profile || 'fast');
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
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
  // -----------------------------------------------------------------------
  // Loading / error states
  // -----------------------------------------------------------------------
  if (paperLoading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <ContentState
          icon={Loader2}
          title={S.workbench.loading}
          description="논문 메타데이터와 분석 워크벤치를 준비하고 있습니다."
          loading
          tone="muted"
        />
      </div>
    );
  }

  if (paperError || !paper) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <ContentState
          icon={AlertCircle}
          title={S.workbench.loadFailed}
          description={paperError || S.workbench.notFound}
          tone="error"
        />
      </div>
    );
  }

  const pdfUrl = getPdfUrl(String(paper.id));
  const canStartAnalysis =
    !isRunning && (paper.status === 'pending' || paper.status === 'completed' || paper.status === 'error');
  const screeningCompleted = status?.phases.some((phase) => phase.phase === 'screening' && phase.status === 'completed') ?? false;
  const chatStarters = buildChatStarterPrompts({
    results,
    figures: figures?.figures ?? [],
    recipe,
  });

  return (
    <div className="flex flex-col h-full">
      {/* Analysis confirmation dialog */}
      <Modal open={showAnalysisConfirm} onClose={() => setShowAnalysisConfirm(false)}>
        <h3 className="text-lg font-semibold text-surface-100 mb-2">분석을 시작할까요?</h3>
        <p className="text-sm text-surface-400 mb-4">
          논문 분석에 Gemini Pro + Claude Sonnet API를 사용합니다.
          예상 비용: <span className="text-primary-400 font-medium">$0.5 ~ $2.0</span> / 논문
        </p>
        <div className="mb-4">
          <label className="text-xs text-surface-400 block mb-1.5">
            {S.workbench.paperbananaProfile}
          </label>
          <select
            value={analysisProfileSelection}
            onChange={(e) => setAnalysisProfileSelection(e.target.value as AnalysisProfileSelection)}
            className="input w-full"
          >
            <option value="default">
              {S.workbench.useDefaultProfile(getProfileLabel(defaultPaperBananaProfile))}
            </option>
            {ANALYSIS_PROFILE_OPTIONS.map((profile) => (
              <option key={profile} value={profile}>
                {getProfileLabel(profile)}
              </option>
            ))}
          </select>
          <p className="text-2xs text-surface-500 mt-1">
            {S.workbench.paperbananaProfileHelp}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void handleStartAnalysis()}
            className="btn-primary flex-1 py-2 text-sm"
          >
            <Play className="w-4 h-4 mr-1" />
            전체 분석 시작
          </button>
          <button
            onClick={() => setShowAnalysisConfirm(false)}
            className="btn-ghost flex-1 py-2 text-sm"
          >
            나중에
          </button>
        </div>
      </Modal>

      {/* Top bar: paper info + controls */}
      <div className="shrink-0 border-b border-surface-700/45 bg-surface-900 px-4 py-2 [.light_&]:bg-white">
        <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={() => navigate('/library')}
            title={S.workbench.backToLibrary}
            aria-label={S.workbench.backToLibrary}
            className="btn-icon-subtle"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={togglePdf}
            title={pdfCollapsed ? S.workbench.showPdf : S.workbench.hidePdf}
            aria-label={pdfCollapsed ? S.workbench.showPdf : S.workbench.hidePdf}
            className="btn-icon-subtle"
          >
            {pdfCollapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-surface-100 tracking-apple-body">
              {paper.title}
            </h1>
            <div className="mt-0.5 flex items-center gap-2 text-2xs text-surface-500">
              {paper.year && <span>{paper.year}</span>}
              {paper.year && paper.domain && <span className="h-1 w-1 rounded-full bg-surface-600" />}
              {paper.domain && <span className="truncate">{paper.domain}</span>}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {analysisError && (
            <span className="text-2xs text-red-400 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {analysisError}
            </span>
          )}
          {canStartAnalysis && (
            <button
              onClick={openAnalysisConfirm}
              className="btn-primary text-xs py-1.5 px-4 shadow-none"
            >
              <Play className="w-3.5 h-3.5" />
              {paper.status === 'completed' ? S.workbench.reAnalyze : S.workbench.startAnalysis}
            </button>
          )}
          {isRunning && (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 text-xs text-primary-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{S.workbench.analyzing} {status?.progress_pct ? `${Math.round(status.progress_pct)}%` : ''}</span>
              </div>
              <button
                onClick={async () => {
                  try {
                    await cancelAnalysis(id!);
                    toast.info(S.toast.analysisCancelled);
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
      </div>

      {/* Split view */}
      <div ref={containerRef} className="flex flex-1 min-h-0">
        {/* Left panel: PDF */}
        {!pdfCollapsed && (
          <div
            className="h-full overflow-hidden relative"
            style={{ width: `${splitPosition}%` }}
          >
            <PdfViewer
              key={pdfUrl}
              pdfUrl={pdfUrl}
              title={paper.title}
              navigationRequest={navigationRequest}
            />
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
          <div className="relative flex h-full flex-col">
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
              onJumpToFigurePage={(figure) => {
                if (typeof figure.page_number !== 'number') return;
                setNavigationRequest({
                  page: figure.page_number,
                  requestId: `${figure.id ?? figure.figure_num ?? 'figure'}-${Date.now()}`,
                  source: 'figure',
                });
              }}
            />
            {screeningCompleted && id && (
              <>
                <ChatComposerFab
                  open={chatOpen}
                  onClick={() => {
                    setChatOpen((prev) => !prev);
                    setChatMinimized(false);
                  }}
                />
                <ChatPanel
                  paperId={id}
                  agentName={paper.agent_used}
                  open={chatOpen}
                  minimized={chatMinimized}
                  draft={chatDraft}
                  starters={chatStarters}
                  onClose={() => setChatOpen(false)}
                  onToggleMinimized={() => setChatMinimized((prev) => !prev)}
                  onDraftChange={setChatDraft}
                />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
