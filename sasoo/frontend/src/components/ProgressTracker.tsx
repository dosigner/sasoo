import {
  FileSearch,
  ImageIcon,
  FlaskConical,
  GitBranch,
  Check,
  Loader2,
  Circle,
  AlertCircle,
} from 'lucide-react';
import type { PhaseInfo, PhaseStatusValue, AnalysisPhase } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProgressTrackerProps {
  phases: PhaseInfo[];
  overallProgress: number;
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
    label: 'Phase 1',
    description: 'Screening',
  },
  visual: {
    icon: ImageIcon,
    label: 'Phase 2',
    description: 'Visual',
  },
  recipe: {
    icon: FlaskConical,
    label: 'Phase 3',
    description: 'Recipe',
  },
  deep_dive: {
    icon: GitBranch,
    label: 'Phase 4',
    description: 'Deep Dive',
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getStatusIcon(status: PhaseStatusValue): React.ReactNode {
  switch (status) {
    case 'completed':
      return <Check className="w-4 h-4 text-emerald-400" />;
    case 'running':
      return <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />;
    case 'error':
      return <AlertCircle className="w-4 h-4 text-red-400" />;
    case 'pending':
    default:
      return <Circle className="w-4 h-4 text-surface-500" />;
  }
}

function getPhaseClasses(status: PhaseStatusValue): string {
  switch (status) {
    case 'completed':
      return 'border-emerald-500/30 bg-emerald-500/5';
    case 'running':
      return 'border-primary-500/50 bg-primary-500/5 ring-1 ring-primary-500/20';
    case 'error':
      return 'border-red-500/30 bg-red-500/5';
    case 'pending':
    default:
      return 'border-surface-700 bg-surface-800/50';
  }
}

function getConnectorClasses(
  currentStatus: PhaseStatusValue,
  nextStatus: PhaseStatusValue
): string {
  if (currentStatus === 'completed') {
    return 'bg-emerald-500';
  }
  if (currentStatus === 'running') {
    return 'bg-gradient-to-r from-primary-500 to-surface-600';
  }
  if (nextStatus !== 'pending') {
    return 'bg-surface-500';
  }
  return 'bg-surface-700';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProgressTracker({
  phases,
  overallProgress,
}: ProgressTrackerProps) {
  const isActive = phases.some((p) => p.status === 'running');
  const isComplete = phases.every((p) => p.status === 'completed');

  return (
    <div className="card px-5 py-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-surface-200">
            Analysis Progress
          </h3>
          {isActive && (
            <span className="badge-primary text-2xs">
              <span className="w-1.5 h-1.5 rounded-full bg-primary-400 animate-pulse mr-1" />
              Running
            </span>
          )}
          {isComplete && (
            <span className="badge-success text-2xs">Complete</span>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs text-surface-400">
          <span className="font-mono tabular-nums">
            {Math.round(overallProgress)}%
          </span>
        </div>
      </div>

      {/* Overall progress bar */}
      <div className="h-1 bg-surface-700 rounded-full mb-5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${overallProgress}%`,
            background: isComplete
              ? '#10b981'
              : 'linear-gradient(90deg, #6366f1, #818cf8)',
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
                  <Icon className="w-4 h-4 text-surface-300" />
                </div>
                <div className="text-center">
                  <div className="text-2xs font-medium text-surface-300">
                    {meta.label}
                  </div>
                  <div className="text-2xs text-surface-500 mt-0.5">
                    {meta.description}
                  </div>
                </div>
                {phase.status === 'running' && (
                  <div className="w-full h-0.5 bg-surface-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 rounded-full animate-pulse"
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
