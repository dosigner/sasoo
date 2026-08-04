import type { PhaseInfo, AnalysisPhase } from '@/lib/api';
import { S } from '@/lib/strings';
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
  overallProgress,
  variant: _variant,
}: ProgressTrackerProps) {
  const isActive = phases.some((p) => p.status === 'running');
  const isComplete = phases.every((p) => p.status === 'completed');

  return (
    <div className="glass rounded-2xl px-5 py-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-fg">
            {S.progressTracker.title}
          </h3>
          {isActive && (
            <span className="badge-primary text-2xs">
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse mr-1" />
              {S.status.running}
            </span>
          )}
          {isComplete && (
            <span className="badge-success text-2xs">{S.status.complete}</span>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs text-fg-muted">
          <span className="font-mono tabular-nums">
            {Math.round(overallProgress)}%
          </span>
        </div>
      </div>

      {/* Overall progress bar */}
      <div className="h-1 bg-border rounded-full mb-5 overflow-hidden">
        <div
          className="h-full w-full transition-transform duration-300 ease-out"
          style={{
            transformOrigin: 'left',
            transform: `scaleX(${overallProgress / 100})`,
            background: isComplete
              ? 'rgb(var(--success))'
              : 'linear-gradient(90deg, rgb(var(--accent)), rgb(var(--accent-hover)))',
          }}
        />
      </div>

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
