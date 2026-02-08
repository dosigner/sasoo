import { useState, useEffect, useCallback, useRef } from 'react';
import {
  type AnalysisStatus,
  type AnalysisResults,
  type FigureListResponse,
  type Recipe,
  type MermaidDiagram,
  type VisualizationPlan,
  type PhaseInfo,
  runAnalysis as apiRunAnalysis,
  getAnalysisStatus,
  getAnalysisResults,
  getFigures,
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
  startAnalysis: () => Promise<void>;
  /** Manually refresh status & results */
  refresh: () => Promise<void>;
  /** Reset state (e.g., when navigating away) */
  reset: () => void;
}

// Polling intervals
const POLL_INTERVAL_ACTIVE = 2000; // 2s while actively running
// POLL_INTERVAL_IDLE removed: completed papers no longer poll

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAnalysis(paperId: string | undefined): UseAnalysisReturn {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [figures, setFigures] = useState<FigureListResponse | null>(null);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [mermaid, setMermaid] = useState<MermaidDiagram | null>(null);
  const [visualizations, setVisualizations] = useState<VisualizationPlan | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track which phases we already fetched sub-resources for
  const fetchedPhases = useRef<Set<string>>(new Set());
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const fetchingRef = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, []);

  // -----------------------------------------------------------------------
  // Fetch sub-resources when phases complete
  // -----------------------------------------------------------------------
  const fetchPhaseResources = useCallback(
    async (phaseStatus: AnalysisStatus) => {
      if (!paperId || fetchingRef.current) return;
      fetchingRef.current = true;
      try {
        const completedPhases = phaseStatus.phases
          .filter((p) => p.status === 'completed')
          .map((p) => p.phase);
        const isCompleted = phaseStatus.overall_status === 'completed';

        // Fetch results whenever any phase completes
        if (completedPhases.length > 0) {
          try {
            const res = await getAnalysisResults(paperId);
            if (mountedRef.current) setResults(res);
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch results:', err);
          }
        }

        // Fetch figures after visual phase completes
        if (
          completedPhases.includes('visual') &&
          !fetchedPhases.current.has('visual')
        ) {
          fetchedPhases.current.add('visual');
          try {
            const figs = await getFigures(paperId);
            if (mountedRef.current) setFigures(figs);
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch figures:', err);
          }
        }

        // Fetch recipe after recipe phase completes
        if (
          completedPhases.includes('recipe') &&
          !fetchedPhases.current.has('recipe')
        ) {
          fetchedPhases.current.add('recipe');
          try {
            const rec = await getRecipe(paperId);
            if (mountedRef.current) setRecipe(rec);
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch recipe:', err);
          }
        }

        // Fetch deep_dive results (text only) when deep_dive completes
        if (
          completedPhases.includes('deep_dive') &&
          !fetchedPhases.current.has('deep_dive')
        ) {
          fetchedPhases.current.add('deep_dive');
        }

        // Fetch visualizations after deep_dive completes (they generate in parallel)
        if (completedPhases.includes('deep_dive')) {
          const alreadyHasViz = fetchedPhases.current.has('visualizations');
          try {
            const viz = await getVisualizations(paperId);
            if (mountedRef.current && viz.items.length > 0) {
              setVisualizations(viz);
              fetchedPhases.current.add('visualizations');
              return;
            }
          } catch (err) {
            console.warn('[useAnalysis] Failed to fetch visualizations:', err);
          }
          if (isCompleted && !alreadyHasViz) {
            fetchedPhases.current.add('visualizations');
            try {
              const dia = await getMermaid(paperId);
              if (mountedRef.current) setMermaid(dia);
            } catch (err) {
              console.warn('[useAnalysis] Failed to fetch mermaid:', err);
            }
          }
        }
      } finally {
        fetchingRef.current = false;
      }
    },
    [paperId]
  );

  // -----------------------------------------------------------------------
  // Poll for status
  // -----------------------------------------------------------------------
  const pollStatus = useCallback(async () => {
    if (!paperId) return;

    try {
      const s = await getAnalysisStatus(paperId);
      if (!mountedRef.current) return;

      setStatus(s);
      const running = s.overall_status === 'running' || s.overall_status === 'analyzing';
      setIsRunning(running);

      // Fetch sub-resources for completed phases
      await fetchPhaseResources(s);

      // Stop polling when done or errored
      if (s.overall_status === 'completed' || s.overall_status === 'error') {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        setIsPolling(false);

        // Final fetch: ensure visualizations are loaded now that pipeline is done
        if (s.overall_status === 'completed') {
          await fetchPhaseResources(s);
        }

        if (s.overall_status === 'error') {
          const errorPhase = s.phases.find(
            (p: PhaseInfo) => p.status === 'error'
          );
          setError(
            errorPhase?.error_message || 'Analysis failed'
          );
        }
      }
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        // No analysis exists yet, that's fine
        return;
      }
      setError(err instanceof Error ? err.message : 'Failed to get status');
    }
  }, [paperId, fetchPhaseResources]);

  // Start polling
  const startPolling = useCallback(
    (interval: number = POLL_INTERVAL_ACTIVE) => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
      setIsPolling(true);
      pollingRef.current = setInterval(pollStatus, interval);
    },
    [pollStatus]
  );

  // -----------------------------------------------------------------------
  // Public methods
  // -----------------------------------------------------------------------

  const startAnalysis = useCallback(async () => {
    if (!paperId) return;

    setError(null);
    setIsRunning(true);
    setStatus(null);
    setResults(null);
    setFigures(null);
    setRecipe(null);
    setMermaid(null);
    setVisualizations(null);
    fetchedPhases.current.clear();

    try {
      await apiRunAnalysis(paperId);
      if (!mountedRef.current) return;
      // Don't set the /run response as status (it's not an AnalysisStatus).
      // Instead, poll immediately to get the real status.
      await pollStatus();
      startPolling(POLL_INTERVAL_ACTIVE);
    } catch (err) {
      if (!mountedRef.current) return;
      setIsRunning(false);
      setError(err instanceof Error ? err.message : 'Failed to start analysis');
    }
  }, [paperId, startPolling]);

  const refresh = useCallback(async () => {
    await pollStatus();
  }, [pollStatus]);

  const reset = useCallback(() => {
    setStatus(null);
    setResults(null);
    setFigures(null);
    setRecipe(null);
    setMermaid(null);
    setVisualizations(null);
    setIsRunning(false);
    setIsPolling(false);
    setError(null);
    fetchedPhases.current.clear();
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // -----------------------------------------------------------------------
  // Initial load: check if analysis already exists
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!paperId) {
      reset();
      return;
    }

    let cancelled = false;

    async function init() {
      try {
        const s = await getAnalysisStatus(paperId!);
        if (cancelled) return;
        setStatus(s);

        if (s.overall_status === 'running' || s.overall_status === 'analyzing') {
          setIsRunning(true);
          startPolling(POLL_INTERVAL_ACTIVE);
        } else if (s.overall_status === 'completed') {
          setIsRunning(false);
          await fetchPhaseResources(s);
          // No polling needed for completed papers
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // No analysis yet -- normal state
          return;
        }
        setError(
          err instanceof Error ? err.message : 'Failed to load analysis'
        );
      }
    }

    init();

    return () => {
      cancelled = true;
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId]);

  return {
    status,
    results,
    figures,
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
