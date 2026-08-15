import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelAnalysis, getSettings, type AnalysisStatus, type Paper } from '@/lib/api';

type AnalysisTerminalState = 'cancelled' | null;

interface UseWorkbenchAnalysisControlsArgs {
  paperId?: string;
  paper: Paper | null;
  status: AnalysisStatus | null;
  isRunning: boolean;
  startAnalysis: () => Promise<boolean>;
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
  const [terminalState, setTerminalState] = useState<AnalysisTerminalState>(null);

  const openAnalysisConfirm = useCallback(() => {
    setShowAnalysisConfirm(true);
  }, []);

  const handleStartAnalysis = useCallback(async (): Promise<boolean> => {
    setTerminalState(null);
    setShowAnalysisConfirm(false);
    return startAnalysis();
  }, [startAnalysis]);

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
          if (settings.auto_analyze) {
            setTerminalState(null);
            void startAnalysis();
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

  return {
    showAnalysisConfirm,
    setShowAnalysisConfirm,
    openAnalysisConfirm,
    handleStartAnalysis,
    handleCancelAnalysis,
    canStartAnalysis,
    terminalState,
    setTerminalState,
  };
}
