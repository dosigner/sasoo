import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelAnalysis, getSettings, type AnalysisRunRequest, type AnalysisStatus, type Paper, type PaperBananaProfile } from '@/lib/api';

type AnalysisProfileSelection = 'default' | PaperBananaProfile;
type AnalysisTerminalState = 'cancelled' | null;

interface UseWorkbenchAnalysisControlsArgs {
  paperId?: string;
  paper: Paper | null;
  status: AnalysisStatus | null;
  isRunning: boolean;
  startAnalysis: (request?: AnalysisRunRequest) => Promise<void>;
}

export function useWorkbenchAnalysisControls({
  paperId,
  paper,
  status,
  isRunning,
  startAnalysis,
}: UseWorkbenchAnalysisControlsArgs) {
  const autoStartedRef = useRef(false);
  const [showAnalysisConfirm, setShowAnalysisConfirm] = useState(false);
  const [defaultPaperBananaProfile, setDefaultPaperBananaProfile] = useState<PaperBananaProfile>('fast');
  const [analysisProfileSelection, setAnalysisProfileSelection] = useState<AnalysisProfileSelection>('default');
  const [terminalState, setTerminalState] = useState<AnalysisTerminalState>(null);

  const getProfileLabel = useCallback((profile: PaperBananaProfile) => {
    if (profile === 'fast') return '빠름';
    if (profile === 'balanced') return '균형';
    return '고품질';
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
    setTerminalState(null);
    setShowAnalysisConfirm(false);
    await startAnalysis({ paperbanana_profile: effectiveProfile });
  }, [analysisProfileSelection, defaultPaperBananaProfile, startAnalysis]);

  const handleCancelAnalysis = useCallback(async () => {
    if (!paperId) return;
    await cancelAnalysis(paperId);
    setTerminalState('cancelled');
  }, [paperId]);

  const canStartAnalysis =
    !isRunning && (paper?.status === 'pending' || paper?.status === 'completed' || paper?.status === 'error');

  useEffect(() => {
    if (
      paper &&
      paper.status === 'pending' &&
      !isRunning &&
      !status &&
      !autoStartedRef.current
    ) {
      autoStartedRef.current = true;
      getSettings()
        .then((settings) => {
          setDefaultPaperBananaProfile(settings.paperbanana_profile || 'fast');
          if (settings.auto_analyze) {
            setTerminalState(null);
            startAnalysis({
              paperbanana_profile: settings.paperbanana_profile || 'fast',
            });
          } else {
            openAnalysisConfirm();
          }
        })
        .catch(() => {
          openAnalysisConfirm();
        });
    }
  }, [paper, isRunning, openAnalysisConfirm, startAnalysis, status]);

  useEffect(() => {
    autoStartedRef.current = false;
    setShowAnalysisConfirm(false);
    setTerminalState(null);
  }, [paperId]);

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
  }, [paperId]);

  return {
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
  };
}
