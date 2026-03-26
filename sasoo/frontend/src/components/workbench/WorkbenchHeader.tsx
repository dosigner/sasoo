import { AppIcon } from '@/components/icons';
import type { WorkbenchSplitPreset } from '@/hooks/useWorkbenchLayout';

function rgbaFromHex(color: string, alpha: number): string {
  const cleaned = color.replace('#', '');
  if (cleaned.length !== 6) return color;

  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function buildAgentPillStyle(color?: string | null): React.CSSProperties | undefined {
  if (!color) return undefined;

  return {
    color,
    borderColor: rgbaFromHex(color, 0.24),
    backgroundColor: rgbaFromHex(color, 0.1),
  };
}

interface WorkbenchHeaderProps {
  title: string;
  domain?: string | null;
  agentLabel?: string | null;
  agentColor?: string | null;
  pdfCollapsed: boolean;
  activeSplitPreset: WorkbenchSplitPreset | null;
  runStateLabel: string;
  trustStateLabel: string;
  analysisError?: string | null;
  canStartAnalysis: boolean;
  isRunning: boolean;
  primaryActionLabel: string;
  onBack: () => void;
  onTogglePdf: () => void;
  onSplitPresetChange: (preset: WorkbenchSplitPreset) => void;
  onStartAnalysis: () => void;
  onCancelAnalysis: () => void;
}

export default function WorkbenchHeader({
  title,
  domain,
  agentLabel,
  agentColor,
  pdfCollapsed,
  activeSplitPreset,
  runStateLabel,
  trustStateLabel,
  analysisError,
  canStartAnalysis,
  isRunning,
  primaryActionLabel,
  onBack,
  onTogglePdf,
  onSplitPresetChange,
  onStartAnalysis,
  onCancelAnalysis,
}: WorkbenchHeaderProps) {
  const splitPresets: Array<{ label: string; value: WorkbenchSplitPreset }> = [
    { label: '1:2', value: '1:2' },
    { label: '중앙', value: 'center' },
    { label: '2:1', value: '2:1' },
  ];

  return (
    <div className="shrink-0 border-b border-surface-700/45 bg-surface-900/95 px-4 py-3 backdrop-blur [.light_&]:bg-white/95">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <button
            type="button"
            onClick={onBack}
            title="라이브러리"
            aria-label="라이브러리"
            className="btn-icon-subtle mt-0.5"
          >
            <AppIcon name="back" className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onTogglePdf}
            title={pdfCollapsed ? 'PDF 표시' : 'PDF 숨기기'}
            aria-label={pdfCollapsed ? 'PDF 표시' : 'PDF 숨기기'}
            className="btn-icon-subtle mt-0.5"
          >
            {pdfCollapsed ? (
              <AppIcon name="panel-open" className="w-4 h-4" />
            ) : (
              <AppIcon name="panel-close" className="w-4 h-4" />
            )}
          </button>

          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-surface-100 tracking-apple-body [.light_&]:text-surface-900">
              {title}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-surface-500">
              {domain && <span className="status-pill border-primary-500/20 bg-primary-500/10 text-primary-300">{domain}</span>}
              {agentLabel && (
                <span
                  className={agentColor ? 'status-pill' : 'status-pill border-surface-700/50 bg-surface-800/80 text-surface-300'}
                  style={buildAgentPillStyle(agentColor)}
                >
                  {agentColor && (
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: agentColor }}
                    />
                  )}
                  {agentLabel}
                </span>
              )}
              <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-300">
                {runStateLabel}
              </span>
              <span className="status-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                {trustStateLabel}
              </span>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-start gap-2">
          <div className="flex items-center gap-2">
            {analysisError && (
              <span className="flex items-center gap-1 text-2xs text-red-400">
                <AppIcon name="error" className="w-3 h-3" />
                {analysisError}
              </span>
            )}

            <div className="inline-flex items-center rounded-full border border-surface-700/60 bg-surface-800/80 p-1 [.light_&]:border-surface-200 [.light_&]:bg-surface-100">
              {splitPresets.map((preset) => {
                const isActive = activeSplitPreset === preset.value;
                return (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => onSplitPresetChange(preset.value)}
                    disabled={pdfCollapsed}
                    aria-pressed={isActive}
                    className={`rounded-full px-3 py-1.5 text-2xs font-medium transition-colors ${
                      isActive
                        ? 'bg-primary-600 text-white'
                        : 'text-surface-400 hover:bg-surface-700/80 hover:text-surface-100 [.light_&]:text-surface-600 [.light_&]:hover:bg-white [.light_&]:hover:text-surface-900'
                    } disabled:cursor-not-allowed disabled:opacity-40`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>

            {canStartAnalysis && (
              <button
                onClick={onStartAnalysis}
                className="btn-primary px-4 py-2 text-xs shadow-none"
              >
                <AppIcon name="play" className="w-3.5 h-3.5" />
                {primaryActionLabel}
              </button>
            )}

            {isRunning && (
              <button
                onClick={onCancelAnalysis}
                className="btn-secondary border-red-500/20 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10"
                title="분석 취소"
              >
                <AppIcon name="stop" className="w-3 h-3" />
                취소
              </button>
            )}

            {isRunning && (
              <span className="flex items-center gap-1 text-xs text-primary-400">
                <AppIcon name="spinner" className="w-4 h-4 animate-spin" />
                실행 중
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
