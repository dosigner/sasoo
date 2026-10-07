import type { PhaseInfo, AnalysisPhase } from '@/lib/api';
import { STAGE_NAMES } from '@/lib/workbenchSummaries';
import { S } from '@/lib/strings';
import AppIcon from '@/components/icons/AppIcon';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProgressTrackerProps {
  phases: PhaseInfo[];
  /** 단계를 누르면 그 결과가 있는 섹션이나 탭으로 이동한다. 대기 중인 단계는 누를 수 없다. */
  onSelect?: (phase: AnalysisPhase) => void;
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

// 상태부 진행 막대 바로 아래에 붙는 한 줄 단계 목록이다. 요약 탭 본문에 따로 두던
// 세로 목록과 탭 제목 옆 n/5 표시는 상태부와 같은 정보를 반복해서 없앴다.
export default function ProgressTracker({ phases, onSelect }: ProgressTrackerProps) {
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-1" aria-label={S.workbench.statusRailTitle}>
      {phases.map((phase) => {
        const meta = PHASE_META[phase.phase];
        if (!meta) return null;
        const running = phase.status === 'running';

        return (
          <li key={phase.phase}>
            <button
              type="button"
              onClick={() => onSelect?.(phase.phase)}
              disabled={!onSelect || phase.status === 'pending'}
              aria-current={running ? 'step' : undefined}
              className="inline-flex items-center gap-1.5 rounded-control px-1.5 py-0.5 text-xs transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-default disabled:hover:bg-transparent"
            >
              {phase.status === 'completed' ? (
                <AppIcon name="success" className="h-3.5 w-3.5 shrink-0 text-success" />
              ) : phase.status === 'error' ? (
                <AppIcon name="error" className="h-3.5 w-3.5 shrink-0 text-danger" />
              ) : (
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    running ? 'bg-accent animate-pulse-subtle' : 'bg-border'
                  }`}
                />
              )}
              <span className={running ? 'font-[650] text-fg' : 'font-normal text-fg-muted'}>
                {meta.label}{phase.status === 'skipped' ? ` (${S.status.skipped})` : ''}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
