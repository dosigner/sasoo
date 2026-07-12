import {
  FileSearch,
  BookOpen,
  ImageIcon,
  FlaskConical,
  GitBranch,
  Check,
  Loader2,
  Circle,
  AlertCircle,
} from 'lucide-react';
import type { PhaseInfo, PhaseStatusValue, AnalysisPhase } from '@/lib/api';
import { S } from '@/lib/strings';

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

const PHASE_META: Record<AnalysisPhase, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
}> = {
  screening: {
    icon: FileSearch,
    label: S.progressTracker.phase1,
    description: S.progressTracker.phase1Desc,
  },
  citation: {
    icon: BookOpen,
    label: S.progressTracker.phase2,
    description: S.progressTracker.phase2Desc,
  },
  visual: {
    icon: ImageIcon,
    label: S.progressTracker.phase3,
    description: S.progressTracker.phase3Desc,
  },
  recipe: {
    icon: FlaskConical,
    label: S.progressTracker.phase4,
    description: S.progressTracker.phase4Desc,
  },
  deep_dive: {
    icon: GitBranch,
    label: S.progressTracker.phase5,
    description: S.progressTracker.phase5Desc,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getStatusIcon(status: PhaseStatusValue): React.ReactNode {
  switch (status) {
    case 'completed':
      return <Check className="w-4 h-4 text-success" />;
    case 'running':
      return <Loader2 className="w-4 h-4 text-accent animate-spin" />;
    case 'error':
      return <AlertCircle className="w-4 h-4 text-danger" />;
    case 'pending':
    default:
      return <Circle className="w-4 h-4 text-fg-muted" />;
  }
}

function getPhaseClasses(status: PhaseStatusValue): string {
  switch (status) {
    case 'completed':
      return 'border-success/30 bg-success/5';
    case 'running':
      return 'border-accent/50 bg-accent/5 ring-1 ring-accent/20';
    case 'error':
      return 'border-danger/30 bg-danger/5';
    case 'pending':
    default:
      return 'border-border bg-surface/50';
  }
}

function getConnectorClasses(
  currentStatus: PhaseStatusValue,
  nextStatus: PhaseStatusValue
): string {
  if (currentStatus === 'completed') {
    return 'bg-success';
  }
  if (currentStatus === 'running') {
    return 'bg-gradient-to-r from-accent to-border';
  }
  if (nextStatus !== 'pending') {
    return 'bg-fg-muted';
  }
  return 'bg-border';
}

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

      {/* Phase steps */}
      <div className="flex items-start justify-between gap-1">
        {phases.map((phase, index) => {
          const meta = PHASE_META[phase.phase];
          if (!meta) return null;

          const Icon = meta.icon;

          return (
            <div key={phase.phase} className="flex items-center flex-1 last:flex-none">
              {/* Phase card */}
              <div
                className={`flex flex-col items-center gap-2 rounded-lg border p-3 min-w-[100px] transition-all duration-300 ${getPhaseClasses(phase.status)}`}
              >
                <div className="flex items-center gap-1.5">
                  {getStatusIcon(phase.status)}
                  <Icon className="w-4 h-4 text-fg-secondary" />
                </div>
                <div className="text-center">
                  <div className="text-2xs font-medium text-fg-secondary">
                    {meta.label}
                  </div>
                  <div className="text-2xs text-fg-muted mt-0.5">
                    {meta.description}
                  </div>
                </div>
                {phase.status === 'running' && (
                  <div className="w-full h-0.5 bg-border rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent rounded-full animate-pulse"
                    />
                  </div>
                )}
              </div>

              {/* Connector line */}
              {index < phases.length - 1 && (
                <div
                  className={`h-0.5 flex-1 mx-1 rounded-full transition-colors duration-300 ${getConnectorClasses(phase.status, phases[index + 1]?.status || 'pending')}`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
