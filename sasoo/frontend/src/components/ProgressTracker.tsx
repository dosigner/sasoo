import type { PhaseInfo, AnalysisPhase } from '@/lib/api';
import { STAGE_NAMES } from '@/lib/workbenchSummaries';
import AppIcon from '@/components/icons/AppIcon';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProgressTrackerProps {
  phases: PhaseInfo[];
  overallProgress: number;
  variant?: 'default' | 'minimal';
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// 상태부 진행 레일(STAGE_NAMES)과 동일한 단계명을 재사용해 표기를 통일한다.
const PHASE_META: Record<AnalysisPhase, { label: string }> = {
  screening: { label: STAGE_NAMES[0] },
  citation: { label: STAGE_NAMES[1] },
  visual: { label: STAGE_NAMES[2] },
  recipe: { label: STAGE_NAMES[3] },
  deep_dive: { label: STAGE_NAMES[4] },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProgressTracker({
  phases,
  overallProgress: _overallProgress,
  variant: _variant,
}: ProgressTrackerProps) {
  // I9: 'glass rounded-2xl' 박스·'분석 진행' 헤더·자체 진행바·%는 전부 삭제한다.
  // 전체 진행률은 상태부 레일(AnalysisPanel의 workbenchStatus.progressRatio)이 담당하고,
  // 이 컴포넌트는 단계 리스트만 보여준다.
  return (
    <div>
      {/* Phase steps: slim vertical list (전체 진행률은 상태부가 담당) */}
      <div className="flex flex-col gap-2">
        {phases.map((phase) => {
          const meta = PHASE_META[phase.phase];
          if (!meta) return null;

          return (
            <div key={phase.phase} className="flex items-center gap-2">
              {phase.status === 'completed' ? (
                <AppIcon name="success" className="w-3.5 h-3.5 shrink-0 text-success" />
              ) : phase.status === 'error' ? (
                <AppIcon name="error" className="w-3.5 h-3.5 shrink-0 text-danger" />
              ) : (
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    phase.status === 'running' ? 'bg-accent' : 'bg-border'
                  }`}
                />
              )}
              <span
                className={`text-xs ${
                  phase.status === 'running'
                    ? 'font-[650] text-fg'
                    : 'font-normal text-fg-muted'
                }`}
              >
                {meta.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
