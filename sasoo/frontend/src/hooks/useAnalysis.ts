import { useState, useEffect, useCallback, useRef } from 'react';
import { S } from '@/lib/strings';
import {
  type AnalysisStatus,
  type AnalysisResults,
  type FigureListResponse,
  type TableListResponse,
  type Recipe,
  type MermaidDiagram,
  type VisualizationPlan,
  type PhaseInfo,
  runAnalysis as apiRunAnalysis,
  getAnalysisStatus,
  getAnalysisResults,
  getFigures,
  getTables,
  getRecipe,
  getMermaid,
  getVisualizations,
  ApiError,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UseAnalysisReturn {
  /** Current analysis status (phases, progress, etc.) */
  status: AnalysisStatus | null;
  /** Partial results -- each phase result appears as it completes */
  results: AnalysisResults | null;
  /** Extracted figures (available after Phase 2) */
  figures: FigureListResponse | null;
  /** Extracted tables (available after visual phase) */
  tables: TableListResponse | null;
  /** Reproducibility recipe (available after Phase 3) */
  recipe: Recipe | null;
  /** Mermaid diagram (legacy, available after Phase 4) */
  mermaid: MermaidDiagram | null;
  /** Visualization plan: up to 5 items, Mermaid + PaperBanana mix */
  visualizations: VisualizationPlan | null;
  /** Whether the analysis is currently running */
  isRunning: boolean;
  /** Whether we are polling for status */
  isPolling: boolean;
  /** Error from the last operation */
  error: string | null;
  /** Start analysis for the given paper */
  startAnalysis: () => Promise<boolean>;
  /** Manually refresh status & results */
  refresh: () => Promise<void>;
  /** Reset state (e.g., when navigating away) */
  reset: () => void;
}

// Polling intervals
const POLL_INTERVAL_ACTIVE = 2000; // 2s while actively running
const VISUAL_REFRESH_RETRY_MS = 1500;
function resultsKey(status: AnalysisStatus): string {
  return JSON.stringify([
    status.overall_status === 'completed',
    status.phases.filter((phase) => phase.status === 'completed')
      .map((phase) => [phase.phase, phase.completed_at]),
  ]);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAnalysis(paperId: string | undefined): UseAnalysisReturn {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [figures, setFigures] = useState<FigureListResponse | null>(null);
  const [tables, setTables] = useState<TableListResponse | null>(null);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [mermaid, setMermaid] = useState<MermaidDiagram | null>(null);
  const [visualizations, setVisualizations] = useState<VisualizationPlan | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track which phases we already fetched sub-resources for
  const fetchedPhases = useRef<Set<string>>(new Set());
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const visualRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const resourceLoadRef = useRef<Promise<void> | null>(null);
  const fetchedResultsKey = useRef<string | null>(null);
  const statusRequestRef = useRef(0);
  const analysisSessionRef = useRef(0);

  const clearPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const clearVisualRetry = useCallback(() => {
    if (visualRetryRef.current) {
      clearTimeout(visualRetryRef.current);
      visualRetryRef.current = null;
    }
  }, []);

  const isSessionActive = useCallback((sessionId: number) => {
    return mountedRef.current && analysisSessionRef.current === sessionId;
  }, []);

  const clearAnalysisState = useCallback(() => {
    setStatus(null);
    setResults(null);
    setFigures(null);
    setTables(null);
    setRecipe(null);
    setMermaid(null);
    setVisualizations(null);
    setIsRunning(false);
    setIsPolling(false);
    setError(null);
    fetchedPhases.current.clear();
    fetchedResultsKey.current = null;
    statusRequestRef.current += 1;
    resourceLoadRef.current = null;
    clearPolling();
    clearVisualRetry();
  }, [clearPolling, clearVisualRetry]);

  const beginNewSession = useCallback(() => {
    const sessionId = analysisSessionRef.current + 1;
    analysisSessionRef.current = sessionId;
    clearAnalysisState();
    return sessionId;
  }, [clearAnalysisState]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearPolling();
      clearVisualRetry();
    };
  }, [clearPolling, clearVisualRetry]);

  // -----------------------------------------------------------------------
  // Fetch sub-resources when phases complete
  // -----------------------------------------------------------------------
  const fetchExistingVisualAssets = useCallback(
    async (targetPaperId: string, sessionId: number) => {
      const [figuresResult, tablesResult] = await Promise.allSettled([
        getFigures(targetPaperId),
        getTables(targetPaperId),
      ]);

      if (!isSessionActive(sessionId)) return;

      if (figuresResult.status === 'fulfilled') {
        setFigures(figuresResult.value);
      } else {
        console.warn('[useAnalysis] Failed to prefetch figures:', figuresResult.reason);
      }

      if (tablesResult.status === 'fulfilled') {
        setTables(tablesResult.value);
      } else {
        console.warn('[useAnalysis] Failed to prefetch tables:', tablesResult.reason);
      }

      const figuresReady =
        figuresResult.status === 'fulfilled'
          ? figuresResult.value.visual_state !== 'running'
          : true;
      const tablesReady =
        tablesResult.status === 'fulfilled'
          ? tablesResult.value.visual_state !== 'running'
          : true;

      if (figuresReady && tablesReady) {
        clearVisualRetry();
      }
    },
    [clearVisualRetry, isSessionActive]
  );

  const fetchPhaseResources = useCallback(
    async (phaseStatus: AnalysisStatus, targetPaperId: string, sessionId: number) => {
      while (resourceLoadRef.current) await resourceLoadRef.current;
      if (!isSessionActive(sessionId)) return;
      const load = (async () => {
        const completedPhases = phaseStatus.phases
          .filter((p) => p.status === 'completed')
          .map((p) => p.phase);
        const isCompleted = phaseStatus.overall_status === 'completed';

        // Record only successful loads so the next poll retries failures.
        const key = resultsKey(phaseStatus);
        if (fetchedResultsKey.current !== key) {
          try {
            const res = await getAnalysisResults(targetPaperId);
            if (!isSessionActive(sessionId)) return;
            setResults(res);
            fetchedResultsKey.current = key;
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch results:', err);
          }
        }

        // Fetch figures after visual phase completes
        if (
          completedPhases.includes('visual') &&
          !fetchedPhases.current.has('visual')
        ) {
          if (!isSessionActive(sessionId)) return;
          fetchedPhases.current.add('visual');
          try {
            await fetchExistingVisualAssets(targetPaperId, sessionId);
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch visual artifacts:', err);
          }
        }

        // Fetch recipe after recipe phase completes
        if (
          completedPhases.includes('recipe') &&
          !fetchedPhases.current.has('recipe')
        ) {
          if (!isSessionActive(sessionId)) return;
          try {
            const rec = await getRecipe(targetPaperId);
            if (!isSessionActive(sessionId)) return;
            setRecipe(rec);
            fetchedPhases.current.add('recipe');
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch recipe:', err);
          }
        }

        // Fetch deep_dive results (text only) when deep_dive completes
        if (
          completedPhases.includes('deep_dive') &&
          !fetchedPhases.current.has('deep_dive')
        ) {
          if (!isSessionActive(sessionId)) return;
          fetchedPhases.current.add('deep_dive');
        }

        // Fetch visualizations after deep_dive completes (they generate in parallel)
        if (completedPhases.includes('deep_dive')) {
          const alreadyHasViz = fetchedPhases.current.has('visualizations');
          try {
            const viz = await getVisualizations(targetPaperId);
            if (!isSessionActive(sessionId)) return;
            if (viz.items.length > 0) {
              setVisualizations(viz);
              fetchedPhases.current.add('visualizations');
              return;
            }
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch visualizations:', err);
          }
          if (isCompleted && !alreadyHasViz) {
            if (!isSessionActive(sessionId)) return;
            fetchedPhases.current.add('visualizations');
            try {
              const dia = await getMermaid(targetPaperId);
              if (!isSessionActive(sessionId)) return;
              setMermaid(dia);
            } catch (err) {
              console.warn('[useAnalysis] Failed to fetch mermaid:', err);
            }
          }
        }

      })();
      resourceLoadRef.current = load;
      try {
        await load;
      } finally {
        if (resourceLoadRef.current === load) resourceLoadRef.current = null;
      }
    },
    [fetchExistingVisualAssets, isSessionActive]
  );

  useEffect(() => {
    const needsRetry =
      figures?.visual_state === 'running' || tables?.visual_state === 'running';

    if (!paperId || !needsRetry) {
      clearVisualRetry();
      return;
    }

    const sessionId = analysisSessionRef.current;
    clearVisualRetry();
    visualRetryRef.current = setTimeout(() => {
      void fetchExistingVisualAssets(paperId, sessionId);
    }, VISUAL_REFRESH_RETRY_MS);

    return clearVisualRetry;
  }, [paperId, figures, tables, clearVisualRetry, fetchExistingVisualAssets]);

  // -----------------------------------------------------------------------
  // Poll for status
  // -----------------------------------------------------------------------
  const pollStatus = useCallback(async (targetPaperId?: string, sessionId?: number) => {
    const activePaperId = targetPaperId ?? paperId;
    const activeSessionId = sessionId ?? analysisSessionRef.current;
    if (!activePaperId) return;
    const requestId = ++statusRequestRef.current;

    try {
      const s = await getAnalysisStatus(activePaperId);
      if (!isSessionActive(activeSessionId) || requestId !== statusRequestRef.current) return;

      setStatus(s);
      const running = s.overall_status === 'running' || s.overall_status === 'analyzing';
      setIsRunning(running);

      // Fetch sub-resources for completed phases
      await fetchPhaseResources(s, activePaperId, activeSessionId);
      if (!isSessionActive(activeSessionId) || requestId !== statusRequestRef.current) return;

      // Stop polling when done or errored
      if ((s.overall_status === 'completed' || s.overall_status === 'error')
          && fetchedResultsKey.current === resultsKey(s)) {
        clearPolling();
        setIsPolling(false);
      }

      if (s.overall_status === 'error') {
          const errorPhase = s.phases.find(
            (p: PhaseInfo) => p.status === 'error'
          );
          setError(
            errorPhase?.error_message || S.error.occurred
          );
      }
      return s;
    } catch (err) {
      if (!isSessionActive(activeSessionId) || requestId !== statusRequestRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        // No analysis exists yet, that's fine
        return;
      }
      if (err instanceof Error) console.warn('[analysis] status error:', err.message);
      setError(S.error.getStatusFailed);
    }
  }, [paperId, clearPolling, fetchPhaseResources, isSessionActive]);

  // Start polling
  const startPolling = useCallback(
    (targetPaperId: string, sessionId: number, interval: number = POLL_INTERVAL_ACTIVE) => {
      clearPolling();
      if (!isSessionActive(sessionId)) return;
      setIsPolling(true);
      pollingRef.current = setInterval(() => {
        void pollStatus(targetPaperId, sessionId);
      }, interval);
    },
    [clearPolling, isSessionActive, pollStatus]
  );

  // -----------------------------------------------------------------------
  // Public methods
  // -----------------------------------------------------------------------

  const startAnalysis = useCallback(async (): Promise<boolean> => {
    if (!paperId) return false;
    const sessionId = beginNewSession();
    if (!isSessionActive(sessionId)) return false;
    setIsRunning(true);

    try {
      await apiRunAnalysis(paperId);
      if (!isSessionActive(sessionId)) return true;
      // Don't set the /run response as status (it's not an AnalysisStatus).
      // Instead, poll immediately to get the real status.
      startPolling(paperId, sessionId, POLL_INTERVAL_ACTIVE);
      await pollStatus(paperId, sessionId);
      return true;
    } catch (err) {
      if (!isSessionActive(sessionId)) return false;
      setIsRunning(false);
      if (err instanceof Error) console.warn('[analysis] start error:', err.message);
      setError(S.error.startAnalysisFailed);
      return false;
    }
  }, [paperId, beginNewSession, isSessionActive, pollStatus, startPolling]);

  const refresh = useCallback(async () => {
    const sessionId = analysisSessionRef.current;
    await resourceLoadRef.current;
    if (!isSessionActive(sessionId)) return;
    fetchedResultsKey.current = null;
    fetchedPhases.current.clear();
    const refreshed = await pollStatus();
    if (paperId && refreshed && isSessionActive(sessionId)
        && fetchedResultsKey.current !== resultsKey(refreshed)) {
      startPolling(paperId, sessionId);
    }
  }, [isSessionActive, paperId, pollStatus, startPolling]);

  const reset = useCallback(() => {
    beginNewSession();
  }, [beginNewSession]);

  // -----------------------------------------------------------------------
  // Initial load: check if analysis already exists
  // -----------------------------------------------------------------------
  useEffect(() => {
    const sessionId = beginNewSession();

    if (!paperId) {
      return;
    }
    const targetPaperId = paperId;

    let cancelled = false;

    async function init() {
      try {
        const s = await getAnalysisStatus(targetPaperId);
        if (cancelled || !isSessionActive(sessionId)) return;
        setStatus(s);
        setIsRunning(s.overall_status === 'running' || s.overall_status === 'analyzing');
        await fetchExistingVisualAssets(targetPaperId, sessionId);
        if (cancelled || !isSessionActive(sessionId)) return;
        await fetchPhaseResources(s, targetPaperId, sessionId);
        if (cancelled || !isSessionActive(sessionId)) return;

        if (s.overall_status === 'running' || s.overall_status === 'analyzing') {
          setIsRunning(true);
          startPolling(targetPaperId, sessionId, POLL_INTERVAL_ACTIVE);
        } else if (s.overall_status === 'completed') {
          setIsRunning(false);
          if (fetchedResultsKey.current !== resultsKey(s)) {
            startPolling(targetPaperId, sessionId, POLL_INTERVAL_ACTIVE);
          }
          // Completed papers stop polling after a successful result load.
        }
      } catch (err) {
        if (cancelled || !isSessionActive(sessionId)) return;
        if (err instanceof ApiError && err.status === 404) {
          // No analysis yet -- normal state
          return;
        }
        if (err instanceof Error) console.warn('[analysis] load error:', err.message);
        setError(S.error.loadAnalysisFailed);
      }
    }

    init();

    return () => {
      cancelled = true;
      if (analysisSessionRef.current === sessionId) {
        clearPolling();
        clearVisualRetry();
        resourceLoadRef.current = null;
      }
    };
  }, [paperId, beginNewSession, clearPolling, clearVisualRetry, fetchExistingVisualAssets, fetchPhaseResources, isSessionActive, startPolling]);

  return {
    status,
    results,
    figures,
    tables,
    recipe,
    mermaid,
    visualizations,
    isRunning,
    isPolling,
    error,
    startAnalysis,
    refresh,
    reset,
  };
}
