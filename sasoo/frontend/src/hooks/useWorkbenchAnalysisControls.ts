import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelAnalysis, getSettings, type AnalysisRunRequest, type AnalysisStatus, type Paper, type PaperBananaProfile } from '@/lib/api';

type AnalysisProfileSelection = 'default' | PaperBananaProfile;
type AnalysisTerminalState = 'cancelled' | null;

interface UseWorkbenchAnalysisControlsArgs {
  paperId?: string;
  paper: Paper | null;
  status: AnalysisStatus | null;
  isRunning: boolean;
  startAnalysis: (request?: AnalysisRunRequest) => Promise<boolean>;
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
  ): Promise<boolean> => {
    const effectiveProfile =
      selection === 'default' ? defaultPaperBananaProfile : selection;
    setTerminalState(null);
    setShowAnalysisConfirm(false);
    return startAnalysis({ paperbanana_profile: effectiveProfile });
  }, [analysisProfileSelection, defaultPaperBananaProfile, startAnalysis]);

  const handleCancelAnalysis = useCallback(async () => {
    if (!paperId) return;
    await cancelAnalysis(paperId);
    setTerminalState('cancelled');
  }, [paperId]);

  // 백엔드는 completed/error/cancelled 상태 모두 재분석을 허용한다(run이 terminal이면
  // upsert_queued가 원자적으로 queued 리셋을 허용) — cancelled를 빠뜨리면 취소된 논문을
  // 프론트에서 재분석할 방법이 없어진다.
  const canStartAnalysis =
    !isRunning &&
    (paper?.status === 'pending' ||
      paper?.status === 'completed' ||
      paper?.status === 'error' ||
      paper?.status === 'cancelled');

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
            void startAnalysis({
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
