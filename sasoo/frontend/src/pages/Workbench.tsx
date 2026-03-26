import { lazy, Suspense, useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getPaper,
  getPdfUrl,
  type Paper,
  type PaperBananaProfile,
  type PdfNavigationRequest,
} from '@/lib/api';
import { useAnalysis } from '@/hooks/useAnalysis';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { buildChatStarterPrompts, buildWorkbenchStatusSummary } from '@/lib/workbenchSummaries';
import WorkbenchHeader from '@/components/workbench/WorkbenchHeader';
import { ContentState, Modal } from '@/components/ui';
import { useWorkbenchLayout } from '@/hooks/useWorkbenchLayout';
import { useWorkbenchAnalysisControls } from '@/hooks/useWorkbenchAnalysisControls';
import { getAgentMeta } from '@/lib/agents';
import { AppIcon } from '@/components/icons';

const ANALYSIS_PROFILE_OPTIONS: PaperBananaProfile[] = ['fast', 'balanced', 'quality'];
type AnalysisProfileSelection = 'default' | PaperBananaProfile;
const PdfViewer = lazy(() => import('@/components/PdfViewer'));
const AnalysisPanel = lazy(() => import('@/components/AnalysisPanel'));
const ChatPanel = lazy(() => import('@/components/ChatPanel'));

function PanelFallback({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <ContentState
        icon={(props) => <AppIcon name="spinner" {...props} />}
        title={title}
        description={description}
        loading
        tone="muted"
      />
    </div>
  );
}

export default function Workbench() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [paperLoading, setPaperLoading] = useState(true);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [navigationRequest, setNavigationRequest] = useState<PdfNavigationRequest | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatDraft, setChatDraft] = useState('');

  const {
    status,
    results,
    figures,
    tables,
    recipe,
    mermaid,
    visualizations,
    isRunning,
    error: analysisError,
    startAnalysis,
  } = useAnalysis(id);

  const {
    containerRef,
    splitPosition,
    activePreset,
    isResizing,
    pdfCollapsed,
    isSnapping,
    handleMouseDown,
    handleDoubleClick,
    handleKeyDown,
    togglePdf,
    setSplitPreset,
  } = useWorkbenchLayout();

  const {
    showAnalysisConfirm,
    setShowAnalysisConfirm,
    defaultPaperBananaProfile,
    analysisProfileSelection,
    setAnalysisProfileSelection,
    getProfileLabel,
    openAnalysisConfirm,
    handleStartAnalysis,
    handleCancelAnalysis,
    canStartAnalysis,
    terminalState,
    setTerminalState,
  } = useWorkbenchAnalysisControls({
    paperId: id,
    paper,
    status,
    isRunning,
    startAnalysis,
  });

  useEffect(() => {
    if (!id) return;

    let cancelled = false;

    async function loadPaper() {
      setPaperLoading(true);
      setPaperError(null);
      try {
        const loadedPaper = await getPaper(id!);
        if (!cancelled) setPaper(loadedPaper);
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

  useEffect(() => {
    if (status?.overall_status === 'completed' || status?.overall_status === 'error') {
      setTerminalState(null);
    }
  }, [setTerminalState, status?.overall_status]);

  useEffect(() => {
    setChatOpen(false);
    setChatDraft('');
  }, [paper?.id]);

  const onConfirmAnalysis = useCallback(async (selection?: AnalysisProfileSelection) => {
    try {
      await handleStartAnalysis(selection);
      toast.success(S.toast.analysisStarted);
    } catch {
      toast.error(S.error.startAnalysisFailed);
    }
  }, [handleStartAnalysis, toast]);

  const onCancelCurrentAnalysis = useCallback(async () => {
    try {
      await handleCancelAnalysis();
      toast.info(S.toast.analysisCancelled);
    } catch {
      toast.error(S.toast.analysisError);
    }
  }, [handleCancelAnalysis, toast]);

  if (paperLoading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <ContentState
          icon={(props) => <AppIcon name="spinner" {...props} />}
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
          icon={(props) => <AppIcon name="error" {...props} />}
          title={S.workbench.loadFailed}
          description={paperError || S.workbench.notFound}
          tone="error"
        />
      </div>
    );
  }

  const pdfUrl = getPdfUrl(String(paper.id));
  const paperId = id ?? String(paper.id);
  const screeningCompleted = status?.phases.some((phase) => phase.phase === 'screening' && phase.status === 'completed') ?? false;
  const artifactStatus = {
    text_ready: paper.text_ready,
    visual_ready: paper.visual_ready,
    visual_state: paper.visual_state,
  };
  const chatStarters = buildChatStarterPrompts({
    results,
    figures: figures?.figures ?? [],
    recipe,
  });
  const statusSummary = buildWorkbenchStatusSummary({
    status,
    artifactStatus,
    figures: figures?.figures ?? [],
    tables: tables?.tables ?? [],
    recipe,
    visualizations,
    terminalState,
  });
  const agentMeta = getAgentMeta(paper.agent_used);
  const primaryActionLabel = paper.status === 'completed' ? '재분석' : '분석 시작';

  return (
    <div className="flex h-full flex-col">
      <Modal open={showAnalysisConfirm} onClose={() => setShowAnalysisConfirm(false)}>
        <h3 className="mb-2 text-lg font-semibold text-surface-100">분석을 시작할까요?</h3>
        <p className="mb-4 text-sm text-surface-400">
          논문 분석에 Gemini Pro + Claude Sonnet API를 사용합니다.
          예상 비용: <span className="font-medium text-primary-400">$0.5 ~ $2.0</span> / 논문
        </p>
        <div className="mb-4">
          <label className="mb-1.5 block text-xs text-surface-400">
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
          <p className="mt-1 text-2xs text-surface-500">
            {S.workbench.paperbananaProfileHelp}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void onConfirmAnalysis()}
            className="btn-primary flex-1 py-2 text-sm"
          >
            <AppIcon name="play" className="mr-1 h-4 w-4" />
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

      <WorkbenchHeader
        title={paper.title}
        domain={paper.domain}
        agentLabel={agentMeta?.nameKo || agentMeta?.name || paper.agent_used}
        agentColor={agentMeta?.color}
        pdfCollapsed={pdfCollapsed}
        activeSplitPreset={activePreset}
        runStateLabel={statusSummary.runStateLabel}
        trustStateLabel={statusSummary.trustStateLabel}
        analysisError={analysisError}
        canStartAnalysis={canStartAnalysis}
        isRunning={isRunning}
        primaryActionLabel={primaryActionLabel}
        onBack={() => navigate('/library')}
        onTogglePdf={togglePdf}
        onSplitPresetChange={setSplitPreset}
        onStartAnalysis={openAnalysisConfirm}
        onCancelAnalysis={() => void onCancelCurrentAnalysis()}
      />

      <div ref={containerRef} className="flex flex-1 min-h-0">
        {!pdfCollapsed && (
          <div
            className="relative h-full overflow-hidden"
            style={{ width: `${splitPosition}%` }}
          >
            <Suspense
              fallback={
                <PanelFallback
                  title={S.pdf.loading}
                  description="문서 뷰어를 준비하고 있습니다."
                />
              }
            >
              <PdfViewer
                key={pdfUrl}
                pdfUrl={pdfUrl}
                title={paper.title}
                navigationRequest={navigationRequest}
              />
            </Suspense>
            {isResizing && (
              <div className="absolute inset-0 z-10" />
            )}
          </div>
        )}

        {!pdfCollapsed && (
          <div
            role="separator"
            tabIndex={0}
            aria-valuenow={Math.round(splitPosition)}
            aria-valuemin={20}
            aria-valuemax={80}
            aria-label={S.workbench.panelResize}
            onMouseDown={handleMouseDown}
            onDoubleClick={handleDoubleClick}
            onKeyDown={handleKeyDown}
            className={`resize-handle ${isResizing ? 'active' : ''} ${isSnapping ? 'snapping' : ''}`}
          />
        )}

        <div
          className="flex h-full overflow-hidden bg-surface-900"
          style={{ width: pdfCollapsed ? '100%' : `${100 - splitPosition}%` }}
        >
          <div className="min-w-0 flex-1">
            <Suspense
              fallback={
                <PanelFallback
                  title={S.analysis.loadingResults}
                  description="분석 패널을 준비하고 있습니다."
                />
              }
            >
              <AnalysisPanel
                status={status}
                artifactStatus={artifactStatus}
                results={results}
                figures={figures}
                tables={tables}
                recipe={recipe}
                mermaid={mermaid}
                visualizations={visualizations}
                isRunning={isRunning}
                agentName={paper.agent_used}
                paperId={paperId}
                terminalState={terminalState}
                onJumpToFigurePage={(figure) => {
                  if (typeof figure.page_number !== 'number') return;
                  setNavigationRequest({
                    page: figure.page_number,
                    requestId: `${figure.id ?? figure.figure_num ?? 'figure'}-${Date.now()}`,
                    source: 'figure',
                  });
                }}
                onJumpToTablePage={(table) => {
                  if (typeof table.page_number !== 'number') return;
                  setNavigationRequest({
                    page: table.page_number,
                    requestId: `${table.id ?? table.table_num ?? 'table'}-${Date.now()}`,
                    source: 'table',
                  });
                }}
              />
            </Suspense>
          </div>
        </div>
      </div>

      <Suspense
        fallback={
          <PanelFallback
            title="채팅 불러오는 중..."
            description="에이전트 채팅 패널을 준비하고 있습니다."
          />
        }
      >
        <ChatPanel
          paperId={paperId}
          agentName={paper.agent_used}
          open={chatOpen}
          ready={screeningCompleted}
          readyMessage={S.workbench.assistantWaiting}
          draft={chatDraft}
          starters={chatStarters}
          onToggleOpen={() => setChatOpen((prev) => !prev)}
          onDraftChange={setChatDraft}
        />
      </Suspense>
    </div>
  );
}
